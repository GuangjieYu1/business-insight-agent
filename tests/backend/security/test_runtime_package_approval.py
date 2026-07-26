from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data_formulator.sandbox.local_sandbox import LocalSandbox
from data_formulator.sandbox.runtime_packages import (
    _APPROVALS,
    classify_sandbox_violation,
    consume_runtime_package_approval,
    create_runtime_package_approval,
    detect_missing_runtime_packages,
    normalize_package_name,
)


def test_detects_multiple_missing_imports_as_one_request(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))

    def fake_find_spec(name):
        if name in {"xgboost", "shap"}:
            return None
        return object()

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)

    missing = detect_missing_runtime_packages("import xgboost\nimport shap\nimport pandas as pd")

    assert [item.import_name for item in missing] == ["shap", "xgboost"]
    assert [item.package_name for item in missing] == ["shap", "xgboost"]


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/pkg.whl",
        "git+https://example.com/repo",
        "xgboost --extra-index-url evil",
        "../xgboost",
        "",
    ],
)
def test_rejects_non_pypi_package_names(raw):
    with pytest.raises(ValueError):
        normalize_package_name(raw)


def test_runtime_approval_is_bound_to_user_workspace_and_single_use(tmp_path):
    approval = create_runtime_package_approval(
        identity_id="user-a",
        workspace_id="workspace-a",
        packages=["xgboost"],
        import_names=["xgboost"],
        trajectory=[{"role": "user", "content": "safe"}],
        completed_step_count=2,
    )

    with pytest.raises(ValueError):
        consume_runtime_package_approval(
            identity_id="user-b",
            workspace_id="workspace-a",
            approval_id=approval.id,
            decision="approve",
        )

    consumed = consume_runtime_package_approval(
        identity_id="user-a",
        workspace_id="workspace-a",
        approval_id=approval.id,
        decision="reject",
    )
    assert consumed.status == "rejected"
    assert consumed.completed_step_count == 2

    with pytest.raises(ValueError):
        consume_runtime_package_approval(
            identity_id="user-a",
            workspace_id="workspace-a",
            approval_id=approval.id,
            decision="approve",
        )


def test_runtime_approval_expires(tmp_path):
    approval = create_runtime_package_approval(
        identity_id="user-a",
        workspace_id="workspace-a",
        packages=["shap"],
        import_names=["shap"],
        trajectory=[],
        completed_step_count=0,
    )
    _APPROVALS[approval.id].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    with pytest.raises(ValueError):
        consume_runtime_package_approval(
            identity_id="user-a",
            workspace_id="workspace-a",
            approval_id=approval.id,
            decision="approve",
        )


def test_local_sandbox_static_missing_import_pauses_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RUNTIME_PACKAGE_INSTALL", "true")
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))

    result = LocalSandbox._run_in_warm_subprocess(
        "import bia_missing_package_for_test\n_pack = {'stdout': ''}",
        {"_pack": None},
        str(tmp_path),
    )

    assert result["status"] == "approval_required"
    assert result["missing_imports"] == ["bia_missing_package_for_test"]


def test_local_sandbox_dynamic_missing_import_is_structured(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RUNTIME_PACKAGE_INSTALL", "true")
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))

    result = LocalSandbox._run_in_warm_subprocess(
        "__import__('bia_missing_dynamic_for_test')\n_pack = {'stdout': ''}",
        {"_pack": None},
        str(tmp_path),
    )

    assert result["status"] == "error"
    assert result["missing_imports"] == ["bia_missing_dynamic_for_test"]


def test_non_package_sandbox_violations_are_not_approvable():
    violation = classify_sandbox_violation("Error: OSError - network access forbidden in sandbox")

    assert violation == {
        "category": "network_access",
        "message": "Sandbox blocked network access. This cannot be approved from the analysis UI.",
    }

