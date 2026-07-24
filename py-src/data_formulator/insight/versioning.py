"""Mutable dataset version workflows for Business Insight."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import re
from typing import Any

import pandas as pd

from data_formulator.insight.domain import Dataset, DatasetVersion, Project
from data_formulator.insight.domain.models import CleaningOperation, DatasetVersionStatus, new_id, utc_now
from data_formulator.insight.registry import (
    PROJECT_PATH,
    InsightRegistryError,
    _dataset_path,
    _require_text,
    _validate_registry_id,
    _version_json_path,
    _version_parquet_path,
    read_dataset,
    read_dataset_version,
    read_project,
)
from data_formulator.insight.storage import InsightStore

_VERSION_ID_RE = re.compile(r"^version_(\d+)$")


class InsightVersioningError(InsightRegistryError):
    """Raised when a dataset version workflow cannot be completed safely."""


@dataclass(frozen=True)
class DatasetVersionMutation:
    dataset: Dataset
    version: DatasetVersion
    operation: CleaningOperation


@dataclass(frozen=True)
class DatasetActivation:
    dataset: Dataset
    active_version: DatasetVersion
    previous_version: DatasetVersion | None
    operation: CleaningOperation
    undone_operation: CleaningOperation | None = None


def _operation_path(operation_id: str) -> str:
    return f"operations/{operation_id}.json"


def _version_sort_key(version: DatasetVersion) -> tuple[int, str]:
    match = _VERSION_ID_RE.fullmatch(version.id)
    if match is None:
        return (10**9, version.id)
    return (int(match.group(1)), version.id)


def _next_version_id(store: InsightStore, dataset_id: str) -> str:
    highest = -1
    for relative_path in store.list(f"datasets/{dataset_id}/versions"):
        if not relative_path.endswith(".json"):
            continue
        version_name = relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".json")
        match = _VERSION_ID_RE.fullmatch(version_name)
        if match is None:
            continue
        highest = max(highest, int(match.group(1)))
    return f"version_{highest + 1:03d}"


def list_dataset_versions(store: InsightStore, dataset_id: str) -> list[DatasetVersion]:
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    versions: list[DatasetVersion] = []
    for relative_path in store.list(f"datasets/{dataset_id}/versions"):
        if relative_path.endswith(".json"):
            versions.append(store.read_model(relative_path, DatasetVersion))
    return sorted(versions, key=_version_sort_key)


def read_operation(store: InsightStore, operation_id: str) -> CleaningOperation | None:
    operation_id = _validate_registry_id(operation_id, "operation_id")
    path = _operation_path(operation_id)
    if not store.exists(path):
        return None
    return store.read_model(path, CleaningOperation)


def _require_dataset_with_versions(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
) -> tuple[Dataset, DatasetVersion]:
    dataset = read_dataset(store, dataset_id)
    if dataset is None:
        raise InsightVersioningError(f"Dataset not found: {dataset_id}")
    if dataset.workspace_id != workspace_id:
        raise InsightVersioningError("Dataset workspace_id does not match active workspace")

    active_version = read_dataset_version(store, dataset.id, dataset.active_version_id)
    if active_version is None:
        raise InsightVersioningError(
            f"Active dataset version not found: {dataset.id}/{dataset.active_version_id}"
        )
    if active_version.workspace_id != workspace_id:
        raise InsightVersioningError("Dataset version workspace_id does not match active workspace")
    return dataset, active_version


def _restore_model(store: InsightStore, relative_path: str, payload: Dataset | DatasetVersion | CleaningOperation | Project) -> None:
    store.write_json(relative_path, payload)


def _sync_project_active_dataset(store: InsightStore, *, workspace_id: str, dataset_id: str) -> tuple[str, Project] | None:
    project = read_project(store)
    if project is None:
        return None
    if project.workspace_id != workspace_id:
        raise InsightVersioningError("Project workspace_id does not match active workspace")
    updated_project = project.model_copy(
        update={
            "active_dataset_id": dataset_id,
            "updated_at": utc_now(),
        }
    )
    return PROJECT_PATH, updated_project


def create_dataset_version(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    dataframe: pd.DataFrame,
    reason: str,
    parent_version_id: str | None = None,
    operation_type: str = "create_version",
    parameters: dict[str, Any] | None = None,
    activate: bool = True,
) -> DatasetVersionMutation:
    workspace_id = _require_text(workspace_id, "workspace_id")
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    reason = _require_text(reason, "reason")
    operation_type = _require_text(operation_type, "operation_type")
    requested_parent = _validate_registry_id(parent_version_id, "parent_version_id") if parent_version_id else None

    with store.workspace_lock():
        dataset, active_version = _require_dataset_with_versions(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
        )
        parent_version_id = requested_parent or active_version.id
        parent_version = read_dataset_version(store, dataset.id, parent_version_id)
        if parent_version is None:
            raise InsightVersioningError(
                f"Parent dataset version not found: {dataset.id}/{parent_version_id}"
            )
        if parent_version.workspace_id != workspace_id:
            raise InsightVersioningError("Parent dataset version workspace_id does not match active workspace")
        if parent_version.status == DatasetVersionStatus.INVALID:
            raise InsightVersioningError("Cannot branch from an invalid dataset version")

        version_id = _next_version_id(store, dataset.id)
        version_parquet_path = _version_parquet_path(dataset.id, version_id)
        version_json_path = _version_json_path(dataset.id, version_id)
        operation_id = new_id("operation")
        operation_path = _operation_path(operation_id)
        now = utc_now()

        version = DatasetVersion(
            id=version_id,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
            dataset_id=dataset.id,
            parent_version_id=parent_version.id,
            created_by_operation_id=operation_id,
            content_hash="",
            row_count=int(len(dataframe)),
            column_count=int(len(dataframe.columns)),
            file_ref=version_parquet_path,
            status=DatasetVersionStatus.ACTIVE if activate else DatasetVersionStatus.HISTORICAL,
        )
        operation = CleaningOperation(
            id=operation_id,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
            operation_type=operation_type,
            input_version_id=parent_version.id,
            output_version_id=version_id,
            parameters={**(parameters or {}), "dataset_id": dataset.id},
            reason=reason,
            status="completed",
        )

        created_paths: list[str] = []
        restore_models: list[tuple[str, Dataset | DatasetVersion | CleaningOperation]] = []
        try:
            store.write_parquet(version_parquet_path, dataframe, overwrite=False)
            created_paths.append(version_parquet_path)
            version = version.model_copy(update={"content_hash": store.file_sha256(version_parquet_path)})
            store.write_json(version_json_path, version)
            created_paths.append(version_json_path)
            store.write_json(operation_path, operation)
            created_paths.append(operation_path)

            updated_dataset = dataset
            if activate:
                updated_active = active_version.model_copy(
                    update={"status": DatasetVersionStatus.HISTORICAL, "updated_at": now}
                )
                restore_models.append((_version_json_path(dataset.id, active_version.id), active_version))
                store.write_json(_version_json_path(dataset.id, active_version.id), updated_active)
                updated_dataset = dataset.model_copy(
                    update={"active_version_id": version.id, "updated_at": now}
                )
                restore_models.append((_dataset_path(dataset.id), dataset))
                store.write_json(_dataset_path(dataset.id), updated_dataset)

                project_update = _sync_project_active_dataset(
                    store,
                    workspace_id=workspace_id,
                    dataset_id=dataset.id,
                )
                if project_update is not None:
                    project_path, updated_project = project_update
                    original_project = read_project(store)
                    if original_project is not None:
                        restore_models.append((project_path, original_project))
                    store.write_json(project_path, updated_project)

                dataset = updated_dataset
        except Exception:
            for relative_path, original_model in reversed(restore_models):
                with suppress(Exception):
                    _restore_model(store, relative_path, original_model)
            for relative_path in reversed(created_paths):
                with suppress(Exception):
                    if store.exists(relative_path):
                        store.remove_tree(relative_path)
            raise

        return DatasetVersionMutation(dataset=dataset, version=version, operation=operation)


def _activate_dataset_version_locked(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    target_version_id: str,
    reason: str,
    operation_type: str,
) -> DatasetActivation:
    dataset, active_version = _require_dataset_with_versions(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
    )
    if active_version.id == target_version_id:
        raise InsightVersioningError(f"Dataset version is already active: {dataset_id}/{target_version_id}")

    target_version = read_dataset_version(store, dataset.id, target_version_id)
    if target_version is None:
        raise InsightVersioningError(f"Dataset version not found: {dataset.id}/{target_version_id}")
    if target_version.workspace_id != workspace_id:
        raise InsightVersioningError("Dataset version workspace_id does not match active workspace")
    if target_version.status == DatasetVersionStatus.INVALID:
        raise InsightVersioningError("Cannot activate an invalid dataset version")

    now = utc_now()
    updated_active = active_version.model_copy(
        update={"status": DatasetVersionStatus.HISTORICAL, "updated_at": now}
    )
    updated_target = target_version.model_copy(
        update={"status": DatasetVersionStatus.ACTIVE, "updated_at": now}
    )
    updated_dataset = dataset.model_copy(
        update={"active_version_id": target_version.id, "updated_at": now}
    )
    operation = CleaningOperation(
        id=new_id("operation"),
        workspace_id=workspace_id,
        created_at=now,
        updated_at=now,
        operation_type=_require_text(operation_type, "operation_type"),
        input_version_id=active_version.id,
        output_version_id=target_version.id,
        parameters={"dataset_id": dataset.id},
        reason=_require_text(reason, "reason"),
        status="completed",
    )

    restore_models: list[tuple[str, Dataset | DatasetVersion | CleaningOperation]] = [
        (_version_json_path(dataset.id, active_version.id), active_version),
        (_version_json_path(dataset.id, target_version.id), target_version),
        (_dataset_path(dataset.id), dataset),
    ]
    created_paths: list[str] = []

    try:
        store.write_json(_version_json_path(dataset.id, active_version.id), updated_active)
        store.write_json(_version_json_path(dataset.id, target_version.id), updated_target)
        store.write_json(_dataset_path(dataset.id), updated_dataset)

        project_update = _sync_project_active_dataset(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
        )
        if project_update is not None:
            project_path, updated_project = project_update
            original_project = read_project(store)
            if original_project is not None:
                restore_models.append((project_path, original_project))
            store.write_json(project_path, updated_project)

        operation_path = _operation_path(operation.id)
        store.write_json(operation_path, operation)
        created_paths.append(operation_path)
    except Exception:
        for relative_path, original_model in reversed(restore_models):
            with suppress(Exception):
                _restore_model(store, relative_path, original_model)
        for relative_path in reversed(created_paths):
            with suppress(Exception):
                if store.exists(relative_path):
                    store.remove_tree(relative_path)
        raise

    return DatasetActivation(
        dataset=updated_dataset,
        active_version=updated_target,
        previous_version=active_version,
        operation=operation,
    )


def activate_dataset_version(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
    reason: str = "Activate dataset version",
) -> DatasetActivation:
    workspace_id = _require_text(workspace_id, "workspace_id")
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    version_id = _validate_registry_id(version_id, "version_id")
    with store.workspace_lock():
        return _activate_dataset_version_locked(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            target_version_id=version_id,
            reason=reason,
            operation_type="activate_version",
        )


def undo_dataset_version_by_operation(
    store: InsightStore,
    *,
    workspace_id: str,
    operation_id: str,
    reason: str = "Undo dataset operation",
) -> DatasetActivation:
    workspace_id = _require_text(workspace_id, "workspace_id")
    operation_id = _validate_registry_id(operation_id, "operation_id")

    with store.workspace_lock():
        original_operation = read_operation(store, operation_id)
        if original_operation is None:
            raise InsightVersioningError(f"Operation not found: {operation_id}")
        if original_operation.workspace_id != workspace_id:
            raise InsightVersioningError("Operation workspace_id does not match active workspace")
        if original_operation.output_version_id is None:
            raise InsightVersioningError("Operation does not create an output dataset version")

        dataset_id = original_operation.parameters.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise InsightVersioningError("Operation is missing dataset_id metadata")
        dataset_id = _validate_registry_id(dataset_id, "dataset_id")

        dataset, active_version = _require_dataset_with_versions(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
        )
        if active_version.id != original_operation.output_version_id:
            raise InsightVersioningError(
                "Undo requires the operation output version to still be the active dataset version"
            )
        if original_operation.input_version_id == active_version.id:
            raise InsightVersioningError("Operation input and output versions are identical; nothing to undo")

        activation = _activate_dataset_version_locked(
            store,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            target_version_id=original_operation.input_version_id,
            reason=reason,
            operation_type="undo_activation",
        )

        updated_original_operation = original_operation.model_copy(
            update={"status": "undone", "updated_at": activation.operation.updated_at}
        )
        try:
            store.write_json(_operation_path(original_operation.id), updated_original_operation)
        except Exception:
            with suppress(Exception):
                _activate_dataset_version_locked(
                    store,
                    workspace_id=workspace_id,
                    dataset_id=dataset.id,
                    target_version_id=activation.previous_version.id if activation.previous_version else active_version.id,
                    reason="Restore dataset version after undo failure",
                    operation_type="activate_version",
                )
            raise

        return DatasetActivation(
            dataset=activation.dataset,
            active_version=activation.active_version,
            previous_version=activation.previous_version,
            operation=activation.operation,
            undone_operation=updated_original_operation,
        )