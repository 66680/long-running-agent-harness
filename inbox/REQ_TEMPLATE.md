# REQ_TEMPLATE: 需求单模板

## Status
pending

## 项目要求

（在此描述项目背景、技术栈、约束条件等。这部分内容将被合并到 CLAUDE.md 的 "## 项目要求" 章节。）

示例：
- 项目使用 Python 3.11+
- 遵循 PEP 8 代码风格
- 所有公共函数必须有 docstring
- 测试覆盖率要求 80%+

## 运行参数

```yaml
# 可选配置，将合并到 Task.json config
lease_ttl_seconds: 900
max_attempts: 3
verify_required: true
```

## Task Seeds

### TASK-001: 第一个任务标题
- goal: 实现 XX 功能
- acceptance: 通过 YY 测试
- constraints: 不修改 ZZ 文件
- verification: pytest tests/test_xx.py
- scope: src/module/
- priority: P0
- depends_on: []

### TASK-002: 第二个任务标题
- goal: 实现 AA 功能
- acceptance: 通过 BB 测试
- constraints: 保持向后兼容
- verification: pytest tests/test_aa.py
- scope: src/other/
- priority: P1
- depends_on: [TASK-001]

---

## 使用说明

1. 复制此模板为 `REQ_你的项目名.md`
2. 填写项目要求、运行参数、Task Seeds
3. 运行 `python auto_task_runner.py --intake inbox/REQ_你的项目名.md`
4. 或启用监听模式 `python auto_task_runner.py --watch-inbox inbox --loop`

## Task Seed 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| goal | 是 | 任务目标，描述要实现什么 |
| acceptance | 是 | 验收标准，如何判断任务完成 |
| constraints | 否 | 约束条件，不能做什么 |
| verification | 否 | 验证命令，如 pytest/go test |
| scope | 否 | 作用范围，涉及哪些文件/目录 |
| priority | 否 | 优先级 P0/P1/P2，默认 P1 |
| depends_on | 否 | 依赖的任务 ID 列表 |

## 注意事项

- Task ID 必须唯一，冲突时会自动添加后缀
- depends_on 中的任务必须在同一 REQ 或已存在于 Task.json
- 处理完成后，REQ 文件会被移动到 inbox/processed/
