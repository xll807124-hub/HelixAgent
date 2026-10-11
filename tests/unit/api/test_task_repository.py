"""Task 仓储单元测试。"""
from __future__ import annotations

import pytest

from src.api.repositories.task_repository import (
    TaskAlreadyTerminalError,
    TaskNotFoundError,
    TaskRepository,
)
from src.api.schemas.task import TaskCreateRequest
from src.runtime.entities.task import RiskLevel, SourceType


def _valid_request() -> TaskCreateRequest:
    return TaskCreateRequest(
        title="T",
        description="D",
        risk_level=RiskLevel.LOW,
        source_type=SourceType.NATURAL_LANGUAGE,
        workflow_template_id="wf",
        workflow_template_version="v1",
        base_revision="0123456789abcdef0123456789abcdef01234567",
    )


class TestTaskRepository:
    def _make_repo(self) -> TaskRepository:
        return TaskRepository()

    def test_create_task(self) -> None:
        repo = self._make_repo()
        task = repo.create_task(
            _valid_request(),
            organization_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            repository_id="00000000-0000-0000-0000-000000000003",
            creator_id="00000000-0000-0000-0000-000000000004",
        )
        assert task.task_id
        assert task.title == "T"
        assert task.status_projection is None  # 实体不变；投影变更

    def test_create_task_rejects_dynamic_base_revision(self) -> None:
        """最新 main 等动态引用应被业务层拒。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TaskCreateRequest(
                title="T",
                description="D",
                workflow_template_id="wf",
                workflow_template_version="v1",
                base_revision="latest",
            )

    def test_get_task_404(self) -> None:
        repo = self._make_repo()
        with pytest.raises(TaskNotFoundError):
            repo.get_task("00000000-0000-0000-0000-000000000000")

    def test_list_tasks_pagination(self) -> None:
        repo = self._make_repo()
        for _ in range(5):
            repo.create_task(
                _valid_request(),
                organization_id="00000000-0000-0000-0000-000000000001",
                project_id="00000000-0000-0000-0000-000000000002",
                repository_id="00000000-0000-0000-0000-000000000003",
                creator_id="00000000-0000-0000-0000-000000000004",
            )
        page1, total = repo.list_tasks(limit=2, offset=0)
        assert total == 5
        assert len(page1) == 2
        page2, _ = repo.list_tasks(limit=2, offset=2)
        assert len(page2) == 2
        page3, _ = repo.list_tasks(limit=2, offset=4)
        assert len(page3) == 1

    def test_cancel_task(self) -> None:
        repo = self._make_repo()
        task = repo.create_task(
            _valid_request(),
            organization_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            repository_id="00000000-0000-0000-0000-000000000003",
            creator_id="00000000-0000-0000-0000-000000000004",
        )
        cancelled = repo.cancel_task(task.task_id, actor_id="user-1")
        assert cancelled is not None
        # 再查投影应是 CANCELLED
        _, proj = repo.get_task(task.task_id)
        assert proj.status == "CANCELLED"

    def test_cancel_already_terminal_raises(self) -> None:
        repo = self._make_repo()
        task = repo.create_task(
            _valid_request(),
            organization_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            repository_id="00000000-0000-0000-0000-000000000003",
            creator_id="00000000-0000-0000-0000-000000000004",
        )
        repo.cancel_task(task.task_id, actor_id="user-1")
        with pytest.raises(TaskAlreadyTerminalError):
            repo.cancel_task(task.task_id, actor_id="user-2")

    def test_cancel_missing_raises(self) -> None:
        repo = self._make_repo()
        with pytest.raises(TaskNotFoundError):
            repo.cancel_task("00000000-0000-0000-0000-000000000000", actor_id="x")
