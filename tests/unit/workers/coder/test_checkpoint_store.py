"""LoopCheckpointStore 单元测试。"""
from __future__ import annotations

import uuid

import pytest

from src.workers.coder.checkpoint_store import (
    JsonFileLoopCheckpointStore,
    MemoryLoopCheckpointStore,
)
from src.workers.react_loop.models import Observation, ReActLoopCheckpoint, ReActLoopState


def _checkpoint(task_id: str) -> ReActLoopCheckpoint:
    return ReActLoopCheckpoint(
        loop_id=str(uuid.uuid4()),
        worker_id=str(uuid.uuid4()),
        task_id=task_id,
        current_state=ReActLoopState.OBSERVING,
        current_iteration=2,
        observations=[Observation(iteration=1, context_summary="s")],
    )


@pytest.fixture(params=["memory", "json"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryLoopCheckpointStore()
    return JsonFileLoopCheckpointStore(tmp_path / "ckpt")


def test_save_load_roundtrip(store):
    task_id = str(uuid.uuid4())
    store.save(_checkpoint(task_id))
    loaded = store.load(task_id)
    assert loaded is not None
    assert loaded.current_iteration == 2
    assert loaded.observations[0].context_summary == "s"


def test_load_missing_returns_none(store):
    assert store.load(str(uuid.uuid4())) is None


def test_delete(store):
    task_id = str(uuid.uuid4())
    store.save(_checkpoint(task_id))
    store.delete(task_id)
    assert store.load(task_id) is None
    store.delete(task_id)  # 幂等


def test_json_store_rejects_path_traversal(tmp_path):
    store = JsonFileLoopCheckpointStore(tmp_path)
    with pytest.raises(ValueError):
        store.load("../evil")
