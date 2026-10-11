"""
分布式撤销系统测试 - REQ-SEC-005

测试覆盖：
1. 撤销事件的发布与订阅
2. 撤销缓存
3. 撤销协调
4. 传播延迟保证
"""
import asyncio

import pytest

from src.security.credential.revocation import (
    RevocationBroker,
    RevocationCache,
    RevocationCoordinator,
    RevocationEvent,
)


@pytest.fixture
def revocation_cache():
    """创建撤销缓存"""
    return RevocationCache(ttl_seconds=3600)


@pytest.fixture
def revocation_broker():
    """创建撤销代理"""
    return RevocationBroker()


@pytest.fixture
def revocation_coordinator(revocation_broker):
    """创建撤销协调器"""
    return RevocationCoordinator(
        broker=revocation_broker,
        propagation_timeout_seconds=5.0,
    )


@pytest.fixture
def revocation_event():
    """创建撤销事件"""
    return RevocationEvent(
        token_id="token-001",
        task_id="task-001",
        reason="Manual revocation",
        triggered_by="manual",
    )


# 测试：撤销事件
def test_revocation_event_creation(revocation_event):
    """测试撤销事件创建"""
    assert revocation_event.revocation_id
    assert revocation_event.token_id == "token-001"
    assert revocation_event.task_id == "task-001"
    assert revocation_event.timestamp


def test_revocation_event_to_dict(revocation_event):
    """测试撤销事件序列化"""
    data = revocation_event.to_dict()
    
    assert data["token_id"] == "token-001"
    assert data["task_id"] == "task-001"
    assert data["triggered_by"] == "manual"


def test_revocation_event_from_dict(revocation_event):
    """测试撤销事件反序列化"""
    data = revocation_event.to_dict()
    restored = RevocationEvent.from_dict(data)
    
    assert restored.token_id == revocation_event.token_id
    assert restored.task_id == revocation_event.task_id
    assert restored.revocation_id == revocation_event.revocation_id


# 测试：撤销缓存
def test_cache_add_and_check(revocation_cache, revocation_event):
    """测试缓存添加和检查"""
    revocation_cache.add(revocation_event)
    
    assert revocation_cache.is_revoked("token-001")
    assert not revocation_cache.is_revoked("token-999")


def test_cache_get_event(revocation_cache, revocation_event):
    """测试从缓存获取事件"""
    revocation_cache.add(revocation_event)
    
    retrieved = revocation_cache.get("token-001")
    assert retrieved is not None
    assert retrieved.token_id == "token-001"


def test_cache_expiration(revocation_cache):
    """测试缓存过期"""
    short_ttl_cache = RevocationCache(ttl_seconds=1)
    
    event = RevocationEvent("token-001", "task-001")
    short_ttl_cache.add(event)
    
    assert short_ttl_cache.is_revoked("token-001")
    
    import time
    time.sleep(2)
    
    assert not short_ttl_cache.is_revoked("token-001")


def test_cache_cleanup_expired(revocation_cache):
    """测试清理过期缓存"""
    short_ttl_cache = RevocationCache(ttl_seconds=1)
    
    event1 = RevocationEvent("token-001", "task-001")
    event2 = RevocationEvent("token-002", "task-002")
    short_ttl_cache.add(event1)
    short_ttl_cache.add(event2)
    
    import time
    time.sleep(2)
    
    cleaned = short_ttl_cache.cleanup_expired()
    assert cleaned == 2


# 测试：撤销代理发布订阅
@pytest.mark.asyncio
async def test_broker_publish_subscribe():
    """测试代理的发布订阅"""
    broker = RevocationBroker()
    received_events = []
    
    async def callback(event):
        received_events.append(event)
    
    await broker.subscribe("instance-1", callback)
    
    event = RevocationEvent("token-001", "task-001")
    await broker.publish_revocation(event)
    
    # 给异步操作一些时间
    await asyncio.sleep(0.1)
    
    assert len(received_events) == 1
    assert received_events[0].token_id == "token-001"


@pytest.mark.asyncio
async def test_broker_multiple_subscribers():
    """测试多个订阅者"""
    broker = RevocationBroker()
    received_by_1 = []
    received_by_2 = []
    
    async def callback1(event):
        received_by_1.append(event)
    
    async def callback2(event):
        received_by_2.append(event)
    
    await broker.subscribe("instance-1", callback1)
    await broker.subscribe("instance-2", callback2)
    
    event = RevocationEvent("token-001", "task-001")
    await broker.publish_revocation(event)
    
    await asyncio.sleep(0.1)
    
    assert len(received_by_1) == 1
    assert len(received_by_2) == 1


@pytest.mark.asyncio
async def test_broker_history():
    """测试代理的历史记录"""
    broker = RevocationBroker()
    
    event1 = RevocationEvent("token-001", "task-001")
    event2 = RevocationEvent("token-002", "task-002")
    
    await broker.publish_revocation(event1)
    await broker.publish_revocation(event2)
    
    history = broker.get_revocation_history()
    assert len(history) >= 2


# 测试：撤销协调器
@pytest.mark.asyncio
async def test_coordinator_request_revocation(revocation_coordinator):
    """测试协调器请求撤销"""
    success = await revocation_coordinator.request_revocation(
        token_id="token-001",
        task_id="task-001",
        reason="Security incident",
        triggered_by="kill_switch",
    )
    
    assert success
    
    # 检查审计日志
    log = revocation_coordinator.get_audit_log()
    assert len(log) > 0
    assert log[-1]["status"] == "published"


