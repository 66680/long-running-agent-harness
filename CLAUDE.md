# Long-Running Agent Harness - 开发 SOP

> **重要**：本文件应复制到每个项目的根目录，每个项目独立维护自己的 Task.json 和 progress.txt

## 项目结构（每个项目独立）

```
your-project/
├── CLAUDE.md        # 本文件（开发规范）
├── Task.json        # 本项目的任务列表
├── progress.txt     # 本项目的工作日志
├── init.sh          # 本项目的初始化脚本
├── scripts/
│   └── verify.sh    # 本项目的验证脚本
└── ... (项目代码)
```

---

## 会话开始指令

当用户说以下任何一句时，执行"会话开始流程"：
- "继续"
- "开始"
- "下一个任务"
- "执行任务"

### 会话开始流程（必须按顺序执行）

```
1. 读取当前目录的 CLAUDE.md（本文件）
2. 读取当前目录的 progress.txt 了解历史
3. 读取当前目录的 Task.json 了解任务状态
4. 运行 git log --oneline -5 查看最近提交
5. 运行 ./init.sh 初始化环境（如果存在）
6. 从 Task.json 领取一个 pending 任务
7. 执行任务（使用所有可用工具）
8. 更新 Task.json 和 progress.txt
9. git commit 提交改动
10. 询问用户是否继续下一个任务
```

---

## 任务拆分指令

当用户说"帮我拆分任务：XXX"时：

1. 分析需求，拆分成 5-15 个独立任务
2. 每个任务应该能在 15-30 分钟内完成
3. 创建/更新当前目录的 Task.json
4. 设置合理的依赖关系（depends_on）
5. 询问用户是否开始执行

---

## Task.json 格式

```json
{
  "project": "项目名称",
  "version": "1.0",
  "last_modified": "ISO时间戳",
  "tasks": [
    {
      "id": "task-001",
      "description": "任务描述",
      "status": "pending|in_progress|completed|failed|blocked",
      "last_update": "ISO时间戳",
      "depends_on": ["task-xxx"],
      "notes": "执行备注"
    }
  ]
}
```

### 状态说明
- `pending`: 待执行
- `in_progress`: 执行中
- `completed`: 已完成
- `failed`: 失败（可重试）
- `blocked`: 阻塞（需人工介入）

---

## 开发时可用的工具

执行任务时应主动使用：

| 工具 | 用途 |
|------|------|
| `/plan` | 复杂任务先规划 |
| `/tdd` | 测试驱动开发 |
| `/commit` | 智能提交 |
| `/security-review` | 安全检查 |
| MCP 工具 | 浏览器、数据库等 |
| 子代理 | code-reviewer, planner 等 |

---

## 人工介入

当遇到以下情况时，将任务标记为 `blocked` 并停止：
- 缺少 API Key 或凭证
- 连续 3 次尝试失败
- 需要用户做决策

在 progress.txt 中记录详细的求助信息。

---

## 文件修改规则

- Task.json: 只修改单个任务的 status/notes/last_update
- progress.txt: 只在末尾追加，不修改历史
- 每完成一个任务必须 git commit
