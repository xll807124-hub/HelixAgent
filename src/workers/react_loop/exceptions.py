"""
ReAct Loop 异常定义

对齐：src/tools/base.py 的异常设计风格
"""


class ReActLoopException(Exception):
    """ReAct Loop 基础异常"""
    pass


class ReActLoopStateError(ReActLoopException):
    """状态转移异常"""
    pass


class ReActLoopTimeoutError(ReActLoopException):
    """超时异常"""
    pass


class ReActLoopBudgetExceededError(ReActLoopException):
    """预算超支异常（Token、时间或成本）"""
    pass


class ReActLoopIterationError(ReActLoopException):
    """迭代失败异常"""
    pass


class ReActLoopCheckpointError(ReActLoopException):
    """Checkpoint 操作异常"""
    pass


class ReActLoopCancelledException(ReActLoopException):
    """循环被取消"""
    pass