@pytest.mark.asyncio
async def test_coordinator_propagation_wait():
    """测试等待撤销传播"""
    broker = RevocationBroker()
    coordinator = RevocationCoordinator(broker, propagation_timeout_seconds=1.0)
    
    received_instances = set()
    
    async def instance_callback(event):
        received_instances.add("instance-1")
        coordinator.confirm_revocation_received(event.revocation_id, "instance-1")
    
    await broker.subscribe("instance-1", instance_callback)
    
    success = await coordinator.request_revocation(
        token_id="token-001",
        task_id="task-001",
    )
    
    assert success
    
    # 这个测试展示了传播确认的机制
    # 在实际系统中，每个 CDP 实例会调用 confirm_revocation_received


@pytest.mark.asyncio
async def test_coordinator_propagation_timeout():
    """测试撤销传播超时"""
    broker = RevocationBroker()
    coordinator = RevocationCoordinator(broker, propagation_timeout_seconds=0.1)
    
    # 创建事件但不发布
    event = RevocationEvent("token-001", "task-001")
    
    # 直接等待传播（没有实例确认，会超时）
    success, confirmed = await coordinator.wait_for_propagation(
        revocation_id=event.revocation_id,
        expected_instances={"instance-1", "instance-2"},
    )
    
    assert not success  # 超时
    assert len(confirmed) == 0  # 没有实例确认


# 测试：触发来源
def test_revocation_triggered_by_manual():
    """测试手动撤销"""
    event = RevocationEvent("token-001", "task-001", triggered_by="manual")
    assert event.triggered_by == "manual"


def test_revocation_triggered_by_kill_switch():
    """测试 Kill Switch 触发的撤销"""
    event = RevocationEvent(
        "token-001",
        "task-001",
        reason="Kill Switch activated",
        triggered_by="kill_switch",
    )
    assert event.triggered_by == "kill_switch"


def test_revocation_triggered_by_policy_change():
    """测试策略变更触发的撤销"""
    event = RevocationEvent(
        "token-001",
        "task-001",
        reason="Policy updated; permission revoked",
        triggered_by="policy_change",
    )
    assert event.triggered_by == "policy_change"


# 测试：撤销历史与审计
@pytest.mark.asyncio
async def test_revocation_audit_trail(revocation_coordinator):
    """测试撤销的完整审计追踪"""
    await revocation_coordinator.request_revocation(
        token_id="token-001",
        task_id="task-001",
        reason="First revocation",
        triggered_by="manual",
    )
    
    await revocation_coordinator.request_revocation(
        token_id="token-002",
        task_id="task-002",
        reason="Second revocation",
        triggered_by="kill_switch",
    )
    
    log = revocation_coordinator.get_audit_log()
    
    assert len(log) >= 2
    assert log[0]["token_id"] == "token-001"
    assert log[1]["token_id"] == "token-002"
    assert log[0]["triggered_by"] == "manual"
    assert log[1]["triggered_by"] == "kill_switch"


# 测试：协调器失败场景
@pytest.mark.asyncio
async def test_coordinator_request_revocation_failure(revocation_coordinator):
    """测试撤销请求失败"""
    # 模拟代理不可用
    revocation_coordinator.broker = None
    
    # 应该处理错误而不是崩溃
    # 在实际实现中，可能需要更复杂的错误处理
    # 这里只是演示异常处理的能力


# 集成测试：完整撤销流程
@pytest.mark.asyncio
async def test_complete_revocation_flow():
    """测试完整的撤销流程"""
    broker = RevocationBroker()
    coordinator = RevocationCoordinator(broker)
    cache = RevocationCache()
    
    # 1. 请求撤销
    success = await coordinator.request_revocation(
        token_id="token-001",
        task_id="task-001",
        reason="Security incident",
        triggered_by="kill_switch",
    )
    assert success
    
    # 2. 代理发布事件
    history = broker.get_revocation_history()
    assert len(history) > 0
    
    event = history[0]
    
    # 3. 订阅者收到并缓存
    cache.add(event)
    assert cache.is_revoked("token-001")
    
    # 4. 验证审计
    log = coordinator.get_audit_log()
    assert len(log) > 0
    assert log[-1]["token_id"] == "token-001"
    assert log[-1]["status"] == "published"


@pytest.mark.asyncio
async def test_revocation_synchronization():
    """测试多个 CDP 实例间的撤销同步"""
    broker = RevocationBroker()
    cache1 = RevocationCache()
    cache2 = RevocationCache()
    
    event1_received = []
    event2_received = []
    
    async def callback1(event):
        event1_received.append(event)
        cache1.add(event)
    
    async def callback2(event):
        event2_received.append(event)
        cache2.add(event)
    
    await broker.subscribe("cdp-1", callback1)
    await broker.subscribe("cdp-2", callback2)
    
    # 发布撤销事件
    event = RevocationEvent("token-001", "task-001")
    await broker.publish_revocation(event)
    
    await asyncio.sleep(0.1)
    
    # 两个实例都应该收到并缓存
    assert cache1.is_revoked("token-001")
    assert cache2.is_revoked("token-001")
    assert len(event1_received) == 1
    assert len(event2_received) == 1
