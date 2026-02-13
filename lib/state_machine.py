"""
state_machine.py - 任务状态机 + 转移规则

实现严格的状态转移规则，确保：
- completed 必须有 verify 证据
- 同一时间最多一个有效 lease
- 子进程回传 run_id 必须匹配
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELED = "canceled"
    ABANDONED = "abandoned"


# 状态转移规则
VALID_TRANSITIONS = {
    TaskStatus.PENDING: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELED},
    TaskStatus.IN_PROGRESS: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.BLOCKED,
        TaskStatus.ABANDONED,
    },
    TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.CANCELED},
    TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.CANCELED},
    TaskStatus.ABANDONED: {TaskStatus.PENDING, TaskStatus.CANCELED},
    TaskStatus.COMPLETED: set(),  # 终态，不可转移
    TaskStatus.CANCELED: set(),   # 终态，不可转移
}


@dataclass
class Claim:
    """任务领取信息"""
    claimed_by: str
    run_id: str
    claimed_at: str
    lease_expires_at: str
    attempt: int = 1

    def to_dict(self) -> dict:
        return {
            "claimed_by": self.claimed_by,
            "run_id": self.run_id,
            "claimed_at": self.claimed_at,
            "lease_expires_at": self.lease_expires_at,
            "attempt": self.attempt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Claim":
        return cls(
            claimed_by=data["claimed_by"],
            run_id=data["run_id"],
            claimed_at=data["claimed_at"],
            lease_expires_at=data["lease_expires_at"],
            attempt=data.get("attempt", 1),
        )

    def is_expired(self) -> bool:
        """检查租约是否过期"""
        expires = datetime.fromisoformat(self.lease_expires_at)
        now = datetime.now(timezone.utc)
        return now > expires


@dataclass
class VerifyResult:
    """验证结果"""
    command: str
    exit_code: int
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VerifyResult":
        return cls(
            command=data.get("command", ""),
            exit_code=data.get("exit_code", -1),
            evidence=data.get("evidence", ""),
        )


@dataclass
class GitResult:
    """Git 提交结果"""
    commit: str
    branch: str = "main"

    def to_dict(self) -> dict:
        return {"commit": self.commit, "branch": self.branch}

    @classmethod
    def from_dict(cls, data: dict) -> "GitResult":
        return cls(
            commit=data.get("commit", ""),
            branch=data.get("branch", "main"),
        )


@dataclass
class TaskResult:
    """任务执行结果"""
    verify: Optional[VerifyResult] = None
    git: Optional[GitResult] = None
    summary: str = ""

    def to_dict(self) -> dict:
        result = {"summary": self.summary}
        if self.verify:
            result["verify"] = self.verify.to_dict()
        if self.git:
            result["git"] = self.git.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "TaskResult":
        verify = None
        git = None
        if "verify" in data:
            verify = VerifyResult.from_dict(data["verify"])
        if "git" in data:
            git = GitResult.from_dict(data["git"])
        return cls(
            verify=verify,
            git=git,
            summary=data.get("summary", ""),
        )


@dataclass
class HistoryEntry:
    """历史记录条目"""
    attempt: int
    run_id: str
    status: str
    timestamp: str
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "run_id": self.run_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryEntry":
        return cls(
            attempt=data["attempt"],
            run_id=data["run_id"],
            status=data["status"],
            timestamp=data["timestamp"],
            error=data.get("error", ""),
        )


class TaskStateMachine:
    """
    任务状态机。

    管理任务状态转移，确保不变式：
    1. completed 必须有 verify.exit_code == 0
    2. 同一时间最多一个有效 lease
    3. 子进程回传 run_id 必须匹配
    """

    def __init__(self, config: Optional[dict] = None):
        """
        初始化状态机。

        Args:
            config: 配置字典，包含 lease_ttl_seconds, max_attempts, verify_required
        """
        self.config = config or {
            "lease_ttl_seconds": 900,
            "max_attempts": 3,
            "verify_required": True,
        }

    def generate_run_id(self) -> str:
        """生成唯一的运行 ID"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique = uuid.uuid4().hex[:8]
        return f"run-{timestamp}-{unique}"

    def generate_runner_id(self) -> str:
        """生成运行器 ID"""
        import os
        return f"runner-pid-{os.getpid()}"

    def can_transition(self, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        """检查状态转移是否合法"""
        return to_status in VALID_TRANSITIONS.get(from_status, set())

    def claim_task(
        self,
        task: dict,
        run_id: str,
        runner_id: Optional[str] = None,
    ) -> dict:
        """
        领取任务（pending -> in_progress）。

        Args:
            task: 任务字典
            run_id: 运行 ID
            runner_id: 运行器 ID（可选，默认自动生成）

        Returns:
            更新后的任务字典

        Raises:
            ValueError: 状态转移不合法或已有有效 lease
        """
        current_status = TaskStatus(task.get("status", "pending"))

        # 检查状态
        if current_status != TaskStatus.PENDING:
            raise ValueError(f"只能领取 pending 状态的任务，当前状态: {current_status}")

        # 检查是否有未过期的 lease
        if "claim" in task and task["claim"]:
            claim = Claim.from_dict(task["claim"])
            if not claim.is_expired():
                raise ValueError(f"任务已被领取，lease 未过期: {claim.run_id}")

        # 计算 lease 过期时间
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.config["lease_ttl_seconds"])

        # 获取尝试次数
        attempt = 1
        if "history" in task and task["history"]:
            attempt = len(task["history"]) + 1

        # 创建 claim
        claim = Claim(
            claimed_by=runner_id or self.generate_runner_id(),
            run_id=run_id,
            claimed_at=now.isoformat(),
            lease_expires_at=expires.isoformat(),
            attempt=attempt,
        )

        # 更新任务
        task = {**task}  # 不可变更新
        task["status"] = TaskStatus.IN_PROGRESS.value
        task["claim"] = claim.to_dict()
        task["last_update"] = now.isoformat()

        return task

    def complete_task(
        self,
        task: dict,
        run_id: str,
        verify: VerifyResult,
        git: Optional[GitResult] = None,
        summary: str = "",
    ) -> dict:
        """
        完成任务（in_progress -> completed）。

        Args:
            task: 任务字典
            run_id: 运行 ID（必须匹配 claim.run_id）
            verify: 验证结果
            git: Git 提交结果
            summary: 任务摘要

        Returns:
            更新后的任务字典

        Raises:
            ValueError: 状态转移不合法、run_id 不匹配或 verify 失败
        """
        current_status = TaskStatus(task.get("status", "pending"))

        # 检查状态
        if current_status != TaskStatus.IN_PROGRESS:
            raise ValueError(f"只能完成 in_progress 状态的任务，当前状态: {current_status}")

        # 检查 run_id 匹配
        claim = task.get("claim")
        if not claim:
            raise ValueError("任务没有 claim 信息")
        if claim["run_id"] != run_id:
            raise ValueError(f"run_id 不匹配: 期望 {claim['run_id']}，实际 {run_id}")

        # 检查 verify
        if self.config["verify_required"] and verify.exit_code != 0:
            raise ValueError(f"verify 失败: exit_code={verify.exit_code}")

        now = datetime.now(timezone.utc)

        # 创建结果
        result = TaskResult(verify=verify, git=git, summary=summary)

        # 添加历史记录
        history = list(task.get("history", []))
        history.append(HistoryEntry(
            attempt=claim["attempt"],
            run_id=run_id,
            status="completed",
            timestamp=now.isoformat(),
        ).to_dict())

        # 更新任务
        task = {**task}
        task["status"] = TaskStatus.COMPLETED.value
        task["result"] = result.to_dict()
        task["history"] = history
        task["last_update"] = now.isoformat()
        task["claim"] = None  # 清除 claim

        return task

    def fail_task(
        self,
        task: dict,
        run_id: str,
        error: str,
        verify: Optional[VerifyResult] = None,
    ) -> dict:
        """
        标记任务失败（in_progress -> failed）。

        Args:
            task: 任务字典
            run_id: 运行 ID
            error: 错误信息
            verify: 验证结果（可选）

        Returns:
            更新后的任务字典
        """
        current_status = TaskStatus(task.get("status", "pending"))

        if current_status != TaskStatus.IN_PROGRESS:
            raise ValueError(f"只能标记 in_progress 状态的任务为失败，当前状态: {current_status}")

        claim = task.get("claim")
        if not claim:
            raise ValueError("任务没有 claim 信息")
        if claim["run_id"] != run_id:
            raise ValueError(f"run_id 不匹配: 期望 {claim['run_id']}，实际 {run_id}")

        now = datetime.now(timezone.utc)

        # 添加历史记录
        history = list(task.get("history", []))
        history.append(HistoryEntry(
            attempt=claim["attempt"],
            run_id=run_id,
            status="failed",
            timestamp=now.isoformat(),
            error=error,
        ).to_dict())

        # 更新任务
        task = {**task}
        task["status"] = TaskStatus.FAILED.value
        task["history"] = history
        task["last_update"] = now.isoformat()
        task["notes"] = error
        task["claim"] = None

        # 如果有 verify 结果，保存
        if verify:
            task["result"] = {"verify": verify.to_dict(), "summary": error}

        return task

    def block_task(
        self,
        task: dict,
        run_id: str,
        reason: str,
    ) -> dict:
        """
        标记任务阻塞（in_progress -> blocked）。

        Args:
            task: 任务字典
            run_id: 运行 ID
            reason: 阻塞原因

        Returns:
            更新后的任务字典
        """
        current_status = TaskStatus(task.get("status", "pending"))

        if current_status != TaskStatus.IN_PROGRESS:
            raise ValueError(f"只能标记 in_progress 状态的任务为阻塞，当前状态: {current_status}")

        claim = task.get("claim")
        if not claim:
            raise ValueError("任务没有 claim 信息")
        if claim["run_id"] != run_id:
            raise ValueError(f"run_id 不匹配: 期望 {claim['run_id']}，实际 {run_id}")

        now = datetime.now(timezone.utc)

        # 添加历史记录
        history = list(task.get("history", []))
        history.append(HistoryEntry(
            attempt=claim["attempt"],
            run_id=run_id,
            status="blocked",
            timestamp=now.isoformat(),
            error=reason,
        ).to_dict())

        # 更新任务
        task = {**task}
        task["status"] = TaskStatus.BLOCKED.value
        task["history"] = history
        task["last_update"] = now.isoformat()
        task["notes"] = reason
        task["claim"] = None

        return task

    def abandon_task(self, task: dict, reason: str = "lease expired") -> dict:
        """
        放弃任务（in_progress -> abandoned，用于租约过期回收）。

        Args:
            task: 任务字典
            reason: 放弃原因

        Returns:
            更新后的任务字典
        """
        current_status = TaskStatus(task.get("status", "pending"))

        if current_status != TaskStatus.IN_PROGRESS:
            raise ValueError(f"只能放弃 in_progress 状态的任务，当前状态: {current_status}")

        claim = task.get("claim")
        now = datetime.now(timezone.utc)

        # 添加历史记录
        history = list(task.get("history", []))
        if claim:
            history.append(HistoryEntry(
                attempt=claim.get("attempt", 1),
                run_id=claim.get("run_id", "unknown"),
                status="abandoned",
                timestamp=now.isoformat(),
                error=reason,
            ).to_dict())

        # 更新任务
        task = {**task}
        task["status"] = TaskStatus.ABANDONED.value
        task["history"] = history
        task["last_update"] = now.isoformat()
        task["notes"] = reason
        task["claim"] = None

        return task

    def retry_task(self, task: dict) -> dict:
        """
        重试任务（failed/blocked/abandoned -> pending）。

        Args:
            task: 任务字典

        Returns:
            更新后的任务字典

        Raises:
            ValueError: 超过最大重试次数
        """
        current_status = TaskStatus(task.get("status", "pending"))

        if current_status not in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.ABANDONED}:
            raise ValueError(f"只能重试 failed/blocked/abandoned 状态的任务，当前状态: {current_status}")

        # 检查重试次数
        history = task.get("history", [])
        if len(history) >= self.config["max_attempts"]:
            raise ValueError(f"超过最大重试次数: {self.config['max_attempts']}")

        now = datetime.now(timezone.utc)

        # 更新任务
        task = {**task}
        task["status"] = TaskStatus.PENDING.value
        task["last_update"] = now.isoformat()

        return task

    def reclaim_expired_leases(self, tasks: list[dict]) -> list[dict]:
        """
        回收所有过期租约的任务。

        Args:
            tasks: 任务列表

        Returns:
            更新后的任务列表
        """
        updated_tasks = []

        for task in tasks:
            if task.get("status") == TaskStatus.IN_PROGRESS.value:
                claim = task.get("claim")
                if claim:
                    claim_obj = Claim.from_dict(claim)
                    if claim_obj.is_expired():
                        # 检查是否超过最大重试次数
                        history = task.get("history", [])
                        if len(history) >= self.config["max_attempts"]:
                            task = self.abandon_task(task, "lease expired, max attempts reached")
                        else:
                            task = self.abandon_task(task, "lease expired")
                            # 自动重试
                            task = self.retry_task(task)

            updated_tasks.append(task)

        return updated_tasks

    def select_next_task(self, tasks: list[dict]) -> Optional[dict]:
        """
        选择下一个可执行的任务。

        条件：
        1. status == pending
        2. 所有依赖已完成
        3. 没有有效的 lease

        Args:
            tasks: 任务列表

        Returns:
            下一个可执行的任务，或 None
        """
        # 已完成的任务 ID
        completed_ids = {
            t["id"] for t in tasks
            if t.get("status") == TaskStatus.COMPLETED.value
        }

        for task in tasks:
            if task.get("status") != TaskStatus.PENDING.value:
                continue

            # 检查依赖
            deps = task.get("depends_on", [])
            if not all(d in completed_ids for d in deps):
                continue

            # 检查 lease
            claim = task.get("claim")
            if claim:
                claim_obj = Claim.from_dict(claim)
                if not claim_obj.is_expired():
                    continue

            return task

        return None
