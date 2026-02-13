"""
progress_logger.py - 结构化日志

提供统一的日志格式，记录：
- 时间戳
- 事件类型
- 任务 ID 和运行 ID
- 状态转移
- 证据和结果
- 耗时统计
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ProgressLogger:
    """
    结构化进度日志记录器。

    日志格式：
    ```
    [时间] 事件类型: task_id
    运行 ID: run_id
    尝试: 1/3
    状态: pending -> in_progress
    操作: ...
    证据: ...
    结果: 成功/失败/阻塞
    耗时: 120秒
    下一步: ...
    需要人工: 是/否
    ```
    """

    def __init__(self, file_path: str = "progress.txt"):
        """
        初始化日志记录器。

        Args:
            file_path: 日志文件路径
        """
        self.file_path = Path(file_path).resolve()

    def _timestamp(self) -> str:
        """获取当前时间戳"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _append(self, content: str) -> None:
        """追加内容到日志文件"""
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")

    def log_claim(
        self,
        task_id: str,
        run_id: str,
        description: str,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """
        记录任务领取事件。

        Args:
            task_id: 任务 ID
            run_id: 运行 ID
            description: 任务描述
            attempt: 当前尝试次数
            max_attempts: 最大尝试次数
        """
        entry = f"""
{'=' * 60}
[{self._timestamp()}] CLAIM: {task_id}
运行 ID: {run_id}
尝试: {attempt}/{max_attempts}
状态: pending -> in_progress
描述: {description}
操作: 父进程领取任务，启动子进程
"""
        self._append(entry)

    def log_complete(
        self,
        task_id: str,
        run_id: str,
        summary: str,
        verify_command: str,
        verify_exit_code: int,
        verify_evidence: str,
        git_commit: Optional[str],
        duration_seconds: float,
    ) -> None:
        """
        记录任务完成事件。

        Args:
            task_id: 任务 ID
            run_id: 运行 ID
            summary: 任务摘要
            verify_command: 验证命令
            verify_exit_code: 验证退出码
            verify_evidence: 验证证据
            git_commit: Git 提交哈希
            duration_seconds: 耗时（秒）
        """
        git_info = f"Git 提交: {git_commit}" if git_commit else "Git 提交: 无"

        entry = f"""[{self._timestamp()}] COMPLETE: {task_id}
运行 ID: {run_id}
状态: in_progress -> completed
验证命令: {verify_command}
验证结果: exit_code={verify_exit_code}
验证证据: {verify_evidence}
{git_info}
摘要: {summary}
耗时: {duration_seconds:.1f}秒
结果: 成功
需要人工: 否
"""
        self._append(entry)

    def log_fail(
        self,
        task_id: str,
        run_id: str,
        error: str,
        attempt: int,
        max_attempts: int,
        duration_seconds: float,
        can_retry: bool,
    ) -> None:
        """
        记录任务失败事件。

        Args:
            task_id: 任务 ID
            run_id: 运行 ID
            error: 错误信息
            attempt: 当前尝试次数
            max_attempts: 最大尝试次数
            duration_seconds: 耗时（秒）
            can_retry: 是否可以重试
        """
        next_step = "自动重试" if can_retry else "需要人工介入"

        entry = f"""[{self._timestamp()}] FAIL: {task_id}
运行 ID: {run_id}
尝试: {attempt}/{max_attempts}
状态: in_progress -> failed
错误: {error}
耗时: {duration_seconds:.1f}秒
结果: 失败
下一步: {next_step}
需要人工: {'否' if can_retry else '是'}
"""
        self._append(entry)

    def log_block(
        self,
        task_id: str,
        run_id: str,
        reason: str,
        duration_seconds: float,
    ) -> None:
        """
        记录任务阻塞事件。

        Args:
            task_id: 任务 ID
            run_id: 运行 ID
            reason: 阻塞原因
            duration_seconds: 耗时（秒）
        """
        entry = f"""[{self._timestamp()}] BLOCK: {task_id}
运行 ID: {run_id}
状态: in_progress -> blocked
原因: {reason}
耗时: {duration_seconds:.1f}秒
结果: 阻塞
下一步: 等待人工介入
需要人工: 是

--- Human Help Packet ---
任务 ID: {task_id}
运行 ID: {run_id}
阻塞原因: {reason}
请检查 progress.txt 和 Task.json 了解详情
建议操作:
1. 解决阻塞问题
2. 将任务状态改为 pending 以重试
3. 或将任务状态改为 canceled 以跳过
--- End Packet ---
"""
        self._append(entry)

    def log_abandon(
        self,
        task_id: str,
        run_id: str,
        reason: str,
    ) -> None:
        """
        记录任务放弃事件（租约过期）。

        Args:
            task_id: 任务 ID
            run_id: 运行 ID
            reason: 放弃原因
        """
        entry = f"""[{self._timestamp()}] ABANDON: {task_id}
运行 ID: {run_id}
状态: in_progress -> abandoned
原因: {reason}
操作: 父进程回收过期租约
下一步: 自动重试（如果未超过最大次数）
"""
        self._append(entry)

    def log_reclaim(
        self,
        task_id: str,
        old_run_id: str,
        new_status: str,
    ) -> None:
        """
        记录租约回收事件。

        Args:
            task_id: 任务 ID
            old_run_id: 原运行 ID
            new_status: 新状态
        """
        entry = f"""[{self._timestamp()}] RECLAIM: {task_id}
原运行 ID: {old_run_id}
操作: 回收过期租约
新状态: {new_status}
"""
        self._append(entry)

    def log_stop(self, reason: str) -> None:
        """
        记录停止事件。

        Args:
            reason: 停止原因
        """
        entry = f"""
{'=' * 60}
[{self._timestamp()}] STOP
原因: {reason}
{'=' * 60}
"""
        self._append(entry)

    def log_pause(self, reason: str) -> None:
        """
        记录暂停事件。

        Args:
            reason: 暂停原因
        """
        entry = f"""[{self._timestamp()}] PAUSE
原因: {reason}
操作: 进入睡眠循环，等待 PAUSE 文件删除
"""
        self._append(entry)

    def log_resume(self) -> None:
        """记录恢复事件。"""
        entry = f"""[{self._timestamp()}] RESUME
操作: PAUSE 文件已删除，恢复执行
"""
        self._append(entry)

    def log_startup(self, runner_id: str, config: dict) -> None:
        """
        记录启动事件。

        Args:
            runner_id: 运行器 ID
            config: 配置信息
        """
        entry = f"""
{'=' * 60}
[{self._timestamp()}] STARTUP
运行器 ID: {runner_id}
配置:
  - lease_ttl_seconds: {config.get('lease_ttl_seconds', 900)}
  - max_attempts: {config.get('max_attempts', 3)}
  - verify_required: {config.get('verify_required', True)}
  - max_turns: {config.get('max_turns', 50)}
  - timeout: {config.get('timeout', 900)}
{'=' * 60}
"""
        self._append(entry)

    def log_run_id_mismatch(
        self,
        task_id: str,
        expected_run_id: str,
        actual_run_id: str,
    ) -> None:
        """
        记录 run_id 不匹配事件。

        Args:
            task_id: 任务 ID
            expected_run_id: 期望的 run_id
            actual_run_id: 实际的 run_id
        """
        entry = f"""[{self._timestamp()}] RUN_ID_MISMATCH: {task_id}
期望 run_id: {expected_run_id}
实际 run_id: {actual_run_id}
操作: 拒绝子进程结果，标记为失败
原因: 可能是子进程漂移或重放攻击
"""
        self._append(entry)

    def log_verify_fail(
        self,
        task_id: str,
        run_id: str,
        verify_command: str,
        exit_code: int,
        evidence: str,
    ) -> None:
        """
        记录验证失败事件。

        Args:
            task_id: 任务 ID
            run_id: 运行 ID
            verify_command: 验证命令
            exit_code: 退出码
            evidence: 证据
        """
        entry = f"""[{self._timestamp()}] VERIFY_FAIL: {task_id}
运行 ID: {run_id}
验证命令: {verify_command}
退出码: {exit_code}
证据: {evidence}
操作: 拒绝标记为 completed，改为 failed
"""
        self._append(entry)
