from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from data_formulator.insight.egress import (
    DataEgressDenied,
    DataEgressPolicy,
    RemoteAnalysisService,
    RemoteAnalysisServiceRegistry,
    build_egress_frontend_config,
    configure_litellm_egress,
    configure_remote_analysis_registry,
    enforce_bia_workspace_policy,
    load_remote_analysis_services,
)


def service(*, enabled: bool = True) -> RemoteAnalysisService:
    return RemoteAnalysisService.from_mapping(
        {
            "service_id": "tsfl",
            "display_name": "Forecast service",
            "endpoint": "https://forecast.example.com/api",
            "enabled": enabled,
            "allowed_data_types": ["time_series_rows", "artifact"],
            "timeout_seconds": 45,
            "workspace_scope": ["workspace_1"],
            "disable_behavior": "finish_in_flight",
        }
    )


def test_remote_analysis_services_are_disabled_by_default() -> None:
    assert load_remote_analysis_services({}) == []
    config = build_egress_frontend_config(
        product_mode="business_insight",
        registry=RemoteAnalysisServiceRegistry(),
    )
    assert config["DATA_EGRESS_POLICY"] == "local_workspace_and_selected_model"
    assert config["REMOTE_ANALYSIS_SERVICES"] == []
    assert config["BIA_AZURE_WORKSPACE_BLOCKED"] is True
    assert config["BIA_ONLINE_CHARTIFACT_BLOCKED"] is True


def test_invalid_bia_remote_config_does_not_affect_data_formulator_mode() -> None:
    registry = configure_remote_analysis_registry(
        product_mode="data_formulator",
        environ={"BIA_REMOTE_ANALYSIS_SERVICES": "not-json"},
    )
    assert registry.list_enabled() == []


def test_admin_environment_is_validated_and_exposes_only_name_and_domain() -> None:
    raw = json.dumps(
        [
            {
                "service_id": "ragflow",
                "display_name": "Project knowledge",
                "endpoint": "https://rag.example.com/private/path",
                "enabled": True,
                "allowed_data_types": ["document_excerpt"],
                "workspace_scope": ["*"],
            }
        ]
    )
    services = load_remote_analysis_services(
        {"BIA_REMOTE_ANALYSIS_SERVICES": raw}
    )
    config = build_egress_frontend_config(
        product_mode="business_insight",
        registry=RemoteAnalysisServiceRegistry(services),
    )

    assert config["DATA_EGRESS_POLICY"] == "admin_enabled_remote_services"
    assert config["REMOTE_ANALYSIS_SERVICES"] == [
        {
            "service_id": "ragflow",
            "display_name": "Project knowledge",
            "domain": "rag.example.com",
        }
    ]
    assert "endpoint" not in config["REMOTE_ANALYSIS_SERVICES"][0]


@pytest.mark.parametrize(
    "override",
    [
        {"endpoint": "https://user:secret@example.com"},
        {"allowed_data_types": []},
        {"workspace_scope": []},
        {"timeout_seconds": 0},
    ],
)
def test_invalid_remote_service_configuration_is_rejected(override) -> None:
    value = {
        "service_id": "tsfl",
        "display_name": "Forecast service",
        "endpoint": "https://forecast.example.com",
        "enabled": True,
        "allowed_data_types": ["time_series_rows"],
        "workspace_scope": ["workspace_1"],
    }
    value.update(override)
    with pytest.raises(ValueError):
        RemoteAnalysisService.from_mapping(value)


def test_policy_requires_enabled_service_workspace_and_data_type() -> None:
    policy = DataEgressPolicy(RemoteAnalysisServiceRegistry([service()]))

    authorized = policy.authorize(
        service_id="tsfl",
        workspace_id="workspace_1",
        data_type="time_series_rows",
    )
    assert authorized.target_domain == "forecast.example.com"

    with pytest.raises(DataEgressDenied, match="workspace_not_allowed"):
        policy.authorize(
            service_id="tsfl",
            workspace_id="workspace_2",
            data_type="time_series_rows",
        )
    with pytest.raises(DataEgressDenied, match="data_type_not_allowed"):
        policy.authorize(
            service_id="tsfl",
            workspace_id="workspace_1",
            data_type="table_rows",
        )


