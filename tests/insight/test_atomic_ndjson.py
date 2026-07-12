from pathlib import Path

import pytest

from data_formulator.insight.storage import LocalInsightStore


def test_failed_ndjson_append_preserves_existing_history(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    path = "runs/run_1/steps.ndjson"
    store.append_ndjson(path, {"id": "step_1", "status": "completed"})
    before = (store.root / path).read_bytes()

    with pytest.raises(TypeError):
        store.append_ndjson(path, {"id": "step_2", "detail": object()})

    assert (store.root / path).read_bytes() == before
    assert store.read_ndjson(path) == [{"id": "step_1", "status": "completed"}]
