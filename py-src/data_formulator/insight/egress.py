# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Fail-closed data-egress controls for Business Insight mode."""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, replace
from typing import Any, Mapping
from urllib.parse import urlparse

from data_formulator.product import ProductMode


logger = logging.getLogger(__name__)

REMOTE_SERVICE_ENV = "BIA_REMOTE_ANALYSIS_SERVICES"
ALLOWED_DATA_TYPES = frozenset(
    {
        "aggregated_metrics",
        "artifact",
        "document_excerpt",
        "profile_summary",
        "table_rows",
        "table_schema",
        "time_series_rows",
    }
)
_SERVICE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_LITELLM_CALLBACK_FIELDS = (
    "callbacks",
    "success_callback",
    "failure_callback",
    "input_callback",
    "service_callback",
    "_async_success_callback",
    "_async_failure_callback",
    "_async_input_callback",
    "audit_log_callbacks",
)
_AUDIT_RESULTS = frozenset(
    {
        "authorized",
        "cancelled",
        "completed",
        "data_type_not_allowed",
        "failed",
        "service_disabled",
        "service_not_registered",
        "timeout",
        "workspace_not_allowed",
    }
)


class DataEgressDenied(PermissionError):
    """Raised before business data can be sent to an unapproved receiver."""


@dataclass(frozen=True, slots=True)
class RemoteAnalysisService:
    service_id: str
    display_name: str
    endpoint: str
    target_domain: str
    enabled: bool
    allowed_data_types: frozenset[str]
    timeout_seconds: float
    workspace_scope: frozenset[str]
    disable_behavior: str = "finish_in_flight"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteAnalysisService":
        service_id = str(value.get("service_id", "")).strip().lower()
        if not _SERVICE_ID_PATTERN.fullmatch(service_id):
            raise ValueError("Remote service_id must match ^[a-z][a-z0-9_-]{1,63}$")

        display_name = str(value.get("display_name", "")).strip()
        if not display_name:
            raise ValueError(f"Remote service '{service_id}' requires display_name")

        endpoint = str(value.get("endpoint", "")).strip()
        parsed = urlparse(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                f"Remote service '{service_id}' endpoint must be an HTTP(S) URL "
                "without embedded credentials"
            )

        allowed_data_types = frozenset(
            str(item).strip() for item in value.get("allowed_data_types", [])
        )
        unknown_types = allowed_data_types - ALLOWED_DATA_TYPES
        if not allowed_data_types or unknown_types:
            raise ValueError(
                f"Remote service '{service_id}' has invalid allowed_data_types: "
                f"{sorted(unknown_types) if unknown_types else 'empty'}"
            )

        workspace_scope = frozenset(
            str(item).strip() for item in value.get("workspace_scope", [])
        )
        if not workspace_scope:
            raise ValueError(f"Remote service '{service_id}' requires workspace_scope")

        timeout_seconds = float(value.get("timeout_seconds", 30))
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError(
                f"Remote service '{service_id}' timeout_seconds must be in (0, 300]"
            )

        disable_behavior = str(
            value.get("disable_behavior", "finish_in_flight")
        ).strip()
        if disable_behavior not in {"finish_in_flight", "cancel_in_flight"}:
            raise ValueError(
                f"Remote service '{service_id}' has invalid disable_behavior"
            )

        return cls(
            service_id=service_id,
            display_name=display_name,
            endpoint=endpoint,
            target_domain=parsed.hostname.lower(),
            enabled=value.get("enabled") is True,
            allowed_data_types=allowed_data_types,
            timeout_seconds=timeout_seconds,
            workspace_scope=workspace_scope,
            disable_behavior=disable_behavior,
        )

    def as_frontend_recipient(self) -> dict[str, str]:
        return {
            "service_id": self.service_id,
            "display_name": self.display_name,
            "domain": self.target_domain,
        }


class RemoteAnalysisServiceRegistry:
    """Server-owned registry. No browser API is allowed to mutate it."""

    def __init__(self, services: list[RemoteAnalysisService] | None = None):
        self._lock = threading.RLock()
        self._services = {
            service.service_id: service for service in (services or [])
        }

    def list_enabled(self) -> list[RemoteAnalysisService]:
        with self._lock:
            return sorted(
                (service for service in self._services.values() if service.enabled),
                key=lambda service: service.service_id,
            )

    def get(self, service_id: str) -> RemoteAnalysisService | None:
        with self._lock:
            return self._services.get(service_id)

    def set_enabled(self, service_id: str, enabled: bool) -> None:
        """Apply an administrator-side toggle to all subsequent authorizations."""
        with self._lock:
            service = self._services.get(service_id)
            if service is None:
                raise KeyError(service_id)
            self._services[service_id] = replace(service, enabled=enabled)


