"""
LRU 缓存测试 - Task 2.3 Day 3
"""
import threading
import time

import pytest

from src.security.prompt_injection.cache import LRUCache


class TestLRUCache:
    """LRU 缓存测试"""

    @pytest.fixture
    def cache(self):
        """创建缓存实例"""
        return LRUCache(max_size=5)

    # ===== 基本操作 =====
    @pytest.mark.asyncio
    async def test_put_and_get(self, cache):
        """测试放入和获取"""
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, cache):
        """测试获取不存在的键"""
        assert cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        """测试删除"""
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        assert cache.delete("key1") is False

    @pytest.mark.asyncio
    async def test_clear(self, cache):
        """测试清空"""
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0
        assert cache.get("key1") is None

    # ===== LRU 驱逐 =====
    @pytest.mark.asyncio
    async def test_lru_eviction_on_overflow(self, cache):
        """测试 LRU 驱逐（满时自动驱逐最旧）"""
        # 填满缓存
        for i in range(5):
            cache.put(f"key{i}", f"value{i}")

        assert cache.size() == 5
        assert cache.stats.total_evictions == 0

        # 添加第 6 项，应该驱逐 key0
        cache.put("key5", "value5")
        assert cache.size() == 5
        assert cache.stats.total_evictions == 1

        # key0 应该被驱逐
        assert cache.get("key0") is None
        # key1-5 应该仍在
        for i in range(1, 6):
            assert cache.get(f"key{i}") is not None

    @pytest.mark.asyncio
    async def test_lru_eviction_respects_access_order(self, cache):
        """测试 LRU 驱逐遵循访问顺序"""
        # 填满缓存
        for i in range(5):
            cache.put(f"key{i}", f"value{i}")

        # 访问 key0，更新其为最新
        cache.get("key0")

        # 添加新项，应该驱逐 key1 (最旧的未访问)
        cache.put("key5", "value5")

        assert cache.get("key0") is not None  # 仍在
        assert cache.get("key1") is None      # 被驱逐

    # ===== TTL 过期 =====
    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache):
        """测试 TTL 过期"""
        cache.put("key1", "value1", ttl_seconds=0.1)

        # 立即获取应该成功
        assert cache.get("key1") == "value1"

        # 等待过期
        time.sleep(0.2)

        # 获取应该失败
        assert cache.get("key1") is None
        assert cache.stats.total_expirations == 1

    @pytest.mark.asyncio
    async def test_global_ttl_setting(self):
        """测试全局 TTL 设置"""
        cache = LRUCache(max_size=5, ttl_seconds=0.1)

        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

        time.sleep(0.2)
        assert cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_entries(self, cache):
        """测试清理过期条目"""
        cache.put("key1", "value1", ttl_seconds=0.1)
        cache.put("key2", "value2")

        assert cache.size() == 2

        time.sleep(0.2)

        cleaned = cache.cleanup_expired()
        assert cleaned == 1
        assert cache.size() == 1
        assert cache.get("key2") == "value2"

    # ===== 统计 =====
    @pytest.mark.asyncio
    async def test_cache_stats_hits_and_misses(self, cache):
        """测试命中和未命中统计"""
        cache.put("key1", "value1")

        # 命中
        cache.get("key1")
        assert cache.stats.total_hits == 1
        assert cache.stats.total_misses == 0

        # 未命中
        cache.get("nonexistent")
        assert cache.stats.total_hits == 1
        assert cache.stats.total_misses == 1

    @pytest.mark.asyncio
    async def test_cache_stats_hit_rate(self, cache):
        """测试命中率计算"""
        cache.put("key1", "value1")

        # 3 次命中，2 次未命中
        cache.get("key1")
        cache.get("key1")
        cache.get("key1")
        cache.get("nonexistent1")
        cache.get("nonexistent2")

        assert cache.stats.hit_rate == 0.6  # 3/5

    @pytest.mark.asyncio
    async def test_cache_stats_evictions(self, cache):
        """测试驱逐统计"""
        for i in range(5):
            cache.put(f"key{i}", f"value{i}")

        assert cache.stats.total_evictions == 0

        for i in range(5, 10):
            cache.put(f"key{i}", f"value{i}")

        assert cache.stats.total_evictions == 5

    @pytest.mark.asyncio
    async def test_reset_stats(self, cache):
        """测试重置统计"""
        cache.put("key1", "value1")
        cache.get("key1")
        cache.get("nonexistent")

        assert cache.stats.total_hits == 1
        assert cache.stats.total_misses == 1

        cache.reset_stats()
        assert cache.stats.total_hits == 0
        assert cache.stats.total_misses == 0

    # ===== 线程安全 =====
    @pytest.mark.asyncio
    async def test_thread_safe_concurrent_access(self):
        """测试线程安全的并发访问"""
        cache = LRUCache(max_size=100, thread_safe=True)
        results = []

        def worker(thread_id):
            for i in range(10):
                key = f"thread{thread_id}_key{i}"
                cache.put(key, f"value{i}")
                value = cache.get(key)
                if value is not None:
                    results.append((thread_id, i, True))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有线程的操作应该成功
        assert len(results) == 50  # 5 threads * 10 ops
        assert cache.size() == 50

    @pytest.mark.asyncio
    async def test_thread_safe_concurrent_eviction(self):
        """测试线程安全的并发驱逐"""
        cache = LRUCache(max_size=10, thread_safe=True)

        def worker(thread_id):
            for i in range(20):
                cache.put(f"thread{thread_id}_{i}", f"value{i}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 缓存大小应该不超过最大值
        assert cache.size() <= 10
        # 应该有驱逐
        assert cache.stats.total_evictions > 0

    # ===== 容器接口 =====
    @pytest.mark.asyncio
    async def test_contains_operator(self, cache):
        """测试 in 操作符"""
        cache.put("key1", "value1")

        assert "key1" in cache
        assert "key2" not in cache

    @pytest.mark.asyncio
    async def test_len_operator(self, cache):
        """测试 len 操作符"""
        assert len(cache) == 0

        cache.put("key1", "value1")
        assert len(cache) == 1

        cache.put("key2", "value2")
        assert len(cache) == 2

    @pytest.mark.asyncio
    async def test_repr(self, cache):
        """测试字符串表示"""
        cache.put("key1", "value1")
        repr_str = repr(cache)

        assert "LRUCache" in repr_str
        assert "size=" in repr_str

    # ===== 性能基准 =====
    @pytest.mark.asyncio
    async def test_cache_access_performance(self, cache):
        """测试缓存访问性能"""
        # 预填充
        for i in range(100):
            cache.put(f"key{i}", f"value{i}")

        # 测量缓存命中延迟
        start = time.perf_counter()
        for _ in range(1000):
            cache.get("key0")
        elapsed = time.perf_counter() - start

        # 平均每次访问 < 0.1ms (1000 次共 < 100ms)
        avg_time = elapsed / 1000
        assert avg_time < 0.0001, f"Cache access too slow: {avg_time*1000:.4f}ms"

    @pytest.mark.asyncio
    async def test_cache_insertion_performance(self, cache):
        """测试缓存插入性能"""
        start = time.perf_counter()
        for i in range(100):
            cache.put(f"key{i}", f"value{i}")
        elapsed = time.perf_counter() - start

        # 平均每次插入 < 0.1ms (100 次共 < 10ms)
        avg_time = elapsed / 100
        assert avg_time < 0.0001, f"Cache insertion too slow: {avg_time*1000:.4f}ms"
