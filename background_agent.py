#!/usr/bin/env python3
"""
background_agent.py - 后台任务执行器

特点：
1. 在后台独立进程中运行，不阻塞你的 Claude Code 会话
2. 你可以继续在 Claude Code 中使用 skills 和其他功能
3. 通过文件进行通信（STOP/PAUSE/状态查看）

使用方法：
    # 启动后台执行器（在新终端窗口中）
    python background_agent.py start

    # 或者使用 nohup 完全后台运行
    nohup python background_agent.py start > agent.log 2>&1 &

    # 查看状态
    python background_agent.py status

    # 暂停（完成当前任务后暂停）
    python background_agent.py pause

    # 恢复
    python background_agent.py resume

    # 停止
    python background_agent.py stop

与 Claude Code 会话共存：
    - 后台执行器在独立终端运行
    - 你的 Claude Code 会话完全不受影响
    - 可以随时使用 /commit, /review-pr 等 skills
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import argparse

# 控制文件
CONTROL_DIR = Path(".agent_control")
PID_FILE = CONTROL_DIR / "agent.pid"
STATUS_FILE = CONTROL_DIR / "status.json"
STOP_FILE = CONTROL_DIR / "STOP"
PAUSE_FILE = CONTROL_DIR / "PAUSE"

# 配置
CONFIG = {
    "loop_delay_seconds": 30,  # 每轮之间的延迟（给你时间使用 Claude）
    "task_file": "Task.json",
    "progress_file": "progress.txt",
    "claude_timeout": 300,
    "max_consecutive_failures": 3,
}

AGENT_PROMPT = '''我将执行一轮任务循环。请按照 CLAUDE.md 中的流程：

1. 读取 Task.json，找到第一个 status="pending" 的任务
2. 将该任务状态改为 "in_progress"
3. 实现该任务
4. 运行 ./scripts/verify.sh 验证
5. 更新 Task.json（completed/failed/blocked）和 progress.txt
6. 执行 git add 和 git commit

注意：只处理一个任务，完成后停止。输出任务ID和结果。
'''


def ensure_control_dir():
    """确保控制目录存在"""
    CONTROL_DIR.mkdir(exist_ok=True)


def log(message: str, level: str = "INFO"):
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    colors = {"INFO": "\033[34m", "SUCCESS": "\033[32m", "WARN": "\033[33m", "ERROR": "\033[31m"}
    nc = "\033[0m"
    print(f"{colors.get(level, '')}{timestamp} [{level}] {message}{nc}")

    # 同时写入状态文件
    update_status({"last_log": f"[{level}] {message}", "last_update": timestamp})


def update_status(data: dict):
    """更新状态文件"""
    ensure_control_dir()
    status = {}
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except:
            pass
    status.update(data)
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def get_status() -> dict:
    """获取状态"""
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {}


def load_tasks():
    """加载任务"""
    try:
        with open(CONFIG["task_file"], "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"tasks": []}


def get_pending_count():
    """获取待处理任务数"""
    data = load_tasks()
    return len([t for t in data.get("tasks", []) if t.get("status") in ["pending", "in_progress"]])


def get_blocked_count():
    """获取阻塞任务数"""
    data = load_tasks()
    return len([t for t in data.get("tasks", []) if t.get("status") == "blocked"])


def run_claude():
    """运行一次 Claude"""
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", AGENT_PROMPT],
            capture_output=True,
            text=True,
            timeout=CONFIG["claude_timeout"],
            cwd=os.getcwd()
        )
        return result.returncode == 0, result.stdout[-1500:] if result.stdout else ""
    except subprocess.TimeoutExpired:
        return False, "执行超时"
    except FileNotFoundError:
        return False, "未找到 claude 命令"
    except Exception as e:
        return False, str(e)


def daemon_loop():
    """后台守护循环"""
    ensure_control_dir()

    # 写入 PID
    PID_FILE.write_text(str(os.getpid()))

    # 清理旧的控制文件
    STOP_FILE.unlink(missing_ok=True)
    PAUSE_FILE.unlink(missing_ok=True)

    update_status({
        "state": "running",
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(),
        "loop_count": 0
    })

    log("后台执行器已启动", "SUCCESS")
    log(f"PID: {os.getpid()}")
    log(f"每 {CONFIG['loop_delay_seconds']} 秒执行一轮任务")
    log("你现在可以在另一个终端使用 Claude Code 了！")
    print()

    consecutive_failures = 0
    loop_count = 0

    while True:
        # 检查停止
        if STOP_FILE.exists():
            log("收到停止信号", "WARN")
            update_status({"state": "stopped"})
            break

        # 检查暂停
        if PAUSE_FILE.exists():
            log("已暂停，等待恢复...", "WARN")
            update_status({"state": "paused"})
            time.sleep(5)
            continue

        # 检查阻塞任务
        if get_blocked_count() > 0:
            log("存在阻塞任务，暂停执行", "WARN")
            update_status({"state": "blocked"})
            time.sleep(30)
            continue

        # 检查是否还有任务
        pending = get_pending_count()
        if pending == 0:
            log("所有任务已完成！", "SUCCESS")
            update_status({"state": "completed"})
            break

        loop_count += 1
        log(f"===== 循环 #{loop_count} (剩余 {pending} 个任务) =====")
        update_status({"state": "running", "loop_count": loop_count, "pending_tasks": pending})

        # 执行 Claude
        success, output = run_claude()

        if success:
            consecutive_failures = 0
            log("任务执行成功", "SUCCESS")
            if output:
                print(f"  输出: {output[:200]}...")
        else:
            consecutive_failures += 1
            log(f"执行失败 ({consecutive_failures}/{CONFIG['max_consecutive_failures']}): {output}", "ERROR")

            if consecutive_failures >= CONFIG["max_consecutive_failures"]:
                log("连续失败过多，停止执行", "ERROR")
                update_status({"state": "error", "error": "连续失败过多"})
                break

        # 延迟
        log(f"等待 {CONFIG['loop_delay_seconds']} 秒...")
        time.sleep(CONFIG["loop_delay_seconds"])

    log(f"执行器退出，共运行 {loop_count} 轮")
    PID_FILE.unlink(missing_ok=True)


def cmd_start():
    """启动命令"""
    ensure_control_dir()

    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        print(f"执行器可能已在运行 (PID: {pid})")
        print("如果确定没有运行，请先执行: python background_agent.py stop")
        return

    print("=" * 50)
    print("  后台任务执行器")
    print("=" * 50)
    print()
    print("提示：")
    print("  - 执行器将在此终端运行")
    print("  - 打开另一个终端使用 Claude Code")
    print("  - 使用 'python background_agent.py stop' 停止")
    print()

    daemon_loop()


def cmd_status():
    """状态命令"""
    status = get_status()
    if not status:
        print("执行器未运行")
        return

    print("=" * 40)
    print("  后台执行器状态")
    print("=" * 40)
    for k, v in status.items():
        print(f"  {k}: {v}")
    print()

    # 显示任务概览
    data = load_tasks()
    tasks = data.get("tasks", [])
    status_count = {}
    for t in tasks:
        s = t.get("status", "unknown")
        status_count[s] = status_count.get(s, 0) + 1

    print("任务概览:")
    for s, c in sorted(status_count.items()):
        print(f"  {s}: {c}")


def cmd_pause():
    """暂停命令"""
    ensure_control_dir()
    PAUSE_FILE.touch()
    print("已发送暂停信号（将在当前任务完成后暂停）")


def cmd_resume():
    """恢复命令"""
    PAUSE_FILE.unlink(missing_ok=True)
    print("已发送恢复信号")


def cmd_stop():
    """停止命令"""
    ensure_control_dir()
    STOP_FILE.touch()
    PID_FILE.unlink(missing_ok=True)
    print("已发送停止信号")


def main():
    parser = argparse.ArgumentParser(description="后台任务执行器")
    parser.add_argument("command", choices=["start", "status", "pause", "resume", "stop"],
                        help="命令: start/status/pause/resume/stop")

    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "status": cmd_status,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "stop": cmd_stop,
    }

    commands[args.command]()


if __name__ == "__main__":
    main()
