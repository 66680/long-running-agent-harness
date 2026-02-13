# Long-Running Agent Harness - 开发 SOP v2.0

> **重要**：本文件应复制到每个项目的根目录，每个项目独立维护自己的 Task.json 和 progress.txt

## 项目结构（每个项目独立）

```
your-project/
├── CLAUDE.md        # 本文件（开发规范）
├── Task.json        # 本项目的任务列表（v2.0 schema）
├── progress.txt     # 本项目的工作日志
├── init.sh          # 本项目的初始化脚本
├── lib/             # 核心模块
│   ├── __init__.py
│   ├── file_lock.py      # 跨平台文件锁
│   ├── state_machine.py  # 状态机
│   ├── prompts.py        # 子进程提示词
│   └── progress_logger.py # 结构化日志
├── scripts/
│   └── verify.sh    # 本项目的验证脚本
└── auto_task_runner.py  # 状态机驱动的任务运行器
```

---

## 状态机规范（v2.0 核心）

### 状态集合

| 状态 | 说明 | 可转移到 |
|------|------|----------|
| `pending` | 待执行 | in_progress, canceled |
| `in_progress` | 执行中（有 lease） | completed, failed, blocked, abandoned |
| `completed` | 已完成（终态） | - |
| `failed` | 失败（可重试） | pending, canceled |
| `blocked` | 阻塞（需人工） | pending, canceled |
| `abandoned` | 放弃（lease 过期） | pending, canceled |
| `canceled` | 取消（终态） | - |

### 状态转移规则

| 转移 | 触发条件 | 守卫条件 |
|------|----------|----------|
| pending → in_progress | 父进程领取 | 依赖已完成，无有效 lease |
| in_progress → completed | 子进程成功 | verify.exit_code == 0，run_id 匹配 |
| in_progress → failed | 子进程失败 | run_id 匹配 |
| in_progress → blocked | 需要人工 | run_id 匹配 |
| in_progress → abandoned | lease 过期 | 父进程回收 |
| failed → pending | 重试 | attempt < max_attempts |
| blocked → pending | 人工解决后 | 手动修改 |
| abandoned → pending | 自动重试 | attempt < max_attempts |

### 不变式（必须满足）

1. **completed 必须有 verify 证据**：verify.exit_code == 0
2. **同一时间最多一个有效 lease**：防止双重执行
3. **子进程回传 run_id 必须匹配**：防止任务漂移
4. **父进程独占调度权**：子进程不可自选任务

---

## Task.json 格式（v2.0）

```json
{
  "version": "2.0",
  "last_modified": "ISO时间戳",
  "config": {
    "lease_ttl_seconds": 900,
    "max_attempts": 3,
    "verify_required": true
  },
  "tasks": [{
    "id": "task-001",
    "description": "任务描述",
    "status": "pending|in_progress|completed|failed|blocked|canceled|abandoned",
    "depends_on": [],
    "claim": {
      "claimed_by": "runner-pid-12345",
      "run_id": "run-20250213-151000-abc123",
      "claimed_at": "ISO时间",
      "lease_expires_at": "ISO时间",
      "attempt": 1
    },
    "result": {
      "verify": { "command": "...", "exit_code": 0, "evidence": "..." },
      "git": { "commit": "abc123", "branch": "main" },
      "summary": "..."
    },
    "history": [{ "attempt": 1, "run_id": "...", "status": "failed", "error": "..." }],
    "notes": ""
  }]
}
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
3. 创建/更新当前目录的 Task.json（使用 v2.0 schema）
4. 设置合理的依赖关系（depends_on）
5. 询问用户是否开始执行

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
- 连续 3 次尝试失败（超过 max_attempts）
- 需要用户做决策

在 progress.txt 中记录 Human Help Packet。

---

## progress.txt 日志模板

```
============================================================
[时间] 事件类型: task_id
运行 ID: run_id
尝试: 1/3
状态: pending -> in_progress
描述: ...
操作: 父进程领取任务，启动子进程

[时间] COMPLETE: task_id
运行 ID: run_id
状态: in_progress -> completed
验证命令: scripts/verify.sh
验证结果: exit_code=0
验证证据: All tests passed
Git 提交: abc123
摘要: ...
耗时: 120.0秒
结果: 成功
需要人工: 否

[时间] BLOCK: task_id
运行 ID: run_id
状态: in_progress -> blocked
原因: 缺少 API Key
耗时: 30.0秒
结果: 阻塞
下一步: 等待人工介入
需要人工: 是

