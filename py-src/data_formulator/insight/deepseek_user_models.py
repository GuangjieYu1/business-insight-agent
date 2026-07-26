# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Business Insight controlled DeepSeek user-key model policy."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass

from data_formulator.errors import AppError, ErrorCode
from data_formulator.product import ProductMode


ENV_ENABLED = "BIA_USER_DEEPSEEK_KEYS_ENABLED"
ENV_API_BASE = "BIA_USER_DEEPSEEK_API_BASE"
ENV_MODELS = "BIA_USER_DEEPSEEK_MODELS"

DEFAULT_DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")


@dataclass(frozen=True)
class BiaUserDeepSeekConfig:
    enabled: bool
    api_base: str
    models: tuple[str, ...]


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_api_base(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def _parse_models(value: str | None) -> tuple[str, ...]:
    parsed = tuple(item.strip() for item in (value or "").split(",") if item.strip())
    return parsed or DEFAULT_DEEPSEEK_MODELS


def get_bia_user_deepseek_config(
    *,
    product_mode: str | None,
    environ: Mapping[str, str] | None = None,
) -> BiaUserDeepSeekConfig:
    env = environ or os.environ
    is_bia = product_mode == ProductMode.BUSINESS_INSIGHT.value
    return BiaUserDeepSeekConfig(
        enabled=is_bia and _is_truthy(env.get(ENV_ENABLED)),
        api_base=_normalize_api_base(env.get(ENV_API_BASE) or DEFAULT_DEEPSEEK_API_BASE),
        models=_parse_models(env.get(ENV_MODELS)),
    )


def build_bia_user_deepseek_frontend_config(*, product_mode: str) -> dict:
    config = get_bia_user_deepseek_config(product_mode=product_mode)
    return {
        "BIA_USER_DEEPSEEK_KEYS_ENABLED": config.enabled,
        "BIA_USER_DEEPSEEK_API_BASE": config.api_base,
        "BIA_USER_DEEPSEEK_MODELS": list(config.models),
    }


def validate_bia_user_model_config(
    model_config: MutableMapping[str, object],
    *,
    product_mode: str | None,
) -> None:
    """Validate and normalise a user-supplied model in Business Insight mode."""

    if product_mode != ProductMode.BUSINESS_INSIGHT.value or model_config.get("is_global"):
        return

    config = get_bia_user_deepseek_config(product_mode=product_mode)
    if not config.enabled:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Custom models are disabled for Business Insight.",
        )

    endpoint = str(model_config.get("endpoint") or "").strip()
    model = str(model_config.get("model") or "").strip()
    api_key = str(model_config.get("api_key") or "").strip()
    api_base = _normalize_api_base(str(model_config.get("api_base") or ""))
    api_version = str(model_config.get("api_version") or "").strip()

    if endpoint != "openai":
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Business Insight only allows the DeepSeek OpenAI-compatible endpoint.",
        )
    if model not in config.models:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "The selected model is not allowed for Business Insight.",
        )
    if api_base != config.api_base:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "The DeepSeek API base is managed by the server and cannot be changed.",
        )
    if api_version:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "API version is not configurable for the Business Insight DeepSeek endpoint.",
        )
    if not api_key:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "A DeepSeek API key is required.",
        )

    model_config["endpoint"] = endpoint
    model_config["model"] = model
    model_config["api_key"] = api_key
    model_config["api_base"] = config.api_base
    model_config["api_version"] = ""
