"""Atomic local persistence for Business Insight domain objects."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel

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
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
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

    def append_ndjson(self, relative_path: str, payload: BaseModel | dict[str, Any]) -> Path:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, default=self._json_default))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
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

    def list_files(self, relative_dir: str = "") -> Iterable[str]:
        directory = self._resolve(relative_dir or ".")
        if not directory.exists():
            return []
        return sorted(str(path.relative_to(self.root).as_posix()) for path in directory.rglob("*") if path.is_file())
