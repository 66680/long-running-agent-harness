#!/usr/bin/env python3
"""
agent_loop.py - Python 版本的无限循环运行器
实现持续推进的 Agent 工作流，支持崩溃恢复
"""

import json
import os
import sys
import time
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

# 配置
CONFIG = {
    "max_consecutive_failures": 3,
    "loop_delay_seconds": 5,
    "log_file": "runner.log",
    "task_file": "Task.json",
    "progress_file": "progress.txt",
    "stop_file": "STOP",
    "demo_mode": True,  # 演示模式，设为 False 可无限运行
}

# 状态
state = {
    "consecutive_failures": 0,
    "loop_count": 0,
    "running": True,
}


def log(message: str, level: str = "INFO") -> None:
    """���录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}"

    # 控制台输出（带颜色）
    colors = {
        "INFO": "\033[0;34m",
        "SUCCESS": "\033[0;32m",
        "WARN": "\033[1;33m",
        "ERROR": "\033[0;31m",
    }
    nc = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}{log_line}{nc}")

    # 写入日志文件
    with open(CONFIG["log_file"], "a", encoding="utf-8") as f:
        f.write(log_line + "\n")


def load_tasks() -> Dict[str, Any]:
    """加载任务列表"""
    try:
        with open(CONFIG["task_file"], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"加载 Task.json 失败: {e}", "ERROR")
        return {"tasks": []}


def save_tasks(data: Dict[str, Any]) -> bool:
    """保存任务列表"""
    try:
        with open(CONFIG["task_file"], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"保存 Task.json 失败: {e}", "ERROR")
        return False


def update_task_status(task_id: str, status: str, notes: str = "") -> bool:
    """更新单个任务状态（最小改动原则）"""
    data = load_tasks()
    for task in data.get("tasks", []):
        if task["id"] == task_id:
            task["status"] = status
            task["last_update"] = datetime.now().isoformat()
            if notes:
                task["notes"] = notes
            break
    data["last_modified"] = datetime.now().isoformat()
    return save_tasks(data)


def append_progress(entry: str) -> None:
    """追加进度日志"""
    with open(CONFIG["progress_file"], "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def check_stop_file() -> bool:
    """检查安全刹车文件"""
    return os.path.exists(CONFIG["stop_file"])


def check_blocked_tasks() -> int:
    """检查阻塞任务数量"""
    data = load_tasks()
    blocked = [t for t in data.get("tasks", []) if t.get("status") == "blocked"]
    return len(blocked)


def get_next_task() -> Optional[Dict[str, Any]]:
    """获取下一个可领取的任务"""
    data = load_tasks()
    tasks = data.get("tasks", [])

    # 获取已完成任务的 ID
    completed_ids = {t["id"] for t in tasks if t.get("status") == "completed"}

    # 查找第一个满足条件的 pending 任务
    for task in tasks:
        if task.get("status") == "pending":
            deps = task.get("depends_on", [])
            if all(d in completed_ids for d in deps):
                return task

    return None


def all_tasks_done() -> bool:
    """检查是否所有任务都完成"""
    data = load_tasks()
    tasks = data.get("tasks", [])
    pending = [t for t in tasks if t.get("status") in ["pending", "in_progress"]]
    return len(pending) == 0


def run_init() -> bool:
    """运行初始化脚本"""
    log("运行初始化脚本...")
    try:
        result = os.system("./init.sh > /dev/null 2>&1")
        if result == 0:
            log("初始化成功", "SUCCESS")
            return True
        else:
            log("初始化失败", "ERROR")
            return False
    except Exception as e:
        log(f"初始化异常: {e}", "ERROR")
        return False


def run_verify() -> bool:
    """运行验证脚本"""
    log("运行验证脚本...")
    try:
        result = os.system("./scripts/verify.sh > /dev/null 2>&1")
        if result == 0:
            log("验证通过", "SUCCESS")
            return True
        else:
            log("验证失败", "ERROR")
            return False
    except Exception as e:
        log(f"验证异常: {e}", "ERROR")
        return False


def signal_handler(signum, frame):
    """信号处理器"""
    log("收到终止信号，正在停止...", "WARN")
    state["running"] = False


def main_loop():
    """主循环"""
    log("启动主循环...")
    print()

    while state["running"]:
        state["loop_count"] += 1
        log(f"========== 循环 #{state['loop_count']} ==========")

        # 1. 检查安全刹车
        if check_stop_file():
            log("检测到 STOP 文件，停止运行", "WARN")
            break

        # 2. 检查阻塞任务
        blocked_count = check_blocked_tasks()
        if blocked_count > 0:
            log(f"存在 {blocked_count} 个阻塞任务，需要人工介入", "WARN")
            break

        # 3. 检查是否所有任务完成
        if all_tasks_done():
            log("所有任务已完成！", "SUCCESS")
            break

        # 4. 运行初始化
        if not run_init():
            state["consecutive_failures"] += 1
            log(
                f"初始化失败 (连续失败: {state['consecutive_failures']}/{CONFIG['max_consecutive_failures']})",
                "ERROR",
            )
            if state["consecutive_failures"] >= CONFIG["max_consecutive_failures"]:
                log("连续失败次数达到上限，退出循环", "ERROR")
                break
            time.sleep(CONFIG["loop_delay_seconds"])
            continue

        # 5. 获取下一个任务
        next_task = get_next_task()
        if not next_task:
            log("没有可领取的任务（可能存在依赖阻塞）", "WARN")
            time.sleep(CONFIG["loop_delay_seconds"])
            continue

        task_id = next_task["id"]
        log(f"下一个任务: {task_id} - {next_task['description']}")

        # 6. 这里是 Agent 执行任务的位置
        # 在实际使用中，这里会调用 Claude API
        log(f">>> 等待 Agent 领取并执行任务: {task_id}")
        log(">>> 在实际部署中，这里会调用 Claude API")
        log(">>> 当前为演示模式，跳过实际执行")

        # 7. 运行验证
        if run_verify():
            state["consecutive_failures"] = 0
            log("本轮循环完成", "SUCCESS")
        else:
            state["consecutive_failures"] += 1
            log(
                f"验证失败 (连续失败: {state['consecutive_failures']}/{CONFIG['max_consecutive_failures']})",
                "ERROR",
            )
            if state["consecutive_failures"] >= CONFIG["max_consecutive_failures"]:
                log("连续失败次数达到上限，退出循环", "ERROR")
                break

        # 8. 延迟后进入下一轮
        log(f"等待 {CONFIG['loop_delay_seconds']} 秒后进入下一轮...")
        time.sleep(CONFIG["loop_delay_seconds"])

        # 演示模式：只运行一轮
        if CONFIG["demo_mode"]:
            log("演示模式：只运行一轮，退出循环", "WARN")
            break

    log(f"主循环结束，共运行 {state['loop_count']} 轮")


def main():
    """主函数"""
    print("==========================================")
    print("  Long-Running Agent Harness")
    print("  Python 无限循环运行器")
    print("==========================================")
    print()

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("按 Ctrl+C 停止运行")
    print("或创建 STOP 文件: touch STOP")
    print()

    try:
        main_loop()
    except Exception as e:
        log(f"运行器异常退出: {e}", "ERROR")
        sys.exit(1)

    print()
    log("运行器已退出")


if __name__ == "__main__":
    main()
