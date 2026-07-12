"""Atomic local persistence for Business Insight domain objects."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, TypeVar

import pandas as pd
from pydantic import BaseModel

from data_formulator.datalake.workspace_metadata import WorkspaceLock

T = TypeVar("T", bound=BaseModel)


class LocalInsightStore:
    """Workspace-confined storage rooted at ``<workspace>/insight``.

    Callers pass relative paths only. The store rejects absolute paths and any
    traversal attempt before touching the filesystem.
    """

    def __init__(self, workspace_path: str | Path) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.root = self.workspace_path / "insight"
        self.root.mkdir(parents=True, exist_ok=True)

    def workspace_lock(self, timeout: float | None = None) -> WorkspaceLock:
        if timeout is None:
            return WorkspaceLock(self.workspace_path)
        return WorkspaceLock(self.workspace_path, timeout=timeout)

    def _resolve(self, relative_path: str | PurePosixPath) -> Path:
        path = PurePosixPath(str(relative_path).replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Insight paths must be relative and cannot traverse directories")
        resolved = (self.root / Path(*path.parts)).resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("Resolved path escapes insight storage root") from exc
        return resolved

    @staticmethod
    def _json_default(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @staticmethod
    def _fsync_path(path: str | Path) -> None:
        with open(path, "r+b") as handle:
            os.fsync(handle.fileno())

    def write_json(self, relative_path: str, payload: BaseModel | dict[str, Any]) -> Path:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload

        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, default=self._json_default)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except Exception:
            with suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise
        return target

    def read_json(self, relative_path: str) -> dict[str, Any]:
        target = self._resolve(relative_path)
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object at {relative_path}")
        return payload

    def read_model(self, relative_path: str, model_type: type[T]) -> T:
        return model_type.model_validate(self.read_json(relative_path))

    def write_parquet(
        self,
        relative_path: str,
        dataframe: pd.DataFrame,
        *,
        overwrite: bool = False,
    ) -> Path:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing parquet: {relative_path}")

        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        os.close(fd)
        try:
            dataframe.to_parquet(temp_name, index=False)
            self._fsync_path(temp_name)
            if target.exists() and not overwrite:
                raise FileExistsError(f"Refusing to overwrite existing parquet: {relative_path}")
            os.replace(temp_name, target)
        except Exception:
            with suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise
        return target

    def make_temp_dir(self, relative_parent: str = ".", *, prefix: str = ".staging.") -> str:
        """Create a temporary directory under the insight root and return its relative path."""

        parent = self._resolve(relative_parent or ".")
        parent.mkdir(parents=True, exist_ok=True)
        temp_path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent)).resolve()
        return temp_path.relative_to(self.root).as_posix()

    def move_tree(self, source_relative_path: str, target_relative_path: str) -> Path:
        """Atomically move a staged directory to its final relative path."""

        source = self._resolve(source_relative_path)
        target = self._resolve(target_relative_path)
        if not source.exists():
            raise FileNotFoundError(f"Staged insight path not found: {source_relative_path}")
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite insight path: {target_relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        return target

    def remove_tree(self, relative_path: str) -> None:
        """Remove a relative file or directory if it exists."""

        target = self._resolve(relative_path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def read_parquet(self, relative_path: str) -> pd.DataFrame:
        return pd.read_parquet(self._resolve(relative_path))

    def file_size(self, relative_path: str) -> int:
        return int(self._resolve(relative_path).stat().st_size)

    def parquet_shape(self, relative_path: str) -> tuple[int, int]:
        import pyarrow.parquet as pq

        metadata = pq.ParquetFile(self._resolve(relative_path)).metadata
        return int(metadata.num_rows), int(metadata.num_columns)

    def file_sha256(self, relative_path: str) -> str:
        target = self._resolve(relative_path)
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def append_ndjson(self, relative_path: str, payload: BaseModel | dict[str, Any]) -> Path:
        """Atomically append one JSON object by replacing the complete file.

        Callers that need concurrent append safety must hold ``workspace_lock``.
        Rewriting is intentionally acceptable for the first-version AgentRun
        budget, which caps the number of persisted steps.
        """

        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        line = (
            json.dumps(data, ensure_ascii=False, default=self._json_default) + "\n"
        ).encode("utf-8")
        existing = target.read_bytes() if target.exists() else b""

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except Exception:
            with suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise
        return target

    def read_ndjson(self, relative_path: str) -> list[dict[str, Any]]:
        target = self._resolve(relative_path)
        if not target.exists():
            return []
        records: list[dict[str, Any]] = []
        with target.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"Expected object on line {line_number} of {relative_path}")
                records.append(value)
        return records

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()

    def list(self, relative_dir: str = "") -> Iterable[str]:
        directory = self._resolve(relative_dir or ".")
        if not directory.exists():
            return []
        return sorted(str(path.relative_to(self.root).as_posix()) for path in directory.rglob("*") if path.is_file())

    def list_files(self, relative_dir: str = "") -> Iterable[str]:
        return self.list(relative_dir)
