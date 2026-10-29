"""Exercise event querying against the actual runtime store contract."""

from datetime import UTC, datetime, timedelta

import pytest

from src.runtime.event_store.envelope import EventEnvelope
from src.runtime.event_store.store import InMemoryEventStore
from src.runtime.query.access_control import UserContext
from src.runtime.query.event_query import EventQueryRequest, EventQueryService

pytestmark = pytest.mark.asyncio


async def populated_store(count=6, **scope):
    store = InMemoryEventStore()
    for index in range(count):
        await store.append(EventEnvelope(
            event_id=f"event-{index}",
            event_type="TestEvent",
            payload_schema="TestEvent.v1",
            task_id="task",
            organization_id=scope.get("organization_id", "org"),
            project_id=scope.get("project_id", "project"),
            repository_id=scope.get("repository_id", "repo"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            payload={"message": f"message-{index}", "api_key": "test-secret"},
        ))
    return store


async def query(store, **options):
    return await EventQueryService(store).query_events(
        UserContext(user_id="user", organization_id="org", roles=["DEVELOPER"]),
        EventQueryRequest(task_id="task", **options),
        task_org_id="org",
        task_project_id="project",
        task_repo_id="repo",
    )


async def test_real_store_pagination_and_time_filter():
    store = await populated_store()
    events, total = await query(
        store, page=2, limit=2,
        occurred_after=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        occurred_before=datetime(2026, 1, 1, 0, 0, 4, tzinfo=UTC),
    )
    assert total == 4
    assert [event.event_id for event in events] == ["event-3", "event-4"]
    assert all(event.payload == {} for event in events)


async def test_query_crosses_store_default_limit_without_losing_total():
    events, total = await query(await populated_store(1003), page=501, limit=2)
    assert total == 1003
    assert [event.event_id for event in events] == ["event-1000", "event-1001"]


@pytest.mark.parametrize("scope", ["organization_id", "project_id", "repository_id"])
async def test_caller_supplied_scope_cannot_expose_other_tenants_events(scope):
    store = await populated_store(**{scope: "other"})
    with pytest.raises(PermissionError, match="scope"):
        await query(store, include_payload=True)


@pytest.mark.parametrize("options", [
    {"page": 0}, {"page": -1}, {"limit": 0}, {"limit": 1001},
    {"occurred_after": datetime(2026, 1, 1)},
    {"occurred_before": datetime(2026, 1, 1)},
    {
        "occurred_after": datetime(2026, 2, 1, tzinfo=UTC),
        "occurred_before": datetime(2026, 1, 1, tzinfo=UTC),
    },
])
async def test_invalid_query_parameters_are_rejected(options):
    with pytest.raises(ValueError):
        await query(await populated_store(), **options)


async def test_empty_store_and_page_past_end():
    assert await query(InMemoryEventStore()) == ([], 0)
    assert await query(await populated_store(), page=10) == ([], 6)


async def test_storage_failure_preserves_cause():
    class BrokenStore(InMemoryEventStore):
        async def query(self, *args, **kwargs):
            raise OSError("storage offline")

    with pytest.raises(ValueError, match="Failed to query events") as error:
        await query(BrokenStore())
    assert isinstance(error.value.__cause__, OSError)


async def test_snapshot_excludes_events_appended_after_latest_sequence_read():
    class AppendingStore(InMemoryEventStore):
        async def get_latest_sequence(self, task_id):
            latest = await super().get_latest_sequence(task_id)
            await self.append(EventEnvelope(
                event_type="TestEvent", payload_schema="TestEvent.v1", payload={},
                task_id=task_id, organization_id="org", project_id="project",
                repository_id="repo",
            ))
            return latest

    store = AppendingStore()
    assert await query(store) == ([], 0)
    assert await store.count("task") == 1
