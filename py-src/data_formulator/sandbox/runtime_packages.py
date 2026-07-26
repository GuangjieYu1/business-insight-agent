# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Runtime package approval and installation helpers for the local sandbox.

This module deliberately keeps the surface small:

* package approval records live in memory and expire quickly;
* package names are server-normalized and cannot come from the client;
* installation is performed by the trusted backend with ``shell=False``;
* runtime packages are installed into DATA_FORMULATOR_HOME/runtime-python.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data_formulator.datalake.workspace import get_data_formulator_home


_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MISSING_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")
_EXPLICIT_INSTALL_RE = re.compile(r"(?:\u4e0b\u8f7d|\u5b89\u88c5|download|install|pip\s+install)", re.IGNORECASE)
_PACKAGE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,127}")
_APPROVAL_TTL = timedelta(minutes=10)
_APPROVALS: dict[str, "RuntimePackageApproval"] = {}
_APPROVAL_LOCK = threading.Lock()

_IMPORT_PACKAGE_ALIASES = {
    "cv2": "opencv-python",
    "PIL": "Pillow",

    "sklearn": "scikit-learn",
}


_INSTALL_COMMAND_WORDS = {"download", "install", "pip", "package", "packages", "python", "analyze", "analysis", "use", "with", "and", "to", "for", "from"}

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
    status: str = "pending"
    consumed_at: datetime | None = None

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "packages": list(self.packages),
            "importNames": list(self.import_names),
            "expiresAt": self.expires_at.isoformat(),
            "source": "PyPI binary wheels",
            "installTarget": "DATA_FORMULATOR_HOME/runtime-python",
            "risk": (
                "Approved libraries run inside the server sandbox process. "
                "Network, file write, subprocess, and other sandbox limits remain active."
            ),
        }


@dataclass(frozen=True)
class RuntimePackageInstallResult:
    ok: bool
    status: str
    packages: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None

    def public_payload(self, approval_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "approval_status",
            "approvalId": approval_id,
            "status": self.status,
            "packages": self.packages,
        }
        if self.error_message:
            payload["error"] = self.error_message
        return payload


def runtime_install_enabled() -> bool:
    return os.environ.get("ENABLE_RUNTIME_PACKAGE_INSTALL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_runtime_package_dir() -> Path:
    return get_data_formulator_home() / "runtime-python"


def ensure_runtime_package_path() -> Path:
    runtime_dir = get_runtime_package_dir()
    runtime_str = str(runtime_dir)
    if runtime_str not in sys.path:
        sys.path.insert(0, runtime_str)
    return runtime_dir


def normalize_package_name(raw: str) -> str:
    cleaned = str(raw or "").strip()
    if not _PACKAGE_RE.fullmatch(cleaned):
        raise ValueError("Invalid PyPI package name")
    # PEP 503-ish normalization without requiring packaging as a runtime dep.
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
    """Find explicit user requests such as download xgboost."""
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
        try:
            spec = importlib.util.find_spec(import_name)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is None:
            missing.append(
                MissingRuntimePackage(
                    import_name=import_name,
                    package_name=package_for_import(import_name),
                )
            )
    return _dedupe_missing(missing)


def missing_runtime_packages_from_error(message: str) -> list[MissingRuntimePackage]:
    matches = _MISSING_RE.findall(str(message or ""))
    missing = []
    for match in matches:
        root = _normalize_import_root(match)
        if root:
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
) -> RuntimePackageApproval:
    normalized_packages = [normalize_package_name(pkg) for pkg in packages]
    normalized_imports = [_normalize_import_root(name) for name in import_names]
    normalized_imports = [name for name in normalized_imports if name]
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
    )
    with _APPROVAL_LOCK:
        _APPROVALS[approval.id] = approval
        _prune_expired_locked(now)
    return approval


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
    packages: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "approval_status",
        "approvalId": approval_id,
        "status": status,
        "packages": packages or [],
    }
    if error:
        payload["error"] = error
    return payload


def install_runtime_packages(
    *,
    packages: list[str],
    import_names: list[str],
    timeout_seconds: int | None = None,
) -> RuntimePackageInstallResult:
    if not runtime_install_enabled():
        return RuntimePackageInstallResult(
            ok=False,
            status="failed",
            error_message="Runtime package installation is disabled by the server.",
        )

    runtime_dir = ensure_runtime_package_path()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    timeout = timeout_seconds or int(os.environ.get("RUNTIME_PACKAGE_INSTALL_TIMEOUT", "300"))
    installed: list[dict[str, Any]] = []

    for raw_pkg in packages:
        try:
            package = normalize_package_name(raw_pkg)
        except ValueError as exc:
            return RuntimePackageInstallResult(ok=False, status="failed", error_message=str(exc))

        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--only-binary=:all:",
            "--target",
            str(runtime_dir),
            package,
        ]
        try:
            completed = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RuntimePackageInstallResult(
                ok=False,
                status="failed",
                error_message=f"Installing {package} timed out after {timeout}s.",
            )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            if len(detail) > 600:
                detail = detail[:600] + "..."
            return RuntimePackageInstallResult(
                ok=False,
                status="failed",
                error_message=f"Installing {package} failed. {detail}",
            )

        installed.append({"package": package, "version": _distribution_version(package)})

    importlib.invalidate_caches()
    failed_imports: list[str] = []
    for import_name in import_names:
        root = _normalize_import_root(import_name)
        if not root:
            continue
        try:
            spec = importlib.util.find_spec(root)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is None:
            failed_imports.append(root)

    if failed_imports:
        return RuntimePackageInstallResult(
            ok=False,
            status="failed",
            packages=installed,
            error_message=f"Installed packages, but import validation failed for: {', '.join(failed_imports)}.",
        )

    _write_manifest(runtime_dir, installed, import_names)
    return RuntimePackageInstallResult(ok=True, status="installed", packages=installed)


def _distribution_version(package: str) -> str | None:
    try:
        return importlib.metadata.distribution(package).version
    except importlib.metadata.PackageNotFoundError:
        return None


def _write_manifest(runtime_dir: Path, packages: list[dict[str, Any]], import_names: list[str]) -> None:
    manifest_path = runtime_dir / "_manifest.json"
    existing: dict[str, Any] = {"schema_version": "1.0", "packages": {}}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {"schema_version": "1.0", "packages": {}}

    package_map = existing.setdefault("packages", {})
    now = datetime.now(timezone.utc).isoformat()
    imports = sorted({_normalize_import_root(name) for name in import_names if _normalize_import_root(name)})
    for item in packages:
        package = item.get("package")
        if not package:
            continue
        package_map[package] = {
            "package": package,
            "version": item.get("version"),
            "import_names": imports,
            "installed_at": now,
        }

    fd, tmp_name = tempfile.mkstemp(prefix="_manifest.", suffix=".tmp", dir=str(runtime_dir))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_name, manifest_path)


def manifest_import_names() -> list[str]:
    manifest_path = get_runtime_package_dir() / "_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    imports: set[str] = set()
    for item in (manifest.get("packages") or {}).values():
        for name in item.get("import_names") or []:
            root = _normalize_import_root(name)
            if root:
                imports.add(root)
    return sorted(imports)


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

