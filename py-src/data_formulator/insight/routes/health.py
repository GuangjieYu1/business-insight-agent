"""Minimal Business Insight readiness endpoint."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from flask import Blueprint, current_app

from data_formulator.error_handler import json_ok
from data_formulator.product import get_product_brand_config

insight_health_bp = Blueprint("insight_health", __name__, url_prefix="/api/insight")


def _package_version() -> str:
    try:
        return version("data_formulator")
    except PackageNotFoundError:
        return "development"


@insight_health_bp.route("/health", methods=["GET"])
def health():
    args = current_app.config.get("CLI_ARGS", {})
    brand = get_product_brand_config(mode_value=args.get("product_mode"))
    return json_ok(
        {
            "service": "business-insight",
            "status": "ready",
            "productMode": brand.mode.value,
            "brandName": brand.name,
            "domainSchemaVersion": "1.0",
            "dataFormulatorVersion": _package_version(),
            "workspaceBackend": args.get("workspace_backend", "local"),
        }
    )
