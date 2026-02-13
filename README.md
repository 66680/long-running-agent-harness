# Long-Running Agent Harness v2.0

一套可跨无限次会话持续推进的软件开发工作流系统。

## v2.0 新特性

- **严格状态机**：父进程独占调度权，子进程不可自选任务
- **文件锁**：跨平台原子读写，防止并发损坏
- **租约机制**：lease 过期自动回收，防止任务永久卡住
- **verify gate**：验证失败不会被标记为 completed
- **可审计**：结构化日志，完整历史记录

## 快速开始

### 方式一：手动会话循环（推荐新手）

每次新会话时说 "继续" 或 "开始执行"，Claude 会自动领取并执行下一个任务。

### 方式二：自动化任务循环（推荐）

使用 `auto_task_runner.py` 实现真正的自动化，每个任务在独立的 Claude 进程中执行（干净上下文）。

```bash
# 查看当前状态
python auto_task_runner.py --status

# 执行一个任务
python auto_task_runner.py

# 循环执行直到完成
python auto_task_runner.py --loop

# 执行指定数量的任务
python auto_task_runner.py --count 5

# 只显示下一个任务（不执行）
python auto_task_runner.py --dry-run

# 回收过期租约
python auto_task_runner.py --reclaim
```

**高级选项：**
```bash
# 限制 Claude 最大轮次（防止无限循环）
python auto_task_runner.py --loop --max-turns 30

# 设置超时时间
python auto_task_runner.py --loop --timeout 600

# 设置租约 TTL（秒）
python auto_task_runner.py --loop --lease-ttl 1800
```

### 方式三：完全自动化（无人值守）

```bash
# 后台运行，输出到日志文件
nohup python auto_task_runner.py --loop > runner.log 2>&1 &

# 查看日志
tail -f runner.log

# 停止
touch STOP
```

## 如何拆分任务

告诉我你的需求，我会帮你拆分。示例：

```
需求: "做一个用户认证系统"

拆分结果:
- task-001: 设计用户数据模型 (User schema)
- task-002: 实现用户注册 API (/api/register)
- task-003: 实现用户登录 API (/api/login)
- task-004: 实现 JWT token 生成和验证
- task-005: 添加认证中间件
- task-006: 编写单元测试
- task-007: 编写集成测试
- task-008: 添加密码重置功能
```

## 核心文件

| 文件 | 用途 |
|------|------|
| `CLAUDE.md` | 开发 SOP，AI 的行为规范 |
| `Task.json` | 任务列表（v2.0 schema，唯一权威源） |
| `progress.txt` | 跨会话工作日志（结构化格式） |
| `auto_task_runner.py` | 状态机驱动的任务运行器 |
| `lib/` | 核心模块（文件锁、状态机、提示词、日志） |
| `init.sh` | 环境初始化脚本 |
| `scripts/verify.sh` | 端到端验证脚本 |

## 项目结构

```
your-project/
├── CLAUDE.md              # 开发规范
├── Task.json              # 任务列表（v2.0 schema）
├── progress.txt           # 工作日志
├── auto_task_runner.py    # 状态机驱动的任务运行器
├── lib/
│   ├── __init__.py
│   ├── file_lock.py       # 跨平台文件锁
│   ├── state_machine.py   # 状态机
│   ├── prompts.py         # 子进程提示词
│   └── progress_logger.py # 结构化日志
├── init.sh
└── scripts/
    └── verify.sh
```

## 工作流程（v2.0）

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

## 任务状态

| 状态 | 含义 | 下一步 |
|------|------|--------|
| `pending` | 未开始 | 可被领取 |
| `in_progress` | 进行中（有 lease） | 当前正在处理 |
| `completed` | 已完成（终态） | 无需处理 |
| `failed` | 失败 | 自动重试（如果 < max_attempts） |
| `blocked` | 阻塞 | 需要人工介入 |
| `abandoned` | 放弃（lease 过期） | 自动重试 |
| `canceled` | 取消（终态） | 无需处理 |

## 安全刹车

```bash
# 立即停止（当前任务完成后退出）
touch STOP

# 暂停执行（删除后恢复）
touch PAUSE

# 恢复运行
rm STOP
rm PAUSE
```

## 人工介入

当任务状态变为 `blocked` 时：

1. 查看 `progress.txt` 中的 "Human Help Packet"
2. 根据提供的选项做出决策
3. 更新 Task.json（将状态改为 pending 以重试，或 canceled 以跳过）
4. 删除 STOP 文件继续运行

## 查看进度

```bash
# 任务概览
python auto_task_runner.py --status

# 任务详情
cat Task.json | python -m json.tool

# 工作日志
tail -50 progress.txt

# 运行器日志
tail -50 runner.log
```

## Task.json v2.0 Schema

```json
{
  "version": "2.0",
  "config": {
    "lease_ttl_seconds": 900,
    "max_attempts": 3,
    "verify_required": true
  },
  "tasks": [{
    "id": "task-001",
    "description": "任务描述",
    "status": "pending",
    "depends_on": [],
    "claim": null,
    "result": null,
    "history": [],
    "notes": ""
  }]
}
```

## 最佳实践

1. **任务粒度**：每个任务应该能在一次会话内完成（15-30分钟）
2. **依赖关系**：使用 `depends_on` 字段明确任务依赖
3. **验证优先**：确保 `verify.sh` 能检测任务是否真正完成
4. **及时提交**：每完成一个任务就 commit，保持可回滚
5. **日志详细**：在 progress.txt 中记录足够的上下文
6. **租约管理**：定期运行 `--reclaim` 回收过期租约

## 运行验收测试

```bash
# 验证状态机模块
python -c "from lib.state_machine import *; print('State machine OK')"

# 验证文件锁模块
python -c "from lib.file_lock import *; print('File lock OK')"

# 查看当前状态
python auto_task_runner.py --status

# 回收过期租约
python auto_task_runner.py --reclaim
```

## 查看 runs/ 归档

每次任务执行的原始输出都会保存到 `runs/` 目录：

```bash
# 列出所有归档
ls runs/

# 查看特定运行的输出
cat runs/run-20250213-160000-abc123.json | python -m json.tool
```

归档内容包括：
- `run_id`: 运行 ID
- `timestamp`: 时间戳
- `stdout`: 标准输出
- `stderr`: 标准错误
- `parsed_result`: 解析的结果 JSON

## 处理 blocked 任务 (Human Help Packet)

当任务状态变为 `blocked` 时：

1. 查看 `progress.txt` 中的 "Human Help Packet"
2. 检查 `runs/{run_id}.json` 获取详细输出
3. 根据阻塞原因采取行动：
   - 缺少凭证：配置环境变量后重试
   - 需要决策：做出决策后修改任务
   - 连续失败：分析原因后修复
4. 修改 Task.json 中的任务状态：
   - 改为 `pending` 以重试
   - 改为 `canceled` 以跳过
5. 删除 STOP 文件（如果存在）继续运行
