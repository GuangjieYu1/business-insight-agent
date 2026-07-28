# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Runtime package approval and installation helpers for the local sandbox."""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from data_formulator.datalake.workspace import get_data_formulator_home

logger = logging.getLogger(__name__)

try:  # pragma: no cover - platform dependent
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # pragma: no cover - platform dependent
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MISSING_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")
_EXPLICIT_INSTALL_RE = re.compile(r"(?:\u4e0b\u8f7d|\u5b89\u88c5|download|install|pip\s+install)", re.IGNORECASE)
_PACKAGE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,127}")
_APPROVAL_TTL = timedelta(minutes=10)
_APPROVALS: dict[str, "RuntimePackageApproval"] = {}
_APPROVAL_LOCK = threading.Lock()

_IMPORT_PACKAGE_ALIASES = {"cv2": "opencv-python", "PIL": "Pillow", "sklearn": "scikit-learn"}
_FORBIDDEN_APPROVAL_IMPORTS = frozenset({
    "ctypes", "http", "multiprocessing", "requests", "resource", "shutil",
    "signal", "socket", "subprocess", "urllib",
})
_INSTALL_COMMAND_WORDS = {
    "download", "install", "pip", "package", "packages", "python",
    "analyze", "analysis", "use", "with", "and", "to", "for", "from",
}
_SOURCE_ERROR_PATTERNS = (
    "connection timed out", "connect timeout", "connection refused",
    "failed to establish a new connection", "temporary failure in name resolution",
    "name or service not known", "newconnectionerror", "read timed out",
    "too many 5xx", "proxyerror", "ssl", "tls", "network is unreachable",
)
_NO_WHEEL_PATTERNS = (
    "no matching distribution found", "could not find a version that satisfies",
    "is not a supported wheel on this platform", "requires-python",
)
_VERIFY_IMPORT_SCRIPT = """\
import importlib
import json
import sys
from importlib import metadata

paths = json.loads(sys.argv[1])
imports = json.loads(sys.argv[2])
packages = json.loads(sys.argv[3])
for path in reversed(paths):
    if path not in sys.path:
        sys.path.insert(0, path)
versions = {}
for import_name in imports:
    importlib.import_module(import_name)
for package_name in packages:
    try:
        versions[package_name] = metadata.version(package_name)
    except metadata.PackageNotFoundError:
        versions[package_name] = "unknown"
print(json.dumps({"versions": versions}, ensure_ascii=False))
"""


@dataclass(frozen=True)
class MissingRuntimePackage:
    import_name: str
    package_name: str


@dataclass
class RuntimePackageApproval:
    id: str
    identity_id: str
    workspace_id: str
    packages: list[str]
    import_names: list[str]
    trajectory: list[dict[str, Any]]
    completed_step_count: int
    created_at: datetime
    expires_at: datetime
    kind: str = "python_package_install"
    status: str = "pending"
    consumed_at: datetime | None = None
    preceding_error: str | None = None

    def public_payload(self) -> dict[str, Any]:
        sources = runtime_approval_sources(self.kind)
        source_label = ", ".join(source["label"] for source in sources) or "PyPI binary wheels"
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "packages": list(self.packages),
            "importNames": list(self.import_names),
            "expiresAt": self.expires_at.isoformat(),
            "source": source_label,
            "sources": sources,
            "installTarget": "DATA_FORMULATOR_HOME/runtime-python",
            "risk": (
                "Approved libraries run inside the server sandbox process. "
                "Network, file write, subprocess, and other sandbox limits remain active."
            ),
        }
        if self.preceding_error:
            payload["precedingError"] = sanitize_install_error(self.preceding_error)
        return payload


@dataclass(frozen=True)
class RuntimePackageInstallResult:
    ok: bool
    status: str
    packages: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    error_code: str | None = None
    source: dict[str, str] | None = None
    versions: dict[str, str] = field(default_factory=dict)
    progress_events: list[dict[str, Any]] = field(default_factory=list)

    def public_payload(self, approval_id: str) -> dict[str, Any]:
        return approval_status_event(
            approval_id,
            self.status,
            packages=self.packages,
            error=self.error_message,
            error_code=self.error_code,
            source=self.source,
            versions=self.versions,
        )


