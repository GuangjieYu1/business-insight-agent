from __future__ import annotations

from unittest.mock import patch

import pytest

from data_formulator.errors import AppError
from data_formulator.insight.deepseek_user_models import (
    build_bia_user_deepseek_frontend_config,
    validate_bia_user_model_config,
)


pytestmark = [pytest.mark.backend, pytest.mark.security]


VALID_ENV = {
    "BIA_USER_DEEPSEEK_KEYS_ENABLED": "true",
    "BIA_USER_DEEPSEEK_API_BASE": "https://api.deepseek.com/v1",
    "BIA_USER_DEEPSEEK_MODELS": "deepseek-v4-flash,deepseek-v4-pro",
    "DF_ALLOWED_API_BASES": "https://api.deepseek.com/v1",
}


def _valid_model(**overrides: object) -> dict[str, object]:
    model: dict[str, object] = {
        "id": "deepseek-user",
        "endpoint": "openai",
        "model": "deepseek-v4-flash",
        "api_key": "sk-user",
        "api_base": "https://api.deepseek.com/v1",
        "api_version": "",
    }
    model.update(overrides)
    return model


def test_frontend_config_is_disabled_outside_business_insight() -> None:
    with patch.dict("os.environ", VALID_ENV, clear=False):
        config = build_bia_user_deepseek_frontend_config(product_mode="data_formulator")

    assert config == {
        "BIA_USER_DEEPSEEK_KEYS_ENABLED": False,
        "BIA_USER_DEEPSEEK_API_BASE": "https://api.deepseek.com/v1",
        "BIA_USER_DEEPSEEK_MODELS": ["deepseek-v4-flash", "deepseek-v4-pro"],
    }


def test_valid_business_insight_deepseek_model_is_normalized() -> None:
    model = _valid_model(api_base="https://api.deepseek.com/v1/")
    with patch.dict("os.environ", VALID_ENV, clear=False):
        validate_bia_user_model_config(model, product_mode="business_insight")

    assert model["endpoint"] == "openai"
    assert model["model"] == "deepseek-v4-flash"
    assert model["api_key"] == "sk-user"
    assert model["api_base"] == "https://api.deepseek.com/v1"
    assert model["api_version"] == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"endpoint": "azure"},
        {"model": "gpt-5.4"},
        {"api_base": "https://evil.example.com/v1"},
        {"api_version": "2024-02-15"},
        {"api_key": ""},
    ],
)
def test_invalid_business_insight_user_models_are_rejected(overrides: dict[str, object]) -> None:
    with patch.dict("os.environ", VALID_ENV, clear=False):
        with pytest.raises(AppError):
            validate_bia_user_model_config(
                _valid_model(**overrides),
                product_mode="business_insight",
            )


def test_business_insight_rejects_user_models_when_deepseek_mode_disabled() -> None:
    with patch.dict("os.environ", {"BIA_USER_DEEPSEEK_KEYS_ENABLED": "false"}, clear=False):
        with pytest.raises(AppError, match="Custom models are disabled"):
            validate_bia_user_model_config(
                _valid_model(),
                product_mode="business_insight",
            )


def test_get_client_enforces_bia_deepseek_policy(monkeypatch) -> None:
    from data_formulator.app import app
    from data_formulator.routes import agents

    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, endpoint, model, api_key=None, api_base=None, api_version=None):
            captured.update(
                {
                    "endpoint": endpoint,
                    "model": model,
                    "api_key": api_key,
                    "api_base": api_base,
                    "api_version": api_version,
                }
            )

    monkeypatch.setattr(agents, "Client", FakeClient)
    original = app.config["CLI_ARGS"].copy()
    try:
        app.config["CLI_ARGS"]["product_mode"] = "business_insight"
        with patch.dict("os.environ", VALID_ENV, clear=False), app.app_context():
            agents.get_client(_valid_model())
    finally:
        app.config["CLI_ARGS"] = original

    assert captured == {
        "endpoint": "openai",
        "model": "deepseek-v4-flash",
        "api_key": "sk-user",
        "api_base": "https://api.deepseek.com/v1",
        "api_version": None,
    }


def test_app_config_exposes_bia_deepseek_user_key_mode() -> None:
    from data_formulator.app import app

    original = app.config["CLI_ARGS"].copy()
    try:
        app.config["CLI_ARGS"]["product_mode"] = "business_insight"
        with patch.dict("os.environ", VALID_ENV, clear=False):
            response = app.test_client().get("/api/app-config")
        assert response.status_code == 200
        data = response.get_json()["data"]
    finally:
        app.config["CLI_ARGS"] = original

    assert data["BIA_USER_DEEPSEEK_KEYS_ENABLED"] is True
    assert data["BIA_USER_DEEPSEEK_API_BASE"] == "https://api.deepseek.com/v1"
    assert data["BIA_USER_DEEPSEEK_MODELS"] == ["deepseek-v4-flash", "deepseek-v4-pro"]

def test_litellm_runtime_proxy_dependency_is_packaged() -> None:
    """LiteLLM imports proxy helpers during completion calls in current releases."""
    import fastapi  # noqa: F401
    import orjson  # noqa: F401
    import litellm.responses.mcp.chat_completions_handler  # noqa: F401
