"""Runtime-approved Python package installation for the local sandbox."""

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
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from data_formulator.datalake.workspace import get_data_formulator_home

try:  # pragma: no cover - unavailable on some non-POSIX test runners
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

logger = logging.getLogger(__name__)

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9]+(?:[._-]?[A-Za-z0-9]+)*$")
_MISSING_MODULE_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")
_APPROVAL_TTL_SECONDS = 10 * 60

_PRIMARY_INDEX_URL = os.environ.get(
    "DF_PIP_PRIMARY_INDEX_URL",
    "https://mirrors.aliyun.com/pypi/simple/",
)
_SECONDARY_INDEX_URL = os.environ.get(
    "DF_PIP_SECONDARY_INDEX_URL",
    "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
)
_OFFICIAL_INDEX_URL = os.environ.get(
    "DF_PIP_OFFICIAL_INDEX_URL",
    "https://pypi.org/simple",
)

_MODULE_TO_PACKAGE = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "googleapiclient": "google-api-python-client",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}

_FORBIDDEN_APPROVAL_MODULES = frozenset(
    {
        "ctypes",
        "http",
        "multiprocessing",
        "requests",
        "resource",
        "shutil",
        "signal",
        "socket",
        "subprocess",
        "urllib",
    }
)

_SOURCE_FAILURE_PATTERNS = (
    "connection timed out",
    "connect timeout",
    "connection refused",
    "could not find a version that satisfies the requirement",
    "failed to establish a new connection",
    "name or service not known",
    "newconnectionerror",
    "no matching distribution found for",
    "read timed out",
    "temporary failure in name resolution",
    "too many 5xx error responses",
)

_LOCAL_FAILURE_PATTERNS = (
    "invalid requirement",
    "is not a supported wheel on this platform",
    "no space left on device",
    "permission denied",
)

_VERIFY_IMPORT_SCRIPT = """\
import importlib
import json
import sys
from importlib import metadata

paths = json.loads(sys.argv[1])
modules = json.loads(sys.argv[2])
packages = json.loads(sys.argv[3])
for path in reversed(paths):
    if path not in sys.path:
        sys.path.insert(0, path)
versions = {}
for module_name in modules:
    importlib.import_module(module_name)
for package_name in packages:
    try:
        versions[package_name] = metadata.version(package_name)
    except metadata.PackageNotFoundError:
        versions[package_name] = "unknown"
print(json.dumps({"versions": versions}, ensure_ascii=False))
"""


class RuntimePackageApprovalError(ValueError):
    """Raised when an approval token is invalid or expired."""


@dataclass(frozen=True)
class MissingPackageRequest:
    modules: tuple[str, ...]
    packages: tuple[str, ...]


@dataclass(frozen=True)
class RuntimePackageApproval:
    id: str
    kind: str
    identity_id: str
    modules: tuple[str, ...]
    packages: tuple[str, ...]
    trajectory: list[dict]
    completed_step_count: int
    input_tables: list[dict]
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class RuntimeInstallResult:
    status: str
    modules: tuple[str, ...]
    packages: tuple[str, ...]
    source_id: str | None = None
    source_label: str | None = None
    index_url: str | None = None
    versions: dict[str, str] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class _AttemptResult:
    status: str
    failure_kind: str | None = None
    source_id: str | None = None
    source_label: str | None = None
    index_url: str | None = None
    versions: dict[str, str] | None = None
    error_message: str | None = None


_approval_lock = threading.Lock()
_approval_store: dict[str, RuntimePackageApproval] = {}


def runtime_package_installs_enabled() -> bool:
    value = os.environ.get("ENABLE_RUNTIME_PACKAGE_INSTALL", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def runtime_approval_source_plan(kind: str = "python_package_install") -> list[dict[str, str]]:
    if kind == "official_pypi_fallback":
        return [_source_info("official")]
    return [_source_info("primary"), _source_info("secondary")]


def get_runtime_package_root() -> Path:
    cache_tag = sys.implementation.cache_tag or f"python-{sys.version_info.major}{sys.version_info.minor}"
    machine = (platform.machine() or "unknown").lower()
    return get_data_formulator_home() / "runtime-python" / f"{cache_tag}-{machine}"


def runtime_bundle_paths() -> list[str]:
    manifest = _load_manifest()
    paths: list[str] = []
    for entry in reversed(manifest.get("entries", [])):
        bundle_name = str(entry.get("bundle", "")).strip()
        if not bundle_name:
            continue
        bundle_path = (_bundle_dir() / bundle_name).resolve()
        if bundle_path.exists():
            paths.append(str(bundle_path))
    return paths


def approved_runtime_modules() -> list[str]:
    seen: set[str] = set()
    modules: list[str] = []
    manifest = _load_manifest()
    for entry in reversed(manifest.get("entries", [])):
        for raw_module in entry.get("modules", []):
            module_name = str(raw_module).strip()
            if not module_name or module_name in seen:
                continue
            seen.add(module_name)
            modules.append(module_name)
    return modules


def ensure_runtime_package_paths() -> list[str]:
    paths = runtime_bundle_paths()
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)
    return paths