@dataclass(frozen=True)
class _InstallerCommand:
    kind: str
    prefix: list[str]


@dataclass(frozen=True)
class _AttemptResult:
    ok: bool
    source_failure: bool = False
    error_message: str | None = None
    error_code: str | None = None
    source: dict[str, str] | None = None
    versions: dict[str, str] = field(default_factory=dict)
    bundle: str | None = None


def runtime_install_enabled() -> bool:
    return os.environ.get("ENABLE_RUNTIME_PACKAGE_INSTALL", "").strip().lower() in {"1", "true", "yes", "on"}


def _primary_index_url() -> str:
    return os.environ.get("DF_PIP_PRIMARY_INDEX_URL", "https://mirrors.aliyun.com/pypi/simple/")


def _secondary_index_url() -> str:
    return os.environ.get("DF_PIP_SECONDARY_INDEX_URL", "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple")


def _official_index_url() -> str:
    return os.environ.get("DF_PIP_OFFICIAL_INDEX_URL", "https://pypi.org/simple")


def _source_url(source_id: str) -> str:
    if source_id == "primary":
        return _primary_index_url()
    if source_id == "secondary":
        return _secondary_index_url()
    return _official_index_url()


def _safe_domain(url: str) -> str:
    try:
        return urlsplit(url).hostname or "unknown"
    except Exception:
        return "unknown"


def _source_info(source_id: str) -> dict[str, str]:
    labels = {
        "primary": "Aliyun PyPI mirror",
        "secondary": "Tsinghua PyPI mirror",
        "official": "Official PyPI",
        "existing": "Existing runtime bundle",
    }
    url = _source_url(source_id) if source_id != "existing" else ""
    return {"id": source_id, "label": labels.get(source_id, source_id), "domain": _safe_domain(url)}


def runtime_approval_sources(kind: str = "python_package_install") -> list[dict[str, str]]:
    if kind == "official_pypi_fallback":
        return [_source_info("official")]
    return [_source_info("primary"), _source_info("secondary")]


def get_runtime_package_base_dir() -> Path:
    return get_data_formulator_home() / "runtime-python"


def get_runtime_package_dir() -> Path:
    cache_tag = sys.implementation.cache_tag or f"python-{sys.version_info.major}{sys.version_info.minor}"
    machine = (platform.machine() or "unknown").lower() or "unknown"
    machine = re.sub(r"[^a-z0-9._-]+", "-", machine)
    return get_runtime_package_base_dir() / f"{cache_tag}-{machine}"


def _manifest_path() -> Path:
    return get_runtime_package_dir() / "manifest.json"


def _legacy_manifest_path() -> Path:
    return get_runtime_package_base_dir() / "_manifest.json"


def _bundle_dir() -> Path:
    return get_runtime_package_dir() / "bundles"


def _staging_dir() -> Path:
    return get_runtime_package_dir() / ".staging"


def runtime_bundle_paths() -> list[str]:
    manifest = _load_manifest()
    paths: list[str] = []
    seen: set[str] = set()
    for entry in reversed(manifest.get("entries", [])):
        bundle = str(entry.get("bundle") or "").strip()
        if not bundle:
            continue
        path = (_bundle_dir() / bundle).resolve()
        if path.exists():
            resolved = str(path)
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def ensure_runtime_package_path() -> Path:
    runtime_dir = get_runtime_package_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for path in reversed(runtime_bundle_paths()):
        if path not in sys.path:
            sys.path.insert(0, path)
    legacy_dir = get_runtime_package_base_dir()
    if _legacy_manifest_path().exists():
        legacy_str = str(legacy_dir)
        if legacy_str not in sys.path:
            sys.path.insert(0, legacy_str)
    return runtime_dir


def normalize_package_name(raw: str) -> str:
    cleaned = str(raw or "").strip()
    if not _PACKAGE_RE.fullmatch(cleaned):
        raise ValueError("Invalid PyPI package name")
    return re.sub(r"[-_.]+", "-", cleaned).lower()


def package_for_import(import_name: str) -> str:
    return normalize_package_name(_IMPORT_PACKAGE_ALIASES.get(import_name, import_name))