--- Human Help Packet ---
任务 ID: task-xxx
运行 ID: run-xxx
阻塞原因: 缺少 API Key
请检查 progress.txt 和 Task.json 了解详情
建议操作:
1. 解决阻塞问题
2. 将任务状态改为 pending 以重试
3. 或将任务状态改为 canceled 以跳过
--- End Packet ---
```

---

## STOP/PAUSE 机制

### 立即停止
```bash
touch STOP
```
创建 STOP 文件后，运行器会在当前任务完成后立即退出。

### 暂停执行
```bash
touch PAUSE
```
创建 PAUSE 文件后，运行器会进入睡眠循环，每 5 秒检查一次。删除 PAUSE 文件后恢复执行。

### 恢复执行
```bash
rm STOP   # 删除停止信号
rm PAUSE  # 删除暂停信号
```

---

## 文件修改规则

- Task.json: 通过状态机更新，使用文件锁保护
- progress.txt: 只在末尾追加，不修改历史
- 每完成一个任务必须 git commit

---

## 自动化执行模式

当通过 `auto_task_runner.py` 自动调用时，Claude 会在全新的隔离上下文中执行。

### 自动化执行流程（v2.0）

```
1. 父进程回收过期租约
2. 检查 STOP/PAUSE 信号
3. 选择下一个 pending 任务（依赖已满足）
4. 生成 run_id，领取任务（写入 claim）
5. 启动子进程，传入 task_id + run_id
6. 子进程执行任务，输出结果 JSON
7. 父进程验证 run_id 匹配
8. 父进程验证 verify.exit_code == 0
9. 更新 Task.json 状态
10. 写入 progress.txt 日志
11. git commit 提交改动
```

### 子进程输出格式要求

完成任务后，必须在最后输出 JSON 格式的结果（便于父进程解析）：

成功时：
```json
{
  "task_id": "task-xxx",
  "run_id": "run-xxx",
  "status": "completed",
  "verify": {"command": "scripts/verify.sh", "exit_code": 0, "evidence": "All tests passed"},
  "git": {"commit": "abc123"},
  "summary": "简要说明完成了什么"
}
```

失败时：
```json
{
  "task_id": "task-xxx",
  "run_id": "run-xxx",
  "status": "failed",
  "error": "失败原因",
  "needs_human": false
}
```

需要人工介入时：
```json
{
  "task_id": "task-xxx",
  "run_id": "run-xxx",
  "status": "blocked",
  "error": "阻塞原因",
  "needs_human": true
}
```

### 状态判断标准

- `completed`: 任务目标已达成，verify.exit_code == 0
- `failed`: 执行出错但可以重试（如网络问题、临时错误）
- `blocked`: 需要人工介入（如缺少凭证、需要决策、连续失败）

---

## 使用方法

```bash
# 执行一个任务
python auto_task_runner.py

# 循环执行直到完成
python auto_task_runner.py --loop

# 执行指定数量的任务
python auto_task_runner.py --count 5

# 查看当前状态
python auto_task_runner.py --status

# 只显示下一个任务
python auto_task_runner.py --dry-run

# 回收过期租约
python auto_task_runner.py --reclaim
```

---

## 故障注入验收清单

以下 6 个用例必须全部通过才能认为系统可靠：

| 用例 | 测试内容 | 预期结果 |
|------|----------|----------|
| A | 强杀子进程/中断 | Task.json 不损坏，lease 过期后回收 |
| B | verify 失败 | 任务不会 completed，记录 exit_code |
| C | 子进程输出非法 JSON | 父进程不崩溃，任务进入 failed |
| D | 双开 runner | 不会双领/双写，第二实例等待 |
| E | STOP/PAUSE | 可控停机，progress 记录事件 |
| F | run_id mismatch | 硬拒绝 completed，生成 help packet |

运行验收测试：
```bash
python -c "from lib.state_machine import *; print('State machine OK')"
python auto_task_runner.py --status
python auto_task_runner.py --reclaim
```

---

## run_id mismatch 处理规则

当子进程返回的 run_id 与 claim.run_id 不匹配时：

1. **硬拒绝**：不接受任何状态更新
2. **标记失败**：任务状态改为 failed
3. **生成 Human Help Packet**：
   - 记录期望的 run_id 和实际的 run_id
   - 写入 progress.txt
   - 可能原因：子进程漂移、重放攻击、并发冲突
4. **归档证据**：原始输出保存到 runs/{run_id}.json

---

## 租约 TTL 配置建议

- `lease_ttl_seconds` 应大于 `timeout`
- 推荐：`lease_ttl_seconds = timeout * 1.5`
- 默认值：900 秒（15 分钟）
- 如果任务可能超过 15 分钟，请调整配置

---

## 提交时机规范

子进程必须遵守以下顺序：

1. 实现任务
2. 运行 verify（scripts/verify.sh）
3. **只有 verify 通过（exit_code=0）才能 git commit**
4. 输出结果 JSON

父进程会验证 verify.exit_code，如果不为 0 则拒绝 completed 状态。
