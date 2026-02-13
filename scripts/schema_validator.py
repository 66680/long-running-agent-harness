#!/usr/bin/env python3
"""
schema_validator.py - Task.json schema 校验

校验项:
1. JSON 可解析
2. version 字段存在且为 "2.0"
3. config 字段存在且包含必要键
4. tasks 数组存在
5. 每个 task 的 id 唯一
6. status 值在合法集合内
7. claim 字段结构正确（如果存在）
"""

import json
import sys

VALID_STATUSES = {"pending", "in_progress", "completed", "failed", "blocked", "canceled", "abandoned"}
REQUIRED_CONFIG_KEYS = {"lease_ttl_seconds", "max_attempts", "verify_required"}


def validate_task_json(file_path: str) -> tuple[bool, list[str]]:
    """
    校验 Task.json schema。

    Returns:
        (is_valid, errors)
    """
    errors = []

    # 1. JSON 可解析
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, [f"文件不存在: {file_path}"]
    except json.JSONDecodeError as e:
        return False, [f"JSON 解析错误: {e}"]

    # 2. version 字段
    if "version" not in data:
        errors.append("缺少 version 字段")
    elif data["version"] != "2.0":
        errors.append(f"version 应为 '2.0'，实际为 '{data['version']}'")

    # 3. config 字段
    if "config" not in data:
        errors.append("缺少 config 字段")
    else:
        config = data["config"]
        missing_keys = REQUIRED_CONFIG_KEYS - set(config.keys())
        if missing_keys:
            errors.append(f"config 缺少必要键: {missing_keys}")

    # 4. tasks 数组
    if "tasks" not in data:
        errors.append("缺少 tasks 字段")
    elif not isinstance(data["tasks"], list):
        errors.append("tasks 应为数组")
    else:
        tasks = data["tasks"]

        # 5. id 唯一性
        ids = [t.get("id") for t in tasks if "id" in t]
        if len(ids) != len(set(ids)):
            duplicates = [id for id in ids if ids.count(id) > 1]
            errors.append(f"存在重复的 task id: {set(duplicates)}")

        # 6. status 合法性
        for i, task in enumerate(tasks):
            if "id" not in task:
                errors.append(f"tasks[{i}] 缺少 id 字段")
                continue

            task_id = task["id"]

            if "status" not in task:
                errors.append(f"task '{task_id}' 缺少 status 字段")
            elif task["status"] not in VALID_STATUSES:
                errors.append(f"task '{task_id}' 的 status '{task['status']}' 不合法")

            # 7. claim 结构（如果存在且非 null）
            if "claim" in task and task["claim"] is not None:
                claim = task["claim"]
                required_claim_keys = {"claimed_by", "run_id", "claimed_at", "lease_expires_at", "attempt"}
                if not isinstance(claim, dict):
                    errors.append(f"task '{task_id}' 的 claim 应为对象")
                else:
                    missing_claim_keys = required_claim_keys - set(claim.keys())
                    if missing_claim_keys:
                        errors.append(f"task '{task_id}' 的 claim 缺少键: {missing_claim_keys}")

    return len(errors) == 0, errors


def main():
    file_path = sys.argv[1] if len(sys.argv) > 1 else "Task.json"
    is_valid, errors = validate_task_json(file_path)

    if is_valid:
        print("SCHEMA_OK")
        sys.exit(0)
    else:
        print("SCHEMA_ERROR")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