def _import_name_for_package(package_name: str) -> str:
    normalized = normalize_package_name(package_name)
    for import_name, aliased_package in _IMPORT_PACKAGE_ALIASES.items():
        if normalize_package_name(aliased_package) == normalized:
            return import_name
    return normalized.replace("-", "_")


def detect_explicit_runtime_package_requests(user_question: str) -> list[MissingRuntimePackage]:
    question = str(user_question or "")
    trigger = _EXPLICIT_INSTALL_RE.search(question)
    if not trigger:
        return []
    if re.search(r"(?:https?://|git\+|git@|--[A-Za-z])", question, re.IGNORECASE):
        return []

    requests: list[MissingRuntimePackage] = []
    seen: set[str] = set()
    for token in _PACKAGE_TOKEN_RE.findall(question[trigger.end():]):
        lowered = token.lower()
        if lowered in {"for", "to", "from", "on", "during"}:
            break
        if lowered in _INSTALL_COMMAND_WORDS or lowered == "and":
            continue
        try:
            package_name = normalize_package_name(token)
        except ValueError:
            continue
        if package_name in seen:
            continue
        seen.add(package_name)
        import_name = _import_name_for_package(package_name)
        if import_name in _FORBIDDEN_APPROVAL_IMPORTS:
            continue
        try:
            available = importlib.util.find_spec(import_name) is not None
        except (ImportError, AttributeError, ValueError):
            available = False
        if not available:
            requests.append(MissingRuntimePackage(import_name, package_name))
    return requests


def _normalize_import_root(raw: str) -> str:
    root = str(raw or "").split(".", 1)[0].strip()
    if not root or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", root):
        return ""
    return root


def _imports_from_code(code: str) -> list[str]:
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return []

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _normalize_import_root(alias.name)
                if root:
                    roots.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                root = _normalize_import_root(node.module)
                if root:
                    roots.add(root)
    return sorted(roots)


def detect_missing_runtime_packages(code: str) -> list[MissingRuntimePackage]:
    ensure_runtime_package_path()
    missing: list[MissingRuntimePackage] = []
    for import_name in _imports_from_code(code):
        if import_name in _FORBIDDEN_APPROVAL_IMPORTS:
            continue
        try:
            spec = importlib.util.find_spec(import_name)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is None:
            missing.append(MissingRuntimePackage(import_name, package_for_import(import_name)))
    return _dedupe_missing(missing)


def missing_runtime_packages_from_error(message: str) -> list[MissingRuntimePackage]:
    matches = _MISSING_RE.findall(str(message or ""))
    missing = []
    for match in matches:
        root = _normalize_import_root(match)
        if root and root not in _FORBIDDEN_APPROVAL_IMPORTS:
            missing.append(MissingRuntimePackage(root, package_for_import(root)))
    return _dedupe_missing(missing)


def _dedupe_missing(items: list[MissingRuntimePackage]) -> list[MissingRuntimePackage]:
    seen: set[tuple[str, str]] = set()
    deduped: list[MissingRuntimePackage] = []
    for item in items:
        key = (item.import_name, item.package_name)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def missing_payload(items: list[MissingRuntimePackage]) -> dict[str, Any]:
    return {
        "missing_imports": [item.import_name for item in items],
        "packages": [item.package_name for item in items],
    }


def create_runtime_package_approval(
    *,
    identity_id: str,
    workspace_id: str,
    packages: list[str],
    import_names: list[str],
    trajectory: list[dict[str, Any]],
    completed_step_count: int,
    kind: str = "python_package_install",
    preceding_error: str | None = None,
) -> RuntimePackageApproval:
    if kind not in {"python_package_install", "official_pypi_fallback"}:
        raise ValueError("Invalid runtime package approval kind")
    normalized_packages = [normalize_package_name(pkg) for pkg in packages]
    normalized_imports = [_normalize_import_root(name) for name in import_names]
    normalized_imports = [name for name in normalized_imports if name and name not in _FORBIDDEN_APPROVAL_IMPORTS]
    if not normalized_packages or not normalized_imports:
        raise ValueError("Runtime package approval requires at least one package")

    now = datetime.now(timezone.utc)
    approval = RuntimePackageApproval(
        id=f"approval_{secrets.token_urlsafe(18)}",
        identity_id=identity_id,
        workspace_id=workspace_id,
        packages=list(dict.fromkeys(normalized_packages)),
        import_names=list(dict.fromkeys(normalized_imports)),
        trajectory=list(trajectory or []),
        completed_step_count=max(0, int(completed_step_count or 0)),
        created_at=now,
        expires_at=now + _APPROVAL_TTL,
        kind=kind,
        preceding_error=sanitize_install_error(preceding_error) if preceding_error else None,
    )
    with _APPROVAL_LOCK:
        _APPROVALS[approval.id] = approval
        _prune_expired_locked(now)
    return approval


