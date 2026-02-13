"""
intake_prompts.py - Intake 子进程提示词模板

为 Intake 处理生成子进程提示词。
"""


def build_intake_prompt(
    req_id: str,
    run_id: str,
    req_content: str,
    task_json_path: str = "Task.json",
    claude_md_path: str = "CLAUDE.md",
) -> str:
    """
    构建 Intake 子进程提示词。

    Args:
        req_id: REQ ID
        run_id: 运行 ID
        req_content: REQ 文件内容
        task_json_path: Task.json 路径
        claude_md_path: CLAUDE.md 路径

    Returns:
        完整的提示词
    """
    return f'''你正在处理一个需求单（REQ）。

## 重要约束（必须遵守）

1. 你只能处理 req_id={req_id}
2. 你的 run_id={run_id}（必须在输出中回传）
3. 不得处理其他 REQ 或 pending 任务
4. 不得自行领取任务
5. 不得修改 Task.json 中已存在的任务

## REQ 内容

```markdown
{req_content}
```

## 执行步骤

1. 解析 REQ 中的项目要求、运行参数、Task Seeds
2. 将项目要求合并到 {claude_md_path}（最小 diff，在 "## 项目要求" 章节插入）
3. 将运行参数合并到 {task_json_path} config（只更新 REQ 中出现的字段）
4. 将 Task Seeds 转换为 {task_json_path} tasks：
   - 每个任务必须包含: id, description, status=pending, depends_on
   - description 应包含: goal, acceptance, constraints
   - id 必须唯一，冲突时自动改名并在 notes 说明
5. 运行 scripts/verify.sh 验证
6. git add 相关文件并 git commit
7. 将 REQ 移动到 inbox/processed/

## Task Seeds 转换规则

每个 Task Seed 格式：
```
### TASK-ID: 任务标题
- goal: 目标
- acceptance: 验收标准
- constraints: 约束条件
- verification: 验证命令
- scope: 作用范围
- priority: 优先级
- depends_on: 依赖任务列表
```

转换为 Task.json 格式：
```json
{{
  "id": "TASK-ID",
  "description": "任务标题\\n目标: ...\\n验收标准: ...\\n约束: ...",
  "status": "pending",
  "depends_on": [...],
  "claim": null,
  "result": null,
  "history": [],
  "notes": "验证命令: ...\\n范围: ...\\n优先级: ..."
}}
```

## 输出格式（必须遵守）

完成后，在最后输出以下 JSON（必须是有效 JSON）：

```json
{{
  "req_id": "{req_id}",
  "run_id": "{run_id}",
  "status": "completed|failed|blocked",
  "config_updates": {{"key": "value"}},
  "tasks_added": ["task-id-1", "task-id-2"],
  "claude_md_patch_summary": "添加了 XX 章节",
  "verify": {{"command": "scripts/verify.sh", "exit_code": 0, "evidence": "..."}},
  "git": {{"commit": "abc123", "branch": "master"}},
  "error": "",
  "needs_human": false
}}
```

## 状态判断标准

- `completed`: REQ 处理成功，所有任务已添加，verify 通过，git commit 成功
- `failed`: 处理出错但可以重试（如临时错误）
- `blocked`: 需要人工介入（如 REQ 格式错误、缺少必要信息）

## 注意事项

- 不要修改已存在的任务
- 如果 Task ID 冲突，自动添加后缀（如 TASK-001 -> TASK-001-1）
- 保持 Task.json 的 version 和其他元数据不变
- 只更新 config 中 REQ 指定的字段
'''


def build_intake_validation_prompt(req_content: str) -> str:
    """
    构建 REQ 验证提示词（用于预检）。

    Args:
        req_content: REQ 文件内容

    Returns:
        验证提示词
    """
    return f'''请验证以下 REQ 文件格式是否正确。

## REQ 内容

```markdown
{req_content}
```

## 验证规则

1. 必须有标题行：`# REQ_XXX: 标题`
2. 必须有 `## Task Seeds` 章节
3. 每个 Task Seed 必须有：
   - `### TASK-ID: 标题` 格式的标题
   - `- goal: ...` 目标
   - `- acceptance: ...` 验收标准
4. `## 运行参数` 章节（如果有）必须是有效 YAML

## 输出格式

```json
{{
  "valid": true|false,
  "errors": ["错误1", "错误2"],
  "warnings": ["警告1"],
  "task_count": 3
}}
```
'''