def detect_missing_runtime_packages_from_code(code: str) -> MissingPackageRequest | None:
    if not runtime_package_installs_enabled():
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_modules.add(node.module.split(".")[0])
    return _build_missing_request(imported_modules)


def detect_missing_runtime_packages_from_error_message(error_message: str) -> MissingPackageRequest | None:
    if not runtime_package_installs_enabled():
        return None
    match = _MISSING_MODULE_RE.search(error_message or "")
    if not match:
        return None
    return _build_missing_request({match.group(1).split(".")[0]})


def create_runtime_package_approval(
    *,
    identity_id: str,
    kind: str,
    request: MissingPackageRequest,
    trajectory: list[dict],
    completed_step_count: int,
    input_tables: list[dict],
) -> RuntimePackageApproval:
    now = time.time()
    approval = RuntimePackageApproval(
        id=uuid.uuid4().hex,
        kind=kind,
        identity_id=identity_id,
        modules=request.modules,
        packages=request.packages,
        trajectory=trajectory,
        completed_step_count=completed_step_count,
        input_tables=input_tables,
        created_at=now,
        expires_at=now + _APPROVAL_TTL_SECONDS,
    )
    with _approval_lock:
        _purge_expired_locked(now)
        _approval_store[approval.id] = approval
    return approval


def create_followup_runtime_package_approval(
    approval: RuntimePackageApproval,
    *,
    kind: str,
) -> RuntimePackageApproval:
    return create_runtime_package_approval(
        identity_id=approval.identity_id,
        kind=kind,
        request=MissingPackageRequest(approval.modules, approval.packages),
        trajectory=approval.trajectory,
        completed_step_count=approval.completed_step_count,
        input_tables=approval.input_tables,
    )


def consume_runtime_package_approval(
    approval_id: str,
    *,
    identity_id: str,
) -> RuntimePackageApproval:
    now = time.time()
    with _approval_lock:
        _purge_expired_locked(now)
        approval = _approval_store.pop(approval_id, None)
    if approval is None:
        raise RuntimePackageApprovalError("Approval request is missing, expired, or already used.")
    if approval.identity_id != identity_id:
        raise RuntimePackageApprovalError("Approval request does not belong to the current user.")
    if approval.expires_at <= now:
        raise RuntimePackageApprovalError("Approval request expired.")
    return approval


def install_runtime_packages(
    *,
    packages: tuple[str, ...],
    modules: tuple[str, ...],
    allow_official: bool,
    progress_callback=None,
) -> RuntimeInstallResult:
    normalized_packages = tuple(_validate_package_name(name) for name in packages)
    root = get_runtime_package_root()
    root.mkdir(parents=True, exist_ok=True)

    attempts = [("official", _OFFICIAL_INDEX_URL)] if allow_official else [
        ("primary", _PRIMARY_INDEX_URL),
        ("secondary", _SECONDARY_INDEX_URL),
    ]

    with _install_lock(root):
        ensure_runtime_package_paths()
        if all(_module_is_available(module_name) for module_name in modules):
            return RuntimeInstallResult(
                status="installed",
                modules=modules,
                packages=normalized_packages,
                source_id="existing",
                source_label="Existing runtime bundle",
                versions=_resolve_versions(normalized_packages),
            )

        for index, (source_id, index_url) in enumerate(attempts):
            source = _source_info(source_id)
            if progress_callback:
                progress_callback(
                    "retrying_secondary" if source_id == "secondary" else "installing",
                    source,
                )

            attempt = _install_from_index(
                root=root,
                packages=normalized_packages,
                modules=modules,
                source_id=source_id,
                index_url=index_url,
            )
            if attempt.status == "installed":
                ensure_runtime_package_paths()
                return RuntimeInstallResult(
                    status="installed",
                    modules=modules,
                    packages=normalized_packages,
                    source_id=attempt.source_id,
                    source_label=attempt.source_label,
                    index_url=attempt.index_url,
                    versions=attempt.versions or {},
                )

            if attempt.failure_kind == "source" and index + 1 < len(attempts):
                continue

            if attempt.failure_kind == "source" and not allow_official:
                return RuntimeInstallResult(
                    status="awaiting_official_approval",
                    modules=modules,
                    packages=normalized_packages,
                    error_message=attempt.error_message,
                )

            return RuntimeInstallResult(
                status="failed",
                modules=modules,
                packages=normalized_packages,
                source_id=attempt.source_id,
                source_label=attempt.source_label,
                index_url=attempt.index_url,
                error_message=attempt.error_message,
            )

    return RuntimeInstallResult(
        status="failed",
        modules=modules,
        packages=normalized_packages,
        error_message="Runtime package installation ended unexpectedly.",
    )