def create_followup_runtime_package_approval(
    approval: RuntimePackageApproval,
    *,
    kind: str,
    preceding_error: str | None = None,
) -> RuntimePackageApproval:
    return create_runtime_package_approval(
        identity_id=approval.identity_id,
        workspace_id=approval.workspace_id,
        packages=approval.packages,
        import_names=approval.import_names,
        trajectory=approval.trajectory,
        completed_step_count=approval.completed_step_count,
        kind=kind,
        preceding_error=preceding_error,
    )


def consume_runtime_package_approval(
    *,
    identity_id: str,
    workspace_id: str,
    approval_id: str,
    decision: str,
) -> RuntimePackageApproval:
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        raise ValueError("Invalid approval decision")

    now = datetime.now(timezone.utc)
    with _APPROVAL_LOCK:
        _prune_expired_locked(now)
        approval = _APPROVALS.get(str(approval_id or ""))
        if approval is None:
            raise ValueError("Approval request not found or expired")
        if approval.identity_id != identity_id or approval.workspace_id != workspace_id:
            raise ValueError("Approval request does not belong to this user or workspace")
        if approval.consumed_at is not None or approval.status != "pending":
            raise ValueError("Approval request has already been used")
        if approval.expires_at <= now:
            approval.status = "expired"
            raise ValueError("Approval request expired")
        approval.status = "approved" if normalized_decision == "approve" else "rejected"
        approval.consumed_at = now
        return approval


def _prune_expired_locked(now: datetime) -> None:
    expired = [
        approval_id
        for approval_id, approval in _APPROVALS.items()
        if approval.expires_at <= now and approval.consumed_at is None
    ]
    for approval_id in expired:
        _APPROVALS.pop(approval_id, None)


def approval_status_event(
    approval_id: str,
    status: str,
    *,
    packages: list[dict[str, Any]] | list[str] | None = None,
    error: str | None = None,
    error_code: str | None = None,
    source: dict[str, str] | None = None,
    versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "approval_status",
        "approvalId": approval_id,
        "status": status,
        "packages": packages or [],
    }
    if source:
        payload["source"] = source
    if versions:
        payload["versions"] = versions
    if error:
        payload["error"] = sanitize_install_error(error)
    if error_code:
        payload["errorCode"] = error_code
    return payload


