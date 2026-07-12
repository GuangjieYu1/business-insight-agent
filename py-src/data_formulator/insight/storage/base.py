"""Shared storage contracts for Business Insight persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ContextManager, Iterable, Protocol, TypeVar, runtime_checkable

import pandas as pd
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class InsightStore(Protocol):
    """Protocol for workspace-scoped Business Insight storage backends."""

    workspace_path: Path
    root: Path

    def workspace_lock(self, timeout: float | None = None) -> ContextManager[object]:
        ...

    def write_json(self, relative_path: str, payload: BaseModel | dict[str, Any]) -> Path:
        ...

    def read_json(self, relative_path: str) -> dict[str, Any]:
        ...

    def read_model(self, relative_path: str, model_type: type[T]) -> T:
        ...

    def write_parquet(
        self,
        relative_path: str,
        dataframe: pd.DataFrame,
        *,
        overwrite: bool = False,
    ) -> Path:
        ...

    def read_parquet(self, relative_path: str) -> pd.DataFrame:
        ...

    def make_temp_dir(self, relative_parent: str = ".", *, prefix: str = ".staging.") -> str:
        ...

    def move_tree(self, source_relative_path: str, target_relative_path: str) -> Path:
        ...

    def remove_tree(self, relative_path: str) -> None:
        ...

    def append_ndjson(self, relative_path: str, payload: BaseModel | dict[str, Any]) -> Path:
        ...

    def read_ndjson(self, relative_path: str) -> list[dict[str, Any]]:
        ...

    def exists(self, relative_path: str) -> bool:
        ...

    def list(self, relative_dir: str = "") -> Iterable[str]:
        ...

    def list_files(self, relative_dir: str = "") -> Iterable[str]:
        ...

    def file_size(self, relative_path: str) -> int:
        ...

    def parquet_shape(self, relative_path: str) -> tuple[int, int]:
        ...

    def file_sha256(self, relative_path: str) -> str:
        ...