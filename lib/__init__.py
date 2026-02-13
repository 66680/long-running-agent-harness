"""
lib - Long-Running Agent Harness 核心模块

提供状态机、文件锁、日志等基础设施。
"""

from .file_lock import TaskFileLock
from .state_machine import TaskStateMachine, TaskStatus
from .prompts import build_task_prompt
from .progress_logger import ProgressLogger

__all__ = [
    "TaskFileLock",
    "TaskStateMachine",
    "TaskStatus",
    "build_task_prompt",
    "ProgressLogger",
]
