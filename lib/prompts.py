"""
prompts.py - 子进程提示词模板

生成严格限制的提示词，确保子进程：
1. 只处理指定的 task_id
2. 必须回传匹配的 run_id
3. 不得自行领取其他任务
4. 不得修改 Task.json 的状态字段
"""

from typing import Optional


def build_task_prompt(
    task_id: str,
    run_id: str,
    task_description: str,
    depends_on: list[str] = None,
    attempt: int = 1,
    max_attempts: int = 3,
    verify_command: Optional[str] = None,
) -> str:
    """
    构建子进程任务提示词。

    Args:
        task_id: 任务 ID
        run_id: 运行 ID（必须在输出中回传）
        task_description: 任务描述
        depends_on: 依赖的任务 ID 列表
        attempt: 当前尝试次数
        max_attempts: 最大尝试次数
        verify_command: 验证命令（可选）

    Returns:
        格式化的提示词
    """
    deps_info = ""
    if depends_on:
        deps_info = f"\n依赖任务（已完成）: {', '.join(depends_on)}"

    verify_info = ""
    if verify_command:
        verify_info = f"""
## 验证要求

完成实现后，必须运行验证命令：
```bash
{verify_command}
```

验证必须通过（exit_code == 0）才能标记为 completed。
"""

    return f'''你正在执行一个长期运行项目的单个任务。

## 重要约束（必须遵守）

1. 你只能处理 task_id={task_id}
2. 你的 run_id={run_id}（必须在输出中回传）
3. 不得领取或处理其他任务
4. 不得直接修改 Task.json 的 status/claim/result 字段
5. 这是第 {attempt}/{max_attempts} 次尝试

## 任务信息

任务 ID: {task_id}
运行 ID: {run_id}
描述: {task_description}{deps_info}

## 执行步骤

1. 读取 CLAUDE.md 了解开发规范
2. 读取 progress.txt 了解历史进度（如果存在）
3. 运行 git log --oneline -5 查看最近提交
4. 实现任务（使用所有可用的 skills 和 MCP 工具）
5. 运行验证（如果有 scripts/verify.sh）
6. 在 progress.txt 末尾追加工作记录
7. git add 相关文件并 git commit
{verify_info}
## 可用工具

实现任务时请主动使用：
- /plan - 复杂任务先规划
- /tdd - 测试驱动开发
- /commit - 智能提交
- /security-review - 安全检查
- MCP 工具 - 根据需要
- 子代理 - code-reviewer, planner, build-error-resolver 等

## 输出要求（必须遵守）

完成后，在最后一行输出 JSON（便于父进程解析）：

成功时：
```json
{{"task_id": "{task_id}", "run_id": "{run_id}", "status": "completed", "verify": {{"command": "scripts/verify.sh", "exit_code": 0, "evidence": "All tests passed"}}, "git": {{"commit": "abc123"}}, "summary": "简要说明完成了什么"}}
```

失败时：
```json
{{"task_id": "{task_id}", "run_id": "{run_id}", "status": "failed", "error": "失败原因", "needs_human": false}}
```

需要人工介入时：
```json
{{"task_id": "{task_id}", "run_id": "{run_id}", "status": "blocked", "error": "阻塞原因", "needs_human": true}}
```

注意：
- task_id 和 run_id 必须与上面给定的值完全匹配
- status 只能是 completed/failed/blocked 之一
- completed 必须包含 verify 字段
'''


def build_status_check_prompt() -> str:
    """
    构建状态检查提示词（用于 --status 模式）。

    Returns:
        状态检查提示词
    """
    return '''请检查当前项目状态：

1. 读取 Task.json 统计任务状态
2. 读取 progress.txt 查看最近进度
3. 运行 git log --oneline -5 查看最近提交
4. 检查是否有 STOP 或 PAUSE 文件

输出格式：
```json
{
  "total": 10,
  "pending": 3,
  "in_progress": 1,
  "completed": 5,
  "failed": 1,
  "blocked": 0,
  "next_task": "task-xxx",
  "stop_file": false,
  "pause_file": false
}
```
'''


def build_recovery_prompt(task_id: str, run_id: str, error: str) -> str:
    """
    构建恢复提示词（用于任务失败后的诊断）。

    Args:
        task_id: 任务 ID
        run_id: 运行 ID
        error: 错误信息

    Returns:
        恢复提示词
    """
    return f'''任务 {task_id} (run_id={run_id}) 执行失败，需要诊断。

错误信息：
{error}

请执行以下步骤：

1. 读取 progress.txt 查看失败时的上下文
2. 检查相关代码文件
3. 分析失败原因
4. 提出修复建议

输出格式：
```json
{{
  "task_id": "{task_id}",
  "run_id": "{run_id}",
  "diagnosis": "诊断结果",
  "root_cause": "根本原因",
  "fix_suggestion": "修复建议",
  "can_auto_fix": true/false
}}
```
'''
