"""
Coder Worker 的 ReAct Loop 检查点存储

对齐：REQ-RT-005（Checkpoint Protocol）

- MemoryLoopCheckpointStore：进程内存储，供测试与单进程使用
- JsonFileLoopCheckpointStore：落盘 JSON，用于进程崩溃后恢复

ReActLoopCheckpoint 的 actions / evidences 字段是 list[Any]，落盘后会变成 dict，
所以加载时需要重新校验为 Action / Evidence 实体。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from src.runtime.entities.action import Action
from src.runtime.entities.evidence import Evidence
from src.workers.react_loop.models import ReActLoopCheckpoint


class LoopCheckpointStore(Protocol):
    """检查点存储接口，按 task_id 保存最新一份检查点。"""

    def save(self, checkpoint: ReActLoopCheckpoint) -> None: ...

    def load(self, task_id: str) -> ReActLoopCheckpoint | None: ...

    def delete(self, task_id: str) -> None: ...


class MemoryLoopCheckpointStore:
    """内存存储：保存时深拷贝，避免后续循环修改影响已保存的快照。"""

    def __init__(self) -> None:
        self._items: dict[str, ReActLoopCheckpoint] = {}

    def save(self, checkpoint: ReActLoopCheckpoint) -> None:
        self._items[checkpoint.task_id] = checkpoint.model_copy(deep=True)

    def load(self, task_id: str) -> ReActLoopCheckpoint | None:
        item = self._items.get(task_id)
        return item.model_copy(deep=True) if item is not None else None

    def delete(self, task_id: str) -> None:
        self._items.pop(task_id, None)


class JsonFileLoopCheckpointStore:
    """JSON 文件存储：每个 task 一个文件，先写临时文件再原子替换。"""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        # task_id 来自 UUID 校验，但这里仍做一次防御，禁止路径分隔符
        if not task_id or any(ch in task_id for ch in ("/", "\\", "..")):
            raise ValueError(f"非法的 task_id: {task_id!r}")
        return self._dir / f"{task_id}.loop-checkpoint.json"

    def save(self, checkpoint: ReActLoopCheckpoint) -> None:
        path = self._path(checkpoint.task_id)
        payload = checkpoint.model_dump(mode="json")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, task_id: str) -> ReActLoopCheckpoint | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["actions"] = [Action.model_validate(a) for a in raw.get("actions", [])]
        raw["evidences"] = [Evidence.model_validate(e) for e in raw.get("evidences", [])]
        return ReActLoopCheckpoint.model_validate(raw)

    def delete(self, task_id: str) -> None:
        path = self._path(task_id)
        if path.exists():
            path.unlink()
