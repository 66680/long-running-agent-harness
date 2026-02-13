#!/usr/bin/env python3
"""
auto_task_runner.py - 状态机驱动的自动化任务循环系统 v2.0

核心特性：
- 严格状态机：父进程独占调度权，子进程不可自选任务
- 文件锁：跨平台原子读写，防止并发损坏
- 租约机制：lease 过期自动回收，防止任务永久卡住
- verify gate：验证失败不会被标记为 completed
- 可审计：结构化日志，完整历史记录

使用方法：
    python auto_task_runner.py              # 执行一个任务
    python auto_task_runner.py --loop       # 循环执行直到完成
    python auto_task_runner.py --count 5    # 执行 5 个任务
    python auto_task_runner.py --status     # 查看当前状态
    python auto_task_runner.py --dry-run    # 只显示下一个任务
    python auto_task_runner.py --reclaim    # 回收过期租约
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 添加 lib 到路径
sys.path.insert(0, str(Path(__file__).parent))

from lib.file_lock import TaskFileLock
from lib.state_machine import TaskStateMachine, TaskStatus, VerifyResult, GitResult
from lib.prompts import build_task_prompt
from lib.progress_logger import ProgressLogger

# 默认配置
DEFAULT_CONFIG = {
    "task_file": "Task.json",
    "progress_file": "progress.txt",
    "claude_md": "CLAUDE.md",
    "runs_dir": "runs",
    "max_turns": 50,
    "timeout": 900,
    "loop_delay": 3,
    "max_failures": 3,
    "stop_file": "STOP",
    "pause_file": "PAUSE",
    "lease_ttl_seconds": 900,
    "max_attempts": 3,
    "verify_required": True,
    "verify_command": "scripts/verify.sh",
}


class Colors:
    """终端颜色"""
    BLUE = '\033[34m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def log(msg: str, level: str = "INFO"):
    """日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {
        "INFO": Colors.BLUE,
        "OK": Colors.GREEN,
        "WARN": Colors.YELLOW,
        "ERR": Colors.RED
    }
    color = colors.get(level, "")
    print(f"{color}[{ts}] {msg}{Colors.RESET}")