class DataEgressPolicy:
    """Authorize remote Adapter calls without accepting or logging payloads."""

    def __init__(self, registry: RemoteAnalysisServiceRegistry):
        self._registry = registry

    def authorize(
        self,
        *,
        service_id: str,
        workspace_id: str,
        data_type: str,
    ) -> RemoteAnalysisService:
        service = self._registry.get(service_id)
        reason: str | None = None
        if service is None:
            reason = "service_not_registered"
        elif not service.enabled:
            reason = "service_disabled"
        elif data_type not in service.allowed_data_types:
            reason = "data_type_not_allowed"
        elif (
            "*" not in service.workspace_scope
            and workspace_id not in service.workspace_scope
        ):
            reason = "workspace_not_allowed"

        if reason is not None:
            self._audit(
                service_id=service_id,
                domain=service.target_domain if service else "",
                workspace_id=workspace_id,
                data_type=data_type,
                result=reason,
            )
            raise DataEgressDenied(
                f"Remote analysis service '{service_id}' denied: {reason}"
            )

        self._audit(
            service_id=service.service_id,
            domain=service.target_domain,
            workspace_id=workspace_id,
            data_type=data_type,
            result="authorized",
        )
        return service

    @staticmethod
    def record_result(
        *,
        service: RemoteAnalysisService,
        workspace_id: str,
        data_type: str,
        result: str,
    ) -> None:
        if result not in _AUDIT_RESULTS:
            raise ValueError("Remote analysis audit result must use a safe result code")
        DataEgressPolicy._audit(
            service_id=service.service_id,
            domain=service.target_domain,
            workspace_id=workspace_id,
            data_type=data_type,
            result=result,
        )

    @staticmethod
    def _audit(
        *,
        service_id: str,
        domain: str,
        workspace_id: str,
        data_type: str,
        result: str,
    ) -> None:
        logger.info(
            "remote_analysis %s",
            json.dumps(
                {
                    "service_id": service_id,
                    "domain": domain,
                    "workspace_id": workspace_id,
                    "data_type": data_type,
                    "result": result,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
        )


def load_remote_analysis_services(
    environ: Mapping[str, str] | None = None,
) -> list[RemoteAnalysisService]:
    import os

    env = environ if environ is not None else os.environ
    raw = env.get(REMOTE_SERVICE_ENV, "").strip()
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{REMOTE_SERVICE_ENV} must be valid JSON") from exc
    if not isinstance(values, list):
        raise ValueError(f"{REMOTE_SERVICE_ENV} must contain a JSON array")

    services = [RemoteAnalysisService.from_mapping(value) for value in values]
    service_ids = [service.service_id for service in services]
    if len(service_ids) != len(set(service_ids)):
        raise ValueError(f"{REMOTE_SERVICE_ENV} contains duplicate service_id values")
    return services


def build_remote_analysis_registry(
    environ: Mapping[str, str] | None = None,
) -> RemoteAnalysisServiceRegistry:
    return RemoteAnalysisServiceRegistry(load_remote_analysis_services(environ))


_remote_service_registry = RemoteAnalysisServiceRegistry()


def configure_remote_analysis_registry(
    *,
    product_mode: str,
    environ: Mapping[str, str] | None = None,
) -> RemoteAnalysisServiceRegistry:
    """Load BIA-only administrator configuration without affecting DF mode."""
    global _remote_service_registry
    if product_mode == ProductMode.BUSINESS_INSIGHT.value:
        _remote_service_registry = build_remote_analysis_registry(environ)
    else:
        _remote_service_registry = RemoteAnalysisServiceRegistry()
    return _remote_service_registry


def get_remote_analysis_registry() -> RemoteAnalysisServiceRegistry:
    return _remote_service_registry


def get_data_egress_policy() -> DataEgressPolicy:
    return DataEgressPolicy(_remote_service_registry)


def configure_litellm_egress(
    *,
    product_mode: str,
    litellm_module: Any | None = None,
) -> None:
    """Disable LiteLLM telemetry globally and callbacks in BIA mode."""
    if product_mode != ProductMode.BUSINESS_INSIGHT.value:
        return

    if litellm_module is None:
        import litellm as litellm_module

    litellm_module.telemetry = False
    for field in _LITELLM_CALLBACK_FIELDS:
        if hasattr(litellm_module, field):
            setattr(litellm_module, field, [])
    if hasattr(litellm_module, "callback_settings"):
        litellm_module.callback_settings = {}


def enforce_bia_workspace_policy(*, product_mode: str, workspace_backend: str) -> None:
    if (
        product_mode == ProductMode.BUSINESS_INSIGHT.value
        and workspace_backend == "azure_blob"
    ):
        raise RuntimeError(
            "Business Insight mode forbids Azure Blob as the Workspace backend. "
            "Use local or ephemeral Workspace storage instead."
        )


def build_egress_frontend_config(
    *,
    product_mode: str,
    registry: RemoteAnalysisServiceRegistry | None = None,
) -> dict[str, Any]:
    is_bia = product_mode == ProductMode.BUSINESS_INSIGHT.value
    enabled = (registry or _remote_service_registry).list_enabled() if is_bia else []
    return {
        "DATA_EGRESS_POLICY": (
            "admin_enabled_remote_services"
            if enabled
            else (
                "local_workspace_and_selected_model"
                if is_bia
                else "standard_data_formulator"
            )
        ),
        "LITELLM_TELEMETRY_DISABLED": True,
        "BIA_AZURE_WORKSPACE_BLOCKED": is_bia,
        "BIA_ONLINE_CHARTIFACT_BLOCKED": is_bia,
        "REMOTE_ANALYSIS_SERVICES": [
            service.as_frontend_recipient() for service in enabled
        ],
    }
