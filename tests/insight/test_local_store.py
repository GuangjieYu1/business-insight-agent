from pathlib import Path

import pytest

from data_formulator.insight.domain import Project
from data_formulator.insight.storage import LocalInsightStore


def test_json_round_trip_and_ndjson(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    project = Project(id="project_1", workspace_id="workspace_1", name="Test")

    store.write_json("project.json", project)
    loaded = store.read_model("project.json", Project)
    assert loaded == project

    store.append_ndjson("runs/run_1/steps.ndjson", {"step": 1})
    store.append_ndjson("runs/run_1/steps.ndjson", {"step": 2})
    assert store.read_ndjson("runs/run_1/steps.ndjson") == [{"step": 1}, {"step": 2}]


def test_store_rejects_traversal(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    with pytest.raises(ValueError):
        store.write_json("../escape.json", {"bad": True})