def test_admin_disable_immediately_rejects_new_authorizations() -> None:
    registry = RemoteAnalysisServiceRegistry([service()])
    policy = DataEgressPolicy(registry)
    registry.set_enabled("tsfl", False)

    with pytest.raises(DataEgressDenied, match="service_disabled"):
        policy.authorize(
            service_id="tsfl",
            workspace_id="workspace_1",
            data_type="time_series_rows",
        )


def test_audit_result_rejects_free_form_error_text() -> None:
    configured = service()
    with pytest.raises(ValueError, match="safe result code"):
        DataEgressPolicy.record_result(
            service=configured,
            workspace_id="workspace_1",
            data_type="artifact",
            result="failed: raw customer row was invalid",
        )


def test_litellm_telemetry_is_global_and_bia_callbacks_are_cleared() -> None:
    fake_litellm = SimpleNamespace(
        telemetry=True,
        callbacks=["external"],
        success_callback=["success"],
        failure_callback=["failure"],
        input_callback=["input"],
        service_callback=["service"],
        _async_success_callback=["async-success"],
        _async_failure_callback=["async-failure"],
        _async_input_callback=["async-input"],
        audit_log_callbacks=["audit"],
        callback_settings={"otel": True},
    )

    configure_litellm_egress(
        product_mode="business_insight",
        litellm_module=fake_litellm,
    )

    assert fake_litellm.telemetry is False
    assert fake_litellm.callback_settings == {}
    for field in (
        "callbacks",
        "success_callback",
        "failure_callback",
        "input_callback",
        "service_callback",
        "_async_success_callback",
        "_async_failure_callback",
        "_async_input_callback",
        "audit_log_callbacks",
    ):
        assert getattr(fake_litellm, field) == []


def test_data_formulator_mode_only_disables_litellm_telemetry() -> None:
    fake_litellm = SimpleNamespace(telemetry=True, callbacks=["existing"])
    configure_litellm_egress(
        product_mode="data_formulator",
        litellm_module=fake_litellm,
    )
    assert fake_litellm.telemetry is False
    assert fake_litellm.callbacks == ["existing"]


def test_business_insight_rejects_azure_workspace_but_not_azure_sources() -> None:
    with pytest.raises(RuntimeError, match="forbids Azure Blob"):
        enforce_bia_workspace_policy(
            product_mode="business_insight",
            workspace_backend="azure_blob",
        )

    enforce_bia_workspace_policy(
        product_mode="business_insight",
        workspace_backend="local",
    )
    enforce_bia_workspace_policy(
        product_mode="data_formulator",
        workspace_backend="azure_blob",
    )


def test_app_config_exposes_read_only_bia_egress_state() -> None:
    from data_formulator.app import app

    original = app.config["CLI_ARGS"].copy()
    try:
        app.config["CLI_ARGS"]["product_mode"] = "business_insight"
        app.config["CLI_ARGS"]["workspace_backend"] = "local"
        response = app.test_client().get("/api/app-config")
        assert response.status_code == 200
        config = response.get_json()["data"]
        assert config["DATA_EGRESS_POLICY"] == "local_workspace_and_selected_model"
        assert config["LITELLM_TELEMETRY_DISABLED"] is True
        assert config["BIA_AZURE_WORKSPACE_BLOCKED"] is True
        assert config["BIA_ONLINE_CHARTIFACT_BLOCKED"] is True
        assert config["REMOTE_ANALYSIS_SERVICES"] == []
    finally:
        app.config["CLI_ARGS"] = original


def test_app_startup_safety_rejects_bia_azure_workspace() -> None:
    from data_formulator.app import _safety_checks, app

    original = app.config["CLI_ARGS"].copy()
    try:
        app.config["CLI_ARGS"].update(
            {
                "product_mode": "business_insight",
                "workspace_backend": "azure_blob",
                "sandbox": "docker",
            }
        )
        with pytest.raises(RuntimeError, match="forbids Azure Blob"):
            _safety_checks()
    finally:
        app.config["CLI_ARGS"] = original
