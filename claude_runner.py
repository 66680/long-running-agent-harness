#!/usr/bin/env python3
"""
claude_runner.py - 使用 Claude Code CLI 实现真正的无限循环任务执行

使用方法:
1. 确保已安装 Claude Code CLI: npm install -g @anthropic-ai/claude-code
2. 确保已登录: claude login
3. 运行: python claude_runner.py

停止方法:
- 创建 STOP 文件: touch STOP
- 或按 Ctrl+C
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 配置
CONFIG = {
    "max_consecutive_failures": 3,
    "loop_delay_seconds": 10,  # 每轮之间的延迟
    "task_file": "Task.json",
    "progress_file": "progress.txt",
    "stop_file": "STOP",
    "claude_timeout": 600,  # Claude 执行超时（秒）
}

# Agent 提示词模板
AGENT_PROMPT = """
我将先获取项目现状：读取 CLAUDE.md、progress.txt、Task.json，
查看 git log，运行初始化脚本并做一次最小验证测试，然后再领取一个任务。

请按照 CLAUDE.md 中的 6 步开发流程执行：
1. 运行 ./init.sh 初始化环境
2. 从 Task.json 领取一个 pending 状态的任务（将其改为 in_progress）
3. 实现该任务
4. 运行 ./scripts/verify.sh 验证
5. 更新 Task.json（改为 completed/failed/blocked）和 progress.txt
6. 执行 git commit 提交改动

完成后输出：任务ID、执行结果、下一步建议。
"""


def log(message: str, level: str = "INFO") -> None:
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    colors = {
        "INFO": "\033[0;34m",
        "SUCCESS": "\033[0;32m",
        "WARN": "\033[1;33m",
        "ERROR": "\033[0;31m",
    }
    nc = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}[{timestamp}] [{level}] {message}{nc}")


def load_tasks():
    """加载任务列表"""
    try:
        with open(CONFIG["task_file"], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"加载 Task.json 失败: {e}", "ERROR")
        return {"tasks": []}


def get_pending_task_count():
    """获取待处理任务数量"""
    data = load_tasks()
    tasks = data.get("tasks", [])
    pending = [t for t in tasks if t.get("status") in ["pending", "in_progress"]]
    return len(pending)


def get_blocked_task_count():
    """获取阻塞任务数量"""
    data = load_tasks()
    tasks = data.get("tasks", [])
    blocked = [t for t in tasks if t.get("status") == "blocked"]
    return len(blocked)


def check_stop_file():
    """检查停止文件"""
    return os.path.exists(CONFIG["stop_file"])


def run_claude_agent():
    """运行 Claude Code Agent 执行一轮任务"""
    log("启动 Claude Code Agent...")

    try:
        # 使用 claude 命令行工具
        # --print: 只打印输出，不进入交互模式
        # --dangerously-skip-permissions: 跳过权限确认（谨慎使用）
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",  # 生产环境建议移除此选项
                AGENT_PROMPT
            ],
            capture_output=True,
            text=True,
            timeout=CONFIG["claude_timeout"],
            cwd=os.getcwd()
        )

        if result.returncode == 0:
            log("Claude Agent 执行成功", "SUCCESS")
            print("--- Agent 输出 ---")
            print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
            print("--- 输出结束 ---")
            return True
        else:
            log(f"Claude Agent 执行失败: {result.stderr}", "ERROR")
            return False

    except subprocess.TimeoutExpired:
        log(f"Claude Agent 执行超时 ({CONFIG['claude_timeout']}秒)", "ERROR")
        return False
    except FileNotFoundError:
        log("未找到 claude 命令，请确保已安装 Claude Code CLI", "ERROR")
        log("安装命令: npm install -g @anthropic-ai/claude-code", "WARN")
        return False
    except Exception as e:
        log(f"Claude Agent 执行异常: {e}", "ERROR")
        return False


def main():
    """主循环"""
    print("=" * 50)
    print("  Claude Code 无限循环任务执行器")
    print("=" * 50)
    print()
    print("停止方法: touch STOP 或 Ctrl+C")
    print()

    consecutive_failures = 0
    loop_count = 0

    while True:
        loop_count += 1
        log(f"========== 循环 #{loop_count} ==========")

        # 1. 检查停止文件
        if check_stop_file():
            log("检测到 STOP 文件，停止运行", "WARN")
            break

        # 2. 检查阻塞任务
        blocked_count = get_blocked_task_count()
        if blocked_count > 0:
            log(f"存在 {blocked_count} 个阻塞任务，需要人工介入", "WARN")
            log("请查看 progress.txt 中的人工介入请求", "WARN")
            break

        # 3. 检查是否还有任务
        pending_count = get_pending_task_count()
        if pending_count == 0:
            log("所有任务已完成！", "SUCCESS")
            break

        log(f"剩余 {pending_count} 个待处理任务")

        # 4. 运行 Claude Agent
        if run_claude_agent():
            consecutive_failures = 0
            log("本轮执行成功", "SUCCESS")
        else:
            consecutive_failures += 1
            log(f"本轮执行失败 (连续失败: {consecutive_failures}/{CONFIG['max_consecutive_failures']})", "ERROR")

            if consecutive_failures >= CONFIG["max_consecutive_failures"]:
                log("连续失败次数达到上限，停止运行", "ERROR")
                break

        # 5. 延迟
        log(f"等待 {CONFIG['loop_delay_seconds']} 秒后进入下一轮...")
        time.sleep(CONFIG["loop_delay_seconds"])

    log(f"运行结束，共执行 {loop_count} 轮")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n收到中断信号，停止运行", "WARN")