def approval_event_payload(
    approval: RuntimePackageApproval,
    *,
    error_message: str | None = None,
) -> dict:
    payload = {
        "type": "approval_required",
        "kind": approval.kind,
        "approval": {"id": approval.id},
        "packages": list(approval.packages),
        "modules": list(approval.modules),
        "sources": runtime_approval_source_plan(approval.kind),
    }
    if error_message:
        payload["error_message"] = error_message
    return payload


def approval_status_event(
    status: str,
    *,
    packages: tuple[str, ...],
    source: dict[str, str] | None = None,
    versions: dict[str, str] | None = None,
    error_message: str | None = None,
) -> dict:
    event = {
        "type": "approval_status",
        "status": status,
        "packages": list(packages),
    }
    if source:
        event["source"] = source
    if versions:
        event["versions"] = versions
    if error_message:
        event["error_message"] = error_message
    return event


def _build_missing_request(module_names: set[str]) -> MissingPackageRequest | None:
    ensure_runtime_package_paths()
    missing_modules: list[str] = []
    packages: list[str] = []

    for raw_module in sorted(module_names):
        module_name = raw_module.split(".")[0].strip()
        if not module_name or module_name in _FORBIDDEN_APPROVAL_MODULES:
            continue
        if _module_is_available(module_name):
            continue
        package_name = _MODULE_TO_PACKAGE.get(module_name, module_name)
        normalized = _validate_package_name(package_name)
        if module_name not in missing_modules:
            missing_modules.append(module_name)
        if normalized not in packages:
            packages.append(normalized)

    if not packages:
        return None
    return MissingPackageRequest(tuple(missing_modules), tuple(packages))


def _module_is_available(module_name: str) -> bool:
    ensure_runtime_package_paths()
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _runtime_manifest_path() -> Path:
    return get_runtime_package_root() / "manifest.json"


def _bundle_dir() -> Path:
    return get_runtime_package_root() / "bundles"


def _staging_dir() -> Path:
    return get_runtime_package_root() / ".staging"


def _load_manifest() -> dict:
    manifest_path = _runtime_manifest_path()
    if not manifest_path.exists():
        return {"entries": []}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Failed to read runtime package manifest", exc_info=True)
        return {"entries": []}
    if not isinstance(raw, dict):
        return {"entries": []}
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return {"entries": []}
    return {"entries": [entry for entry in entries if isinstance(entry, dict)]}


def _write_manifest(manifest: dict) -> None:
    manifest_path = _runtime_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(manifest_path)


def _source_info(source_id: str) -> dict[str, str]:
    if source_id == "primary":
        return {
            "id": "primary",
            "label": "Aliyun HTTPS",
            "url": _PRIMARY_INDEX_URL,
        }
    if source_id == "secondary":
        return {
            "id": "secondary",
            "label": "Tsinghua TUNA",
            "url": _SECONDARY_INDEX_URL,
        }
    return {
        "id": "official",
        "label": "Official PyPI",
        "url": _OFFICIAL_INDEX_URL,
    }