def install_runtime_packages(
    *,
    packages: list[str],
    import_names: list[str],
    timeout_seconds: int | None = None,
    allow_official: bool = False,
) -> RuntimePackageInstallResult:
    if not runtime_install_enabled():
        return RuntimePackageInstallResult(
            ok=False,
            status="failed",
            error_message="Runtime package installation is disabled by the server.",
            error_code="installer_unavailable",
        )

    try:
        normalized_packages = list(dict.fromkeys(normalize_package_name(pkg) for pkg in packages))
    except ValueError as exc:
        return RuntimePackageInstallResult(ok=False, status="failed", error_message=str(exc), error_code="invalid_package")
    normalized_imports = [name for name in dict.fromkeys(_normalize_import_root(name) for name in import_names) if name]
    normalized_imports = [name for name in normalized_imports if name not in _FORBIDDEN_APPROVAL_IMPORTS]
    if not normalized_packages or not normalized_imports:
        return RuntimePackageInstallResult(
            ok=False,
            status="failed",
            error_message="Runtime package installation requires packages and import names.",
            error_code="invalid_package",
        )

    runtime_dir = ensure_runtime_package_path()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    timeout = timeout_seconds or int(os.environ.get("RUNTIME_PACKAGE_INSTALL_TIMEOUT", "300"))
    installer = _select_installer(timeout_seconds=min(10, timeout))
    if installer is None:
        return RuntimePackageInstallResult(
            ok=False,
            status="failed",
            error_message="No supported Python package installer is available for the current interpreter.",
            error_code="installer_unavailable",
        )

    progress_events: list[dict[str, Any]] = []
    source_ids = ["official"] if allow_official else ["primary", "secondary"]
    package_payload = [{"package": pkg} for pkg in normalized_packages]

    with _install_lock(runtime_dir):
        ensure_runtime_package_path()
        if all(_module_available(import_name) for import_name in normalized_imports):
            versions = _resolve_versions(normalized_packages)
            return RuntimePackageInstallResult(
                ok=True,
                status="installed",
                packages=[{"package": pkg, "version": versions.get(pkg)} for pkg in normalized_packages],
                source=_source_info("existing"),
                versions=versions,
                progress_events=progress_events,
            )

        for index, source_id in enumerate(source_ids):
            source = _source_info(source_id)
            progress_events.append({
                "status": "retrying_secondary" if source_id == "secondary" else "installing",
                "source": source,
                "packages": package_payload,
            })
            attempt = _install_from_source(
                installer=installer,
                packages=normalized_packages,
                import_names=normalized_imports,
                source_id=source_id,
                timeout_seconds=timeout,
            )
            if attempt.ok:
                ensure_runtime_package_path()
                versions = attempt.versions
                return RuntimePackageInstallResult(
                    ok=True,
                    status="installed",
                    packages=[{"package": pkg, "version": versions.get(pkg)} for pkg in normalized_packages],
                    source=attempt.source,
                    versions=versions,
                    progress_events=progress_events,
                )

            has_next_source = index + 1 < len(source_ids)
            if attempt.source_failure and has_next_source:
                continue
            if attempt.source_failure and not allow_official:
                return RuntimePackageInstallResult(
                    ok=False,
                    status="awaiting_official_approval",
                    packages=package_payload,
                    error_message=attempt.error_message,
                    error_code=attempt.error_code or "source_unreachable",
                    source=attempt.source,
                    progress_events=progress_events,
                )
            return RuntimePackageInstallResult(
                ok=False,
                status="failed",
                packages=package_payload,
                error_message=attempt.error_message,
                error_code=attempt.error_code or "unknown_install_error",
                source=attempt.source,
                progress_events=progress_events,
            )

    return RuntimePackageInstallResult(
        ok=False,
        status="failed",
        packages=package_payload,
        error_message="Runtime package installation ended unexpectedly.",
        error_code="unknown_install_error",
        progress_events=progress_events,
    )


