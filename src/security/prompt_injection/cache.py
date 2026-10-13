"""
Prompt 注入检测缓存管理 - Task 2.3 Day 3

功能：
- LRU (Least Recently Used) 缓存
- 大小限制 (max 1000 条目)
- 内存限制 (可选)
- 线程安全 (可选锁定)
- TTL 过期 (可选)
- 统计指标 (命中率、命中数等)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheEntry(Generic[V]):
    """缓存条目"""

    value: V
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    ttl_seconds: Optional[float] = None

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl_seconds is None:
            return False
        return time.time() - self.timestamp > self.ttl_seconds

    def touch(self) -> None:
        """更新访问时间和计数"""
        self.timestamp = time.time()
        self.access_count += 1


@dataclass
class CacheStats:
    """缓存统计"""

    total_hits: int = 0
    total_misses: int = 0
    total_evictions: int = 0
    total_expirations: int = 0
    current_size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        """命中率"""
        total = self.total_hits + self.total_misses
        return self.total_hits / total if total > 0 else 0.0

    def __str__(self) -> str:
        """统计摘要"""
        return (
            f"Hits: {self.total_hits}, Misses: {self.total_misses}, "
            f"Rate: {self.hit_rate:.1%}, Size: {self.current_size}/{self.max_size}"
        )


class LRUCache(Generic[K, V]):
    """
    线程安全的 LRU 缓存

    特性：
    - 自动 LRU 驱逐
    - 大小限制
    - TTL 支持
    - 线程安全
    - 统计跟踪
    - 手动驱逐
    """

    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: Optional[float] = None,
        thread_safe: bool = True,
    ):
        """
        初始化 LRU 缓存

        Args:
            max_size: 最大条目数 (默认 1000)
            ttl_seconds: 条目 TTL (秒，None = 无过期)
            thread_safe: 是否启用线程安全 (使用锁定)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.thread_safe = thread_safe

        # 核心数据结构
        self._cache: dict[K, CacheEntry[V]] = {}
        self._access_order: list[K] = []  # 访问顺序（从旧到新）

        # 线程安全
        self._lock = threading.RLock() if thread_safe else None

        # 统计
        self.stats = CacheStats(max_size=max_size)

    def get(self, key: K) -> Optional[V]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在或过期返回 None
        """
        if self.thread_safe:
            with self._lock:
                return self._get_impl(key)
        else:
            return self._get_impl(key)

    def _get_impl(self, key: K) -> Optional[V]:
        """实现获取逻辑"""
        if key not in self._cache:
            self.stats.total_misses += 1
            return None

        entry = self._cache[key]

        # 检查过期
        if entry.is_expired():
            logger.debug(f"Cache entry expired: {key}")
            del self._cache[key]
            self._access_order.remove(key)
            self.stats.total_expirations += 1
            self.stats.current_size -= 1
            self.stats.total_misses += 1
            return None

        # 更新 LRU
        entry.touch()
        self._access_order.remove(key)
        self._access_order.append(key)

        self.stats.total_hits += 1
        return entry.value

    def put(self, key: K, value: V, ttl_seconds: Optional[float] = None) -> None:
        """
        放入缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl_seconds: 此条目的 TTL (None = 使用默认)
        """
        if self.thread_safe:
            with self._lock:
                self._put_impl(key, value, ttl_seconds)
        else:
            self._put_impl(key, value, ttl_seconds)

    def _put_impl(self, key: K, value: V, ttl_seconds: Optional[float]) -> None:
        """实现放入逻辑"""
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds

        # 如果键已存在，更新并重排序
        if key in self._cache:
            self._cache[key].value = value
            self._cache[key].timestamp = time.time()
            self._cache[key].ttl_seconds = ttl
            self._cache[key].access_count = 0
            self._access_order.remove(key)
            self._access_order.append(key)
            return

        # 如果缓存满，驱逐 LRU 条目
        if len(self._cache) >= self.max_size:
            self._evict_lru()

        # 添加新条目
        self._cache[key] = CacheEntry(value, ttl_seconds=ttl)
        self._access_order.append(key)
        self.stats.current_size += 1

    def _evict_lru(self) -> None:
        """驱逐最少最近使用的条目"""
        if not self._access_order:
            return

        lru_key = self._access_order.pop(0)
        del self._cache[lru_key]
        self.stats.total_evictions += 1
        self.stats.current_size -= 1

        logger.debug(f"LRU eviction: {lru_key}")

    def delete(self, key: K) -> bool:
        """
        删除缓存条目

        Args:
            key: 缓存键

        Returns:
            是否成功删除
        """
        if self.thread_safe:
            with self._lock:
                return self._delete_impl(key)
        else:
            return self._delete_impl(key)

    def _delete_impl(self, key: K) -> bool:
        """实现删除逻辑"""
        if key not in self._cache:
            return False

        del self._cache[key]
        self._access_order.remove(key)
        self.stats.current_size -= 1
        return True

    def clear(self) -> None:
        """清空缓存"""
        if self.thread_safe:
            with self._lock:
                self._clear_impl()
        else:
            self._clear_impl()

    def _clear_impl(self) -> None:
        """实现清空逻辑"""
        self._cache.clear()
        self._access_order.clear()
        self.stats.current_size = 0
        logger.debug("Cache cleared")

    def cleanup_expired(self) -> int:
        """
        清理过期条目

        Returns:
            清理的条目数
        """
        if self.thread_safe:
            with self._lock:
                return self._cleanup_expired_impl()
        else:
            return self._cleanup_expired_impl()

    def _cleanup_expired_impl(self) -> int:
        """实现过期清理逻辑"""
        expired_keys = [
            key for key, entry in self._cache.items() if entry.is_expired()
        ]

        for key in expired_keys:
            del self._cache[key]
            self._access_order.remove(key)
            self.stats.total_expirations += 1
            self.stats.current_size -= 1

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired entries")

        return len(expired_keys)

    def size(self) -> int:
        """获取当前缓存大小"""
        if self.thread_safe:
            with self._lock:
                return len(self._cache)
        else:
            return len(self._cache)

    def get_stats(self) -> CacheStats:
        """获取缓存统计"""
        if self.thread_safe:
            with self._lock:
                return CacheStats(
                    total_hits=self.stats.total_hits,
                    total_misses=self.stats.total_misses,
                    total_evictions=self.stats.total_evictions,
                    total_expirations=self.stats.total_expirations,
                    current_size=len(self._cache),
                    max_size=self.max_size,
                )
        else:
            return CacheStats(
                total_hits=self.stats.total_hits,
                total_misses=self.stats.total_misses,
                total_evictions=self.stats.total_evictions,
                total_expirations=self.stats.total_expirations,
                current_size=len(self._cache),
                max_size=self.max_size,
            )

    def reset_stats(self) -> None:
        """重置统计信息"""
        if self.thread_safe:
            with self._lock:
                self.stats = CacheStats(max_size=self.max_size)
        else:
            self.stats = CacheStats(max_size=self.max_size)

    def __contains__(self, key: K) -> bool:
        """检查键是否存在（且未过期）"""
        if self.thread_safe:
            with self._lock:
                return self._contains_impl(key)
        else:
            return self._contains_impl(key)

    def _contains_impl(self, key: K) -> bool:
        """实现包含检查逻辑"""
        if key not in self._cache:
            return False
        if self._cache[key].is_expired():
            return False
        return True

    def __len__(self) -> int:
        """获取缓存大小"""
        return self.size()

    def __repr__(self) -> str:
        """缓存表示"""
        return (
            f"LRUCache(size={len(self._cache)}/{self.max_size}, "
            f"hits={self.stats.total_hits}, "
            f"misses={self.stats.total_misses})"
        )
