"""测试采样策略。"""

from src.runtime.trace.sampling import SamplingPriority, SamplingStrategy


class TestSamplingStrategy:
    """测试 SamplingStrategy（REQ-RT-006 §5.4）。"""

    def test_default_sampling_rate(self) -> None:
        """测试默认采样率为 15%。"""
        assert SamplingStrategy.DEFAULT_SAMPLING_RATE == 0.15

    def test_get_sampler_default(self) -> None:
        """测试获取默认采样器（15%）。"""
        sampler = SamplingStrategy.get_sampler()
        assert sampler is not None
        # 默认是 ParentBased 包装的 TraceIdRatioBased

    def test_get_sampler_high_priority(self) -> None:
        """测试获取高优先级采样器（100%）。"""
        sampler = SamplingStrategy.get_sampler(SamplingPriority.HIGH)
        assert sampler is not None
        # 应该包含 ALWAYS_ON

    def test_get_sampler_disabled(self) -> None:
        """测试获取禁用采样器（0%）。"""
        sampler = SamplingStrategy.get_sampler(SamplingPriority.DISABLED)
        assert sampler is not None
        # 应该包含 ALWAYS_OFF

    def test_get_sampler_custom_rate(self) -> None:
        """测试自定义采样率。"""
        sampler = SamplingStrategy.get_sampler(custom_rate=0.5)
        assert sampler is not None

    def test_custom_rate_out_of_range(self) -> None:
        """测试自定义采样率超出范围。"""
        import pytest

        with pytest.raises(ValueError, match="采样率必须在 0.0-1.0 范围内"):
            SamplingStrategy.get_sampler(custom_rate=1.5)

        with pytest.raises(ValueError, match="采样率必须在 0.0-1.0 范围内"):
            SamplingStrategy.get_sampler(custom_rate=-0.1)

    def test_should_sample_task_default(self) -> None:
        """测试默认任务采样优先级。"""
        priority = SamplingStrategy.should_sample_task()
        assert priority == SamplingPriority.DEFAULT

    def test_should_sample_task_high_risk(self) -> None:
        """测试高风险任务采样优先级（REQ-RT-006 §5.4）。"""
        priority = SamplingStrategy.should_sample_task(is_high_risk=True)
        assert priority == SamplingPriority.HIGH

    def test_should_sample_task_has_failure(self) -> None:
        """测试包含失败的任务采样优先级。"""
        priority = SamplingStrategy.should_sample_task(has_failure=True)
        assert priority == SamplingPriority.HIGH

    def test_should_sample_task_is_recovery(self) -> None:
        """测试恢复操作采样优先级。"""
        priority = SamplingStrategy.should_sample_task(is_recovery=True)
        assert priority == SamplingPriority.HIGH

    def test_should_sample_task_explicit_request(self) -> None:
        """测试显式诊断请求采样优先级。"""
        priority = SamplingStrategy.should_sample_task(explicit_request=True)
        assert priority == SamplingPriority.HIGH

    def test_should_sample_task_multiple_conditions(self) -> None:
        """测试多个条件同时满足时采样优先级。"""
        priority = SamplingStrategy.should_sample_task(
            is_high_risk=True,
            has_failure=True,
            is_recovery=True,
        )
        assert priority == SamplingPriority.HIGH