def _select_installer(timeout_seconds: int = 10) -> _InstallerCommand | None:
    pip_check = [sys.executable, "-m", "pip", "--version"]
    try:
        completed = subprocess.run(pip_check, shell=False, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        if completed.returncode == 0:
            return _InstallerCommand("pip", [sys.executable, "-m", "pip", "install"])
    except Exception:
        pass

    uv_path = shutil.which("uv")
    if uv_path:
        return _InstallerCommand("uv", [uv_path, "pip", "install", "--python", sys.executable])
    return None


def _install_from_source(
    *,
    installer: _InstallerCommand,
    packages: list[str],
    import_names: list[str],
    source_id: str,
    timeout_seconds: int,
) -> _AttemptResult:
    source = _source_info(source_id)
    index_url = _source_url(source_id)
    staging_parent = _staging_dir()
    staging_parent.mkdir(parents=True, exist_ok=True)
    _bundle_dir().mkdir(parents=True, exist_ok=True)
    staging_dir = staging_parent / f"install-{secrets.token_hex(12)}"

    common_args = [
        "--only-binary=:all:",
        "--target", str(staging_dir),
        "--index-url", index_url,
        *packages,
    ]
    if installer.kind == "pip":
        command = [*installer.prefix, "--disable-pip-version-check", "--no-input", *common_args]
    else:
        command = [*installer.prefix, *common_args]

    env = dict(os.environ)
    env.update({"PIP_NO_INPUT": "1", "UV_NO_PROGRESS": "1"})
    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        _cleanup_path(staging_dir)
        return _AttemptResult(
            ok=False,
            source_failure=True,
            error_message=f"Installing packages timed out after {timeout_seconds}s from {source['label']}.",
            error_code="install_timeout",
            source=source,
        )
    except PermissionError as exc:
        _cleanup_path(staging_dir)
        return _AttemptResult(False, False, str(exc), "permission_denied", source)
    except OSError as exc:
        _cleanup_path(staging_dir)
        code = "disk_full" if "no space" in str(exc).lower() else "unknown_install_error"
        return _AttemptResult(False, False, _install_failure_summary(code, source), code, source)

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode != 0:
        _cleanup_path(staging_dir)
        error_code, source_failure = _classify_install_failure(output)
        if output:
            logger.warning(
                "Runtime package install failed source=%s error_code=%s detail=%s",
                source.get("id"),
                error_code,
                sanitize_install_error(output, limit=2000),
            )
        return _AttemptResult(False, source_failure, _install_failure_summary(error_code, source), error_code, source)

    verify = _verify_installed_bundle(staging_dir, import_names, packages)
    if not verify.ok:
        _cleanup_path(staging_dir)
        return _AttemptResult(False, False, verify.error_message, verify.error_code, source)

    bundle_name = f"bundle-{int(time.time())}-{secrets.token_hex(4)}"
    destination = _bundle_dir() / bundle_name
    try:
        staging_dir.replace(destination)
    except OSError:
        staging_dir.rename(destination)

    versions = verify.versions
    _append_manifest_entry({
        "bundle": bundle_name,
        "packages": packages,
        "import_names": import_names,
        "versions": versions,
        "source_id": source["id"],
        "source_label": source["label"],
        "source_domain": source["domain"],
        "python_abi": sys.implementation.cache_tag,
        "machine": platform.machine(),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    })
    return _AttemptResult(True, False, source=source, versions=versions, bundle=bundle_name)


def _classify_install_failure(output: str) -> tuple[str, bool]:
    lowered = (output or "").lower()
    if "permission denied" in lowered or "access is denied" in lowered:
        return "permission_denied", False
    if "no space left" in lowered or "disk full" in lowered:
        return "disk_full", False
    if any(pattern in lowered for pattern in _SOURCE_ERROR_PATTERNS):
        return "source_unreachable", True
    if any(pattern in lowered for pattern in _NO_WHEEL_PATTERNS):
        return "no_compatible_wheel", False
    return "unknown_install_error", False


def _install_failure_summary(error_code: str, source: dict[str, str] | None = None) -> str:
    source_label = (source or {}).get("label") or "the configured package source"
    messages = {
        "invalid_package": "The requested package name is not allowed.",
        "installer_unavailable": "No supported Python package installer is available on the server.",
        "source_unreachable": f"The package source {source_label} could not be reached.",
        "no_compatible_wheel": "No compatible binary wheel is available for the current Python and CPU platform.",
        "install_timeout": f"Installing from {source_label} timed out.",
        "permission_denied": "The server could not write to the runtime package directory.",
        "disk_full": "The server disk is full while installing runtime libraries.",
        "import_validation_failed": "The package installed, but import validation failed in a clean Python process.",
        "unknown_install_error": "Runtime package installation failed. Check the server log for details.",
    }
    return messages.get(error_code, messages["unknown_install_error"])


def _verify_installed_bundle(staging_dir: Path, import_names: list[str], packages: list[str]) -> _AttemptResult:
    paths = [str(staging_dir), *runtime_bundle_paths()]
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _VERIFY_IMPORT_SCRIPT,
                json.dumps(paths, ensure_ascii=False),
                json.dumps(import_names, ensure_ascii=False),
                json.dumps(packages, ensure_ascii=False),
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("RUNTIME_PACKAGE_IMPORT_VERIFY_TIMEOUT", "180")),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _AttemptResult(False, False, "Import validation timed out.", "import_validation_failed")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Import validation failed.").strip()
        return _AttemptResult(False, False, detail, "import_validation_failed")
    try:
        payload = json.loads(completed.stdout or "{}")
    except ValueError:
        payload = {}
    versions = payload.get("versions") if isinstance(payload, dict) else {}
    if not isinstance(versions, dict):
        versions = {}
    return _AttemptResult(True, False, versions={str(k): str(v) for k, v in versions.items()})