def _install_from_index(
    *,
    root: Path,
    packages: tuple[str, ...],
    modules: tuple[str, ...],
    source_id: str,
    index_url: str,
) -> _AttemptResult:
    source = _source_info(source_id)
    staging_parent = _staging_dir()
    staging_parent.mkdir(parents=True, exist_ok=True)
    _bundle_dir().mkdir(parents=True, exist_ok=True)
    staging_dir = staging_parent / f"install-{uuid.uuid4().hex}"

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--only-binary=:all:",
        "--target",
        str(staging_dir),
        "--index-url",
        index_url,
        *packages,
    ]

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:
        _cleanup_path(staging_dir)
        return _AttemptResult(
            status="failed",
            failure_kind="local",
            source_id=source["id"],
            source_label=source["label"],
            index_url=source["url"],
            error_message=f"{type(exc).__name__}: {exc}",
        )

    combined_output = "\n".join(
        part for part in (proc.stdout.strip(), proc.stderr.strip()) if part
    ).strip()

    if proc.returncode != 0:
        _cleanup_path(staging_dir)
        failure_kind = _classify_install_failure(combined_output)
        return _AttemptResult(
            status="failed",
            failure_kind=failure_kind,
            source_id=source["id"],
            source_label=source["label"],
            index_url=source["url"],
            error_message=combined_output or "pip install failed",
        )

    verify = _verify_installed_bundle(staging_dir, modules, packages)
    if verify.status != "installed":
        _cleanup_path(staging_dir)
        return _AttemptResult(
            status="failed",
            failure_kind="local",
            source_id=source["id"],
            source_label=source["label"],
            index_url=source["url"],
            error_message=verify.error_message or "Installed packages could not be imported.",
        )

    bundle_name = f"bundle-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    destination = _bundle_dir() / bundle_name
    staging_dir.rename(destination)

    manifest = _load_manifest()
    manifest["entries"].append(
        {
            "bundle": bundle_name,
            "modules": list(modules),
            "packages": list(packages),
            "source_id": source["id"],
            "source_label": source["label"],
            "index_url": source["url"],
            "versions": verify.versions or {},
            "installed_at": int(time.time()),
        }
    )
    _write_manifest(manifest)

    return _AttemptResult(
        status="installed",
        source_id=source["id"],
        source_label=source["label"],
        index_url=source["url"],
        versions=verify.versions or {},
    )


def _verify_installed_bundle(
    staging_dir: Path,
    modules: tuple[str, ...],
    packages: tuple[str, ...],
) -> _AttemptResult:
    verify_paths = [str(staging_dir), *runtime_bundle_paths()]
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _VERIFY_IMPORT_SCRIPT,
            json.dumps(verify_paths, ensure_ascii=False),
            json.dumps(list(modules), ensure_ascii=False),
            json.dumps(list(packages), ensure_ascii=False),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        return _AttemptResult(
            status="failed",
            failure_kind="local",
            error_message=(proc.stderr or proc.stdout or "Import verification failed").strip(),
        )
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        payload = {}
    versions = payload.get("versions") if isinstance(payload, dict) else {}
    if not isinstance(versions, dict):
        versions = {}
    return _AttemptResult(status="installed", versions={str(k): str(v) for k, v in versions.items()})


def _resolve_versions(packages: tuple[str, ...]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in packages:
        try:
            versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            versions[package_name] = "unknown"
    return versions


def _classify_install_failure(output: str) -> str:
    lower = (output or "").lower()
    if any(pattern in lower for pattern in _LOCAL_FAILURE_PATTERNS):
        return "local"
    if any(pattern in lower for pattern in _SOURCE_FAILURE_PATTERNS):
        return "source"
    return "source"


def _validate_package_name(name: str) -> str:
    value = normalize_distribution_name(name)
    if not _PACKAGE_RE.fullmatch(value):
        raise ValueError(f"Invalid package name: {name!r}")
    return value


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "").strip()).lower()


@contextmanager
def _install_lock(root: Path):
    lock_path = root / ".install.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:  # pragma: no branch
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:  # pragma: no branch
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _cleanup_path(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.warning("Failed to clean up runtime package staging dir", exc_info=True)


def _purge_expired_locked(now: float) -> None:
    expired = [
        approval_id
        for approval_id, approval in _approval_store.items()
        if approval.expires_at <= now
    ]
    for approval_id in expired:
        _approval_store.pop(approval_id, None)


ensure_runtime_package_paths()