class TaskRunner:
    """任务运行器"""

    def __init__(self, config: dict):
        self.config = config
        self.state_machine = TaskStateMachine({
            "lease_ttl_seconds": config["lease_ttl_seconds"],
            "max_attempts": config["max_attempts"],
            "verify_required": config["verify_required"],
        })
        self.logger = ProgressLogger(config["progress_file"])
        self.runner_id = self.state_machine.generate_runner_id()
        # 确保 runs 目录存在
        self.runs_dir = Path(config.get("runs_dir", "runs"))
        self.runs_dir.mkdir(exist_ok=True)

    def archive_run(self, run_id: str, stdout: str, stderr: str, result: Optional[dict]) -> str:
        """
        归档运行输出到 runs/ 目录。

        Args:
            run_id: 运行 ID
            stdout: 标准输出
            stderr: 标准错误
            result: 解析的结果（可能为 None）

        Returns:
            归档文件路径
        """
        archive_path = self.runs_dir / f"{run_id}.json"
        archive_data = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stdout": stdout[:50000] if stdout else "",  # 限制大小
            "stderr": stderr[:10000] if stderr else "",
            "parsed_result": result,
        }
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        return str(archive_path)

    def load_tasks(self) -> dict:
        """加载任务列表（带锁）"""
        try:
            with TaskFileLock(self.config["task_file"]) as lock:
                return lock.read()
        except FileNotFoundError:
            log(f"未找到 {self.config['task_file']}", "ERR")
            return {"version": "2.0", "config": {}, "tasks": []}
        except json.JSONDecodeError as e:
            log(f"Task.json 格式错误: {e}", "ERR")
            return {"version": "2.0", "config": {}, "tasks": []}

    def save_tasks(self, data: dict) -> None:
        """保存任务列表（带锁）"""
        with TaskFileLock(self.config["task_file"]) as lock:
            lock.write(data)

    def get_task_stats(self) -> dict:
        """获取任务统计"""
        data = self.load_tasks()
        tasks = data.get("tasks", [])
        stats = {"total": len(tasks)}
        for t in tasks:
            s = t.get("status", "unknown")
            stats[s] = stats.get(s, 0) + 1
        return stats

    def check_stop_signal(self) -> bool:
        """检查停止信号"""
        return os.path.exists(self.config["stop_file"])

    def check_pause_signal(self) -> bool:
        """检查暂停信号"""
        return os.path.exists(self.config["pause_file"])

    def has_blocked_tasks(self) -> bool:
        """检查是否有阻塞任务"""
        data = self.load_tasks()
        return any(t.get("status") == "blocked" for t in data.get("tasks", []))

    def reclaim_expired_leases(self) -> int:
        """回收过期租约，返回回收数量"""
        reclaimed = 0

        with TaskFileLock(self.config["task_file"]) as lock:
            data = lock.read()
            tasks = data.get("tasks", [])

            for i, task in enumerate(tasks):
                if task.get("status") == TaskStatus.IN_PROGRESS.value:
                    claim = task.get("claim")
                    if claim:
                        from lib.state_machine import Claim
                        claim_obj = Claim.from_dict(claim)
                        if claim_obj.is_expired():
                            old_run_id = claim["run_id"]
                            history = task.get("history", [])

                            # 检查是否超过最大重试次数
                            if len(history) >= self.config["max_attempts"]:
                                tasks[i] = self.state_machine.abandon_task(
                                    task, "lease expired, max attempts reached"
                                )
                                new_status = "abandoned"
                            else:
                                tasks[i] = self.state_machine.abandon_task(task)
                                tasks[i] = self.state_machine.retry_task(tasks[i])
                                new_status = "pending (retry)"

                            self.logger.log_reclaim(task["id"], old_run_id, new_status)
                            reclaimed += 1

            if reclaimed > 0:
                data["tasks"] = tasks
                data["last_modified"] = datetime.now(timezone.utc).isoformat()
                lock.write(data)

        return reclaimed

    def select_next_task(self) -> Optional[dict]:
        """选择下一个可执行任务"""
        data = self.load_tasks()
        return self.state_machine.select_next_task(data.get("tasks", []))

    def claim_task(self, task_id: str, run_id: str) -> dict:
        """领取任务"""
        with TaskFileLock(self.config["task_file"]) as lock:
            data = lock.read()
            tasks = data.get("tasks", [])

            for i, task in enumerate(tasks):
                if task["id"] == task_id:
                    tasks[i] = self.state_machine.claim_task(
                        task, run_id, self.runner_id
                    )
                    data["tasks"] = tasks
                    data["last_modified"] = datetime.now(timezone.utc).isoformat()
                    lock.write(data)
                    return tasks[i]

            raise ValueError(f"任务不存在: {task_id}")

    def update_task_result(
        self,
        task_id: str,
        run_id: str,
        status: str,
        verify: Optional[VerifyResult] = None,
        git: Optional[GitResult] = None,
        summary: str = "",
        error: str = "",
    ) -> dict:
        """更新任务结果"""
        with TaskFileLock(self.config["task_file"]) as lock:
            data = lock.read()
            tasks = data.get("tasks", [])

            for i, task in enumerate(tasks):
                if task["id"] == task_id:
                    if status == "completed":
                        tasks[i] = self.state_machine.complete_task(
                            task, run_id, verify, git, summary
                        )
                    elif status == "failed":
                        tasks[i] = self.state_machine.fail_task(
                            task, run_id, error, verify
                        )
                    elif status == "blocked":
                        tasks[i] = self.state_machine.block_task(
                            task, run_id, error
                        )
                    else:
                        raise ValueError(f"未知状态: {status}")

                    data["tasks"] = tasks
                    data["last_modified"] = datetime.now(timezone.utc).isoformat()
                    lock.write(data)
                    return tasks[i]

            raise ValueError(f"任务不存在: {task_id}")

    def get_claude_path(self) -> str:
        """获取 claude 命令路径"""
        claude_path = shutil.which("claude")
        if claude_path:
            return claude_path

        if sys.platform == "win32":
            possible_paths = [
                os.path.expanduser("~/AppData/Roaming/npm/claude.cmd"),
                os.path.expanduser("~/AppData/Roaming/npm/claude"),
                "C:/Program Files/nodejs/claude.cmd",
            ]
            for p in possible_paths:
                if os.path.exists(p):
                    return p

        return "claude"

    def run_claude_subprocess(
        self,
        task: dict,
        run_id: str,
    ) -> tuple[bool, str, Optional[dict]]:
        """运行 Claude 子进程"""
        claude_cmd = self.get_claude_path()

        # 构建提示词
        attempt = 1
        if task.get("claim"):
            attempt = task["claim"].get("attempt", 1)

        prompt = build_task_prompt(
            task_id=task["id"],
            run_id=run_id,
            task_description=task["description"],
            depends_on=task.get("depends_on", []),
            attempt=attempt,
            max_attempts=self.config["max_attempts"],
            verify_command=self.config.get("verify_command"),
        )

        cmd = [
            claude_cmd,
            "-p",
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--output-format", "json",
            "--max-turns", str(self.config["max_turns"]),
            prompt
        ]

        try:
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            log(f"启动子进程 (run_id={run_id[:20]}...)")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config["timeout"],
                cwd=os.getcwd(),
                env=env,
            )

            output = result.stdout or ""
            stderr = result.stderr or ""

            parsed_result = None
            if output:
                try:
                    json_output = json.loads(output)
                    if isinstance(json_output, dict) and "result" in json_output:
                        actual_output = json_output.get("result", "")
                        parsed_result = self.extract_task_result(actual_output)
                        output = actual_output
                except json.JSONDecodeError:
                    parsed_result = self.extract_task_result(output)

            # 归档运行输出
            archive_path = self.archive_run(run_id, output, stderr, parsed_result)
            log(f"归档到 {archive_path}")

            if result.returncode == 0:
                return True, output, parsed_result
            else:
                error_msg = stderr if stderr else f"退出码: {result.returncode}"
                return False, error_msg, None

        except subprocess.TimeoutExpired:
            return False, f"执行超时 ({self.config['timeout']}秒)", None
        except FileNotFoundError:
            return False, "未找到 claude 命令", None
        except Exception as e:
            return False, str(e), None

    def extract_task_result(self, text: str) -> Optional[dict]:
        """从输出文本中提取任务结果 JSON"""
        if not text:
            return None

        lines = text.strip().split('\n')
        for line in reversed(lines):
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    result = json.loads(line)
                    if "task_id" in result and "status" in result:
                        return result
                except json.JSONDecodeError:
                    continue

        json_blocks = re.findall(r'```json\s*\n({[^`]+})\s*\n```', text)
        for block in reversed(json_blocks):
            try:
                result = json.loads(block)
                if "task_id" in result and "status" in result:
                    return result
            except json.JSONDecodeError:
                continue

        return None

    def execute_one_task(self, dry_run: bool = False) -> tuple[bool, Optional[str]]:
        """执行一个任务"""
        # 检查停止信号
        if self.check_stop_signal():
            log(f"检测到 {self.config['stop_file']} 文件，停止执行", "WARN")
            return False, None

        # 检查暂停信号
        if self.check_pause_signal():
            log(f"检测到 {self.config['pause_file']} 文件，暂停执行", "WARN")
            return False, None

        # 回收过期租约
        reclaimed = self.reclaim_expired_leases()
        if reclaimed > 0:
            log(f"回收了 {reclaimed} 个过期租约", "INFO")

        # 选择任务
        task = self.select_next_task()
        if not task:
            stats = self.get_task_stats()
            if stats.get("blocked", 0) > 0:
                log("存在阻塞任务，需要人工介入", "WARN")
            elif stats.get("pending", 0) == 0:
                log("所有任务已完成！", "OK")
            else:
                log("没有可执行的任务（可能有未满足的依赖）", "WARN")
            return False, None

        task_id = task["id"]
        task_desc = task["description"][:60]
        log(f"下一个任务: {task_id} - {task_desc}...")

        if dry_run:
            log("(dry-run 模式，不实际执行)", "INFO")
            return True, task_id

        # 生成 run_id
        run_id = self.state_machine.generate_run_id()

        # 领取任务
        try:
            claimed_task = self.claim_task(task_id, run_id)
            attempt = claimed_task.get("claim", {}).get("attempt", 1)
            self.logger.log_claim(
                task_id, run_id, task["description"],
                attempt, self.config["max_attempts"]
            )
        except Exception as e:
            log(f"领取任务失败: {e}", "ERR")
            return False, None

        # 执行任务
        start_time = time.time()
        log("=" * 50)
        success, output, result = self.run_claude_subprocess(claimed_task, run_id)
        log("=" * 50)
        duration = time.time() - start_time

        # 处理结果
        if success and result:
            # 验证 run_id
            if result.get("run_id") != run_id:
                log(f"run_id 不匹配: 期望 {run_id}, 实际 {result.get('run_id')}", "ERR")
                self.logger.log_run_id_mismatch(task_id, run_id, result.get("run_id", ""))
                self.update_task_result(
                    task_id, run_id, "failed",
                    error="run_id mismatch"
                )
                self.logger.log_fail(
                    task_id, run_id, "run_id mismatch",
                    attempt, self.config["max_attempts"], duration,
                    attempt < self.config["max_attempts"]
                )
                return False, task_id

            status = result.get("status", "failed")

            if status == "completed":
                # 验证 verify
                verify_data = result.get("verify", {})
                verify = VerifyResult(
                    command=verify_data.get("command", ""),
                    exit_code=verify_data.get("exit_code", -1),
                    evidence=verify_data.get("evidence", ""),
                )

                if self.config["verify_required"] and verify.exit_code != 0:
                    log(f"verify 失败: exit_code={verify.exit_code}", "ERR")
                    self.logger.log_verify_fail(
                        task_id, run_id, verify.command,
                        verify.exit_code, verify.evidence
                    )
                    self.update_task_result(
                        task_id, run_id, "failed",
                        verify=verify,
                        error=f"verify failed: exit_code={verify.exit_code}"
                    )
                    self.logger.log_fail(
                        task_id, run_id, f"verify failed: exit_code={verify.exit_code}",
                        attempt, self.config["max_attempts"], duration,
                        attempt < self.config["max_attempts"]
                    )
                    return False, task_id

                git_data = result.get("git", {})
                git = GitResult(
                    commit=git_data.get("commit", ""),
                    branch=git_data.get("branch", "main"),
                ) if git_data else None

                self.update_task_result(
                    task_id, run_id, "completed",
                    verify=verify, git=git,
                    summary=result.get("summary", "")
                )
                self.logger.log_complete(
                    task_id, run_id, result.get("summary", ""),
                    verify.command, verify.exit_code, verify.evidence,
                    git.commit if git else None, duration
                )
                log(f"任务完成: {result.get('summary', '')}", "OK")
                return True, task_id

            elif status == "blocked":
                error = result.get("error", "unknown")
                self.update_task_result(task_id, run_id, "blocked", error=error)
                self.logger.log_block(task_id, run_id, error, duration)
                log(f"任务阻塞: {error}", "WARN")
                return False, task_id

            else:  # failed
                error = result.get("error", "unknown")
                self.update_task_result(task_id, run_id, "failed", error=error)
                self.logger.log_fail(
                    task_id, run_id, error,
                    attempt, self.config["max_attempts"], duration,
                    attempt < self.config["max_attempts"]
                )
                log(f"任务失败: {error}", "ERR")
                return False, task_id

        else:
            # 子进程执行失败或无法解析结果
            error = output if output else "子进程执行失败"
            self.update_task_result(task_id, run_id, "failed", error=error)
            self.logger.log_fail(
                task_id, run_id, error,
                attempt, self.config["max_attempts"], duration,
                attempt < self.config["max_attempts"]
            )
            log(f"任务执行失败: {error}", "ERR")
            return False, task_id

    def run_loop(self, max_count: Optional[int] = None):
        """循环执行任务"""
        print()
        print(f"{Colors.BOLD}{'=' * 50}")
        print("  状态机驱动的自动化任务循环系统 v2.0")
        print("  父进程独占调度权，子进程不可自选任务")
        print(f"{'=' * 50}{Colors.RESET}")
        print()

        # 记录启动
        self.logger.log_startup(self.runner_id, self.config)

        # 显示初始状态
        stats = self.get_task_stats()
        log(f"任务状态: {stats}")

        if self.check_stop_signal():
            log(f"检测到 {self.config['stop_file']} 文件，请先删除", "WARN")
            return

        count = 0
        failures = 0

        while True:
            # 检查停止信号
            if self.check_stop_signal():
                log(f"检测到 {self.config['stop_file']} 文件，停止执行", "WARN")
                self.logger.log_stop("STOP file detected")
                break

            # 检查暂停信号
            if self.check_pause_signal():
                log(f"检测到 {self.config['pause_file']} 文件，暂停执行", "WARN")
                self.logger.log_pause("PAUSE file detected")
                while self.check_pause_signal():
                    time.sleep(5)
                self.logger.log_resume()
                log("PAUSE 文件已删除，恢复执行", "OK")
                continue

            if self.has_blocked_tasks():
                log("存在阻塞任务，停止执行", "WARN")
                self.logger.log_stop("blocked tasks exist")
                break

            if max_count is not None and count >= max_count:
                log(f"已执行 {count} 个任务，达到指定数量", "OK")
                break

            print()
            log(f"===== 任务轮次 #{count + 1} =====")

            success, task_id = self.execute_one_task()

            if success and task_id:
                count += 1
                failures = 0
                stats = self.get_task_stats()
                log(f"当前进度: {stats}")
            else:
                if not self.select_next_task():
                    stats = self.get_task_stats()
                    if stats.get("pending", 0) == 0:
                        log("所有任务已完成！", "OK")
                    break

                failures += 1
                if failures >= self.config["max_failures"]:
                    log(f"连续失败 {failures} 次，停止执行", "ERR")
                    self.logger.log_stop(f"max failures reached: {failures}")
                    break

                log(f"失败 {failures}/{self.config['max_failures']}，等待后重试...", "WARN")

            next_task = self.select_next_task()
            if next_task and (max_count is None or count < max_count):
                log(f"等待 {self.config['loop_delay']} 秒后执行下一个任务...")
                time.sleep(self.config["loop_delay"])

        print()
        log(f"执行结束，共完成 {count} 个任务")
        stats = self.get_task_stats()
        log(f"最终状态: {stats}")

    def show_status(self):
        """显示当前状态"""
        print()
        print(f"{Colors.BOLD}任务状态{Colors.RESET}")
        print("-" * 40)

        stats = self.get_task_stats()
        for status, count in sorted(stats.items()):
            if status == "total":
                continue
            color = {
                "completed": Colors.GREEN,
                "pending": Colors.BLUE,
                "in_progress": Colors.YELLOW,
                "failed": Colors.RED,
                "blocked": Colors.RED,
                "abandoned": Colors.YELLOW,
            }.get(status, "")
            print(f"  {color}{status}: {count}{Colors.RESET}")
        print(f"  总计: {stats.get('total', 0)}")

        print()
        next_task = self.select_next_task()
        if next_task:
            print(f"{Colors.BOLD}下一个任务{Colors.RESET}")
            print(f"  ID: {next_task['id']}")
            print(f"  描述: {next_task['description']}")
            deps = next_task.get("depends_on", [])
            if deps:
                print(f"  依赖: {', '.join(deps)}")
        else:
            print("没有待执行的任务")

        print()
        if self.check_stop_signal():
            print(f"{Colors.YELLOW}注意: 检测到 STOP 文件{Colors.RESET}")
        if self.check_pause_signal():
            print(f"{Colors.YELLOW}注意: 检测到 PAUSE 文件{Colors.RESET}")
        if self.has_blocked_tasks():
            print(f"{Colors.RED}警告: 存在阻塞任务，需要人工介入{Colors.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="状态机驱动的自动化任务循环系统 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python auto_task_runner.py              # 执行一个任务
  python auto_task_runner.py --loop       # 循环执行直到完成
  python auto_task_runner.py --count 5    # 执行 5 个任务
  python auto_task_runner.py --status     # 查看当前状态
  python auto_task_runner.py --dry-run    # 只显示下一个任务
  python auto_task_runner.py --reclaim    # 回收过期租约

停止/暂停:
  touch STOP                              # 立即停止
  touch PAUSE                             # 暂停（删除后恢复）
        """
    )

    parser.add_argument("--loop", action="store_true",
                        help="循环执行直到所有任务完成")
    parser.add_argument("--count", type=int, metavar="N",
                        help="执行指定数量的任务")
    parser.add_argument("--status", action="store_true",
                        help="显示当前任务状态")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示下一个任务，不实际执行")
    parser.add_argument("--reclaim", action="store_true",
                        help="回收过期租约")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_CONFIG["max_turns"],
                        help=f"Claude 最大轮次 (默认: {DEFAULT_CONFIG['max_turns']})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_CONFIG["timeout"],
                        help=f"执行超时秒数 (默认: {DEFAULT_CONFIG['timeout']})")
    parser.add_argument("--lease-ttl", type=int, default=DEFAULT_CONFIG["lease_ttl_seconds"],
                        help=f"租约 TTL 秒数 (默认: {DEFAULT_CONFIG['lease_ttl_seconds']})")

    args = parser.parse_args()

    # 构建配置
    config = {**DEFAULT_CONFIG}
    config["max_turns"] = args.max_turns
    config["timeout"] = args.timeout
    config["lease_ttl_seconds"] = args.lease_ttl

    runner = TaskRunner(config)

    if args.status:
        runner.show_status()
    elif args.reclaim:
        reclaimed = runner.reclaim_expired_leases()
        log(f"回收了 {reclaimed} 个过期租约", "OK" if reclaimed > 0 else "INFO")
    elif args.dry_run:
        runner.execute_one_task(dry_run=True)
    elif args.loop:
        runner.run_loop()
    elif args.count:
        runner.run_loop(max_count=args.count)
    else:
        runner.execute_one_task()


if __name__ == "__main__":
    main()