def _distribution_version(package: str) -> str | None:
    try:
        return importlib.metadata.distribution(package).version
    except importlib.metadata.PackageNotFoundError:
        return None


def _resolve_versions(packages: list[str]) -> dict[str, str]:
    ensure_runtime_package_path()
    versions: dict[str, str] = {}
    for package in packages:
        version = _distribution_version(package)
        versions[package] = version or "unknown"
    return versions


def _load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return {"schema_version": "2.0", "entries": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "2.0", "entries": []}
    if not isinstance(raw, dict):
        return {"schema_version": "2.0", "entries": []}
    entries = raw.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {"schema_version": str(raw.get("schema_version") or "2.0"), "entries": [entry for entry in entries if isinstance(entry, dict)]}


def _write_manifest(manifest: dict[str, Any]) -> None:
    runtime_dir = get_runtime_package_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=str(runtime_dir))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_name, _manifest_path())


def _append_manifest_entry(entry: dict[str, Any]) -> None:
    manifest = _load_manifest()
    manifest["schema_version"] = "2.0"
    manifest.setdefault("python_abi", sys.implementation.cache_tag)
    manifest.setdefault("machine", platform.machine())
    entries = manifest.setdefault("entries", [])
    entries.append(entry)
    _write_manifest(manifest)


def _legacy_manifest_import_names() -> list[str]:
    path = _legacy_manifest_path()
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    imports: set[str] = set()
    for item in (manifest.get("packages") or {}).values():
        for name in item.get("import_names") or []:
            root = _normalize_import_root(name)
            if root:
                imports.add(root)
    return sorted(imports)


def manifest_import_names() -> list[str]:
    imports: set[str] = set(_legacy_manifest_import_names())
    manifest = _load_manifest()
    for entry in manifest.get("entries", []):
        for name in entry.get("import_names") or entry.get("modules") or []:
            root = _normalize_import_root(name)
            if root:
                imports.add(root)
    return sorted(imports)


def sanitize_install_error(message: str | None, limit: int = 600) -> str:
    text = str(message or "").strip()
    text = re.sub(r"https?://[^\s]+", lambda m: f"https://{_safe_domain(m.group(0))}/...", text)
    text = re.sub(r"(?i)(token|key|secret|password)=([^\s&]+)", r"\1=***", text)
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


@contextmanager
def _install_lock(root: Path):
    lock_path = root / ".install.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:  # pragma: no branch
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:  # pragma: no branch
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass


def _cleanup_path(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _module_available(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def classify_sandbox_violation(message: str) -> dict[str, str] | None:
    text = str(message or "")
    lowered = text.lower()
    if "network access forbidden" in lowered or "socket" in lowered:
        return {
            "category": "network_access",
            "message": "Sandbox blocked network access. This cannot be approved from the analysis UI.",
        }
    if "file write forbidden" in lowered:
        return {
            "category": "file_write",
            "message": "Sandbox blocked file writes. Analysis code may only read workspace data.",
        }
    if "file read outside workspace forbidden" in lowered:
        return {
            "category": "file_read",
            "message": "Sandbox blocked reading files outside the current workspace.",
        }
    if "subprocess" in lowered or "dangerous os operation" in lowered or "process" in lowered:
        return {
            "category": "process_execution",
            "message": "Sandbox blocked process execution. This cannot be approved from the analysis UI.",
        }
    if "ctypes access forbidden" in lowered:
        return {
            "category": "native_extension",
            "message": "Sandbox blocked native extension access after sandbox startup.",
        }
    if "import of" in lowered and "forbidden in sandbox" in lowered:
        return {
            "category": "forbidden_import",
            "message": "Sandbox blocked an unsafe import. This cannot be approved from the analysis UI.",
        }
    return None
