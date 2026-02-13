# Long-Running Agent Harness

一套可跨无限次会话持续推进的软件开发工作流系统。

## 快速开始

### 方式一：手动会话循环（推荐新手）

每次新会话时说 "继续" 或 "开始执行"，Claude 会自动领取并执行下一个任务。

### 方式二：后台自动执行 + 前台交互（推荐）

**同时运行两个终端：**

```bash
# 终端 1：启动后台执行器
python background_agent.py start

# 终端 2：正常使用 Claude Code
claude
# 你可以继续使用 /commit, /review-pr 等 skills
```

**控制命令：**
```bash
python background_agent.py status   # 查看状态
python background_agent.py pause    # 暂停
python background_agent.py resume   # 恢复
python background_agent.py stop     # 停止
```

### 方式三：完全自动化（无人值守）

```bash
# 后台运行，输出到日志文件
nohup python background_agent.py start > agent.log 2>&1 &

# 查看日志
tail -f agent.log

# 停止
python background_agent.py stop
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
| `Task.json` | 任务列表（唯一权威源） |
| `progress.txt` | 跨会话工作日志 |
| `init.sh` | 环境初始化脚本 |
| `scripts/verify.sh` | 端到端验证脚本 |
| `claude_runner.py` | 自动化循环脚本（调用 Claude CLI） |

## 工作流程

每轮会话遵循 6 步流程：

```
1. 初始化环境     → ./init.sh
2. 领取任务       → 从 Task.json 选择 pending 任务
3. 开发实现       → 只围绕当前任务改动
4. 测试验证       → ./scripts/verify.sh
5. 更新状态       → Task.json + progress.txt
6. Git 提交       → git commit
```

## 任务状态

| 状态 | 含义 | 下一步 |
|------|------|--------|
| `pending` | 未开始 | 可被领取 |
| `in_progress` | 进行中 | 当前正在处理 |
| `completed` | 已完成 | 无需处理 |
| `failed` | 失败 | 分析后重试 |
| `blocked` | 阻塞 | 需要人工介入 |

## 安全刹车

```bash
# 创建 STOP 文件，系统会在下一轮循环时停止
touch STOP

# 删除以恢复运行
rm STOP
```

## 人工介入

当任务状态变为 `blocked` 时：

1. 查看 `progress.txt` 中的"人工介入请求"
2. 根据提供的选项做出决策
3. 更新 Task.json 或提供所需资源
4. 删除 STOP 文件继续运行

## 查看进度

```bash
# 任务概览
cat Task.json | python -m json.tool

# 工作日志
tail -50 progress.txt

# 运行器日志
tail -50 runner.log
```

## 最佳实践

1. **任务粒度**：每个任务应该能在一次会话内完成（15-30分钟）
2. **依赖关系**：使用 `depends_on` 字段明确任务依赖
3. **验证优先**：确保 `verify.sh` 能检测任务是否真正完成
4. **及时提交**：每完成一个任务就 commit，保持可回滚
5. **日志详细**：在 progress.txt 中记录足够的上下文
