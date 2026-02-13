# Long-Running Agent Harness

一套可跨无限次会话持续推进的软件开发工作流系统。

## 快速开始

```bash
# 1. 初始化环境
./init.sh

# 2. 运行验证
./scripts/verify.sh

# 3. 启动无限循环运行器（二选一）
./run_forever.sh      # Bash 版本
python agent_loop.py  # Python 版本
```

## 核心文件

| 文件 | 用途 |
|------|------|
| `CLAUDE.md` | 开发 SOP，所有 Agent 的行为规范 |
| `Task.json` | 任务列表，唯一权威任务源 |
| `progress.txt` | 跨会话工作日志 |
| `init.sh` | 环境初始化脚本 |
| `scripts/verify.sh` | 端到端验证脚本 |
| `run_forever.sh` | Bash 无限循环运行器 |
| `agent_loop.py` | Python 无限循环运行器 |

## 工作流程

每轮会话遵循 6 步流程：

1. **初始化环境** - 运行 `init.sh`
2. **领取任务** - 从 `Task.json` 选择一个 pending 任务
3. **开发实现** - 只围绕当前任务做改动
4. **测试验证** - 运行 `scripts/verify.sh`
5. **更新状态** - 更新 `Task.json` 和 `progress.txt`
6. **Git 提交** - 产生清晰的 commit

## 安全刹车

```bash
# 创建 STOP 文件，运行器会在下一轮循环时自动停止
touch STOP

# 删除 STOP 文件以恢复运行
rm STOP
```

## 人工介入

当任务状态变为 `blocked` 时，查看 `progress.txt` 中的"人工介入请求"获取详情。

## 任务状态

| 状态 | 含义 |
|------|------|
| `pending` | 未开始，可被领取 |
| `in_progress` | 进行中 |
| `completed` | 已完成 |
| `failed` | 失败，需分析后重试 |
| `blocked` | 阻塞，需人工介入 |

## 查看进度

```bash
# 查看任务概览
cat Task.json | python -m json.tool

# 查看工作日志
tail -50 progress.txt

# 查看运行器日志
tail -50 runner.log
```
