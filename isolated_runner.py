#!/usr/bin/env python3
"""
isolated_runner.py - 隔离上下文的任务执行器

核心特点：
- 每个任务在独立的 Claude 进程中执行（上下文完全隔离）
- 任务之间不共享对话历史
- 通过文件系统传递状态（Task.json, progress.txt）

使用方法：
    python isolated_runner.py          # 执行一个任务
    python isolated_runner.py --loop   # 循环执行直到完成
    python isolated_runner.py --count 5  # 执行 5 个任务
"""

import json
import os
import subprocess
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

CONFIG = {
    "task_file": "Task.json",
    "progress_file": "progress.txt",
    "claude_timeout": 600,  # 10 分钟超时
    "loop_delay": 5,  # 任务间隔秒数
    "max_failures": 3,
}

# 每个任务的独立提示词 - Claude 会在全新上下文中执行
TASK_PROMPT_TEMPLATE = '''你正在执行一个长期运行的开发项目。这是一个全新的会话，请先了解项目状态。

## 第一步：了解现状（必须执行）

1. 读取 CLAUDE.md 了解开发规范
2. 读取 progress.txt 了解历史进度
3. 读取 Task.json 了解任务状态
4. 运行 git log --oneline -5 查看最近提交

## 第二步：执行任务

从 Task.json 中找到第一个 status="pending" 的任务，然后：

1. 将该任务状态改为 "in_progress"，更新 last_update
2. 实现该任务（可以使用任何可用的 skills 和 MCP 工具）
3. 运行 ./scripts/verify.sh 验证
4. 更新 Task.json：
   - 成功：status 改为 "completed"
   - 失败：status 改为 "failed" 或 "blocked"
5. 在 progress.txt 末尾追加本次工作记录
6. 执行 git add 和 git commit

## 可用工具

在实现任务时，请主动使用：
- /plan - 复杂任务先规划
- /tdd - 测试驱动开发
- /security-review - 安全相关任务
- /commit - 提交代码
- MCP 工具 - 根据需要使用
- 子代理 - code-reviewer, build-error-resolver 等

## 输出要求

完成后输出：
- 任务 ID
- 执行结果（成功/失败/阻塞）
- 主要改动
- 下一个建议任务
'''


def log(msg: str, level: str = "INFO"):
    """日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {"INFO": "\033[34m", "OK": "\033[32m", "WARN": "\033[33m", "ERR": "\033[31m"}
    print(f"{colors.get(level, '')}[{ts}] {msg}\033[0m")


def load_tasks() -> dict:
    """加载任务列表"""
    try:
        with open(CONFIG["task_file"], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"加载 Task.json 失败: {e}", "ERR")
        return {"tasks": []}


def get_next_pending_task() -> dict | None:
    """获取下一个待执行任务"""
    data = load_tasks()
    tasks = data.get("tasks", [])
    completed_ids = {t["id"] for t in tasks if t.get("status") == "completed"}

    for task in tasks:
        if task.get("status") == "pending":
            deps = task.get("depends_on", [])
            if all(d in completed_ids for d in deps):
                return task
    return None


def get_task_stats() -> dict:
    """获取任务统计"""
    data = load_tasks()
    tasks = data.get("tasks", [])
    stats = {}
    for t in tasks:
        s = t.get("status", "unknown")
        stats[s] = stats.get(s, 0) + 1
    return stats


def has_blocked_tasks() -> bool:
    """检查是否有阻塞任务"""
    data = load_tasks()
    return any(t.get("status") == "blocked" for t in data.get("tasks", []))


def run_isolated_claude() -> tuple[bool, str]:
    """
    在隔离的进程中运行 Claude
    每次调用都是全新的上下文
    """
    log("启动新的 Claude 进程（隔离上下文）...")

    try:
        # 使用 claude --print 模式，每次都是独立进程
        result = subprocess.run(
            [
                "claude",
                "--print",  # 非交互模式
                "--dangerously-skip-permissions",  # 跳过确认（生产环境谨慎使用）
                TASK_PROMPT_TEMPLATE
            ],
            capture_output=True,
            text=True,
            timeout=CONFIG["claude_timeout"],
            cwd=os.getcwd(),
            env={**os.environ, "CLAUDE_NO_HISTORY": "1"}  # 确保不加载历史
        )

        output = result.stdout if result.stdout else ""

        if result.returncode == 0:
            return True, output[-2000:]  # 截取最后 2000 字符
        else:
            return False, result.stderr or "执行失败"

    except subprocess.TimeoutExpired:
        return False, f"执行超时 ({CONFIG['claude_timeout']}秒)"
    except FileNotFoundError:
        return False, "未找到 claude 命令，请安装: npm install -g @anthropic-ai/claude-code"
    except Exception as e:
        return False, str(e)


def execute_one_task() -> bool:
    """执行一个任务"""
    # 检查是否有待执行任务
    task = get_next_pending_task()
    if not task:
        stats = get_task_stats()
        if stats.get("blocked", 0) > 0:
            log("存在阻塞任务，需要人工介入", "WARN")
        else:
            log("没有待执行的任务", "OK")
        return False

    log(f"准备执行: {task['id']} - {task['description'][:50]}...")

    # 在隔离进程中执行
    success, output = run_isolated_claude()

    if success:
        log(f"任务执行完成", "OK")
        if output:
            # 显示输出摘要
            lines = output.strip().split('\n')
            for line in lines[-10:]:  # 最后 10 行
                print(f"  {line}")
        return True
    else:
        log(f"任务执行失败: {output}", "ERR")
        return False


def run_loop(max_count: int = None):
    """循环执行任务"""
    print("=" * 50)
    print("  隔离上下文任务执行器")
    print("  每个任务在独立 Claude 进程中执行")
    print("=" * 50)
    print()

    # 显示初始状态
    stats = get_task_stats()
    log(f"任务状态: {stats}")

    if os.path.exists("STOP"):
        log("检测到 STOP 文件，请先删除: rm STOP", "WARN")
        return

    count = 0
    failures = 0

    while True:
        # 检查停止条件
        if os.path.exists("STOP"):
            log("检测到 STOP 文件，停止执行", "WARN")
            break

        if has_blocked_tasks():
            log("存在阻塞任务，停止执行", "WARN")
            break

        if max_count and count >= max_count:
            log(f"已执行 {count} 个任务，达到指定数量", "OK")
            break

        # 执行任务
        print()
        log(f"===== 任务 #{count + 1} =====")

        success = execute_one_task()

        if success:
            count += 1
            failures = 0
        else:
            # 检查是否是因为没有任务了
            if not get_next_pending_task():
                log("所有任务已完成！", "OK")
                break

            failures += 1
            if failures >= CONFIG["max_failures"]:
                log(f"连续失败 {failures} 次，停止执行", "ERR")
                break

        # 任务间隔
        if max_count is None or count < max_count:
            next_task = get_next_pending_task()
            if next_task:
                log(f"等待 {CONFIG['loop_delay']} 秒后执行下一个任务...")
                time.sleep(CONFIG["loop_delay"])

    print()
    log(f"执行结束，共完成 {count} 个任务")
    stats = get_task_stats()
    log(f"最终状态: {stats}")


def main():
    parser = argparse.ArgumentParser(description="隔离上下文的任务执行器")
    parser.add_argument("--loop", action="store_true", help="循环执行直到完成")
    parser.add_argument("--count", type=int, help="执行指定数量的任务")
    args = parser.parse_args()

    if args.loop:
        run_loop()
    elif args.count:
        run_loop(max_count=args.count)
    else:
        # 默认执行一个任务
        execute_one_task()


if __name__ == "__main__":
    main()
