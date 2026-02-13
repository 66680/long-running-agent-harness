#!/bin/bash
# init.sh - 环境初始化脚本
# 每次会话开始时运行，确保环境干净可用

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  Long-Running Agent Harness - 初始化"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_ok() {
    echo -e "${GREEN}[OK]${NC} $1"
}

check_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

check_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    exit 1
}

# 1. 检查必要文件
echo "1. 检查必要文件..."
if [ -f "CLAUDE.md" ]; then
    check_ok "CLAUDE.md 存在"
else
    check_fail "CLAUDE.md 不存在"
fi

if [ -f "Task.json" ]; then
    check_ok "Task.json 存在"
else
    check_fail "Task.json 不存在"
fi

if [ -f "progress.txt" ]; then
    check_ok "progress.txt 存在"
else
    check_fail "progress.txt 不存在"
fi

# 2. 检查 Git 状态
echo ""
echo "2. 检查 Git 状态..."
if [ -d ".git" ]; then
    check_ok "Git 仓库已初始化"

    # 检查是否有未提交的更改
    if git diff --quiet && git diff --staged --quiet; then
        check_ok "工作区干净"
    else
        check_warn "存在未提交的更改"
        git status --short
    fi
else
    check_warn "Git 仓库未初始化，正在初始化..."
    git init
    check_ok "Git 仓库已初始化"
fi

# 3. 检查 STOP 文件（安全刹车）
echo ""
echo "3. 检查安全刹车..."
if [ -f "STOP" ]; then
    check_warn "检测到 STOP 文件，系统处于停止状态"
    echo "如需继续运行，请删除 STOP 文件: rm STOP"
else
    check_ok "无 STOP 文件，系统可正常运行"
fi

# 4. 检查 Task.json 格式
echo ""
echo "4. 验证 Task.json 格式..."
# 优先使用 python，因为 Windows 上 python3 可能有问题
if command -v python &> /dev/null; then
    python -c "import json; json.load(open('Task.json', encoding='utf-8'))" 2>/dev/null && check_ok "Task.json 格式正确" || check_fail "Task.json 格式错误"
elif command -v python3 &> /dev/null; then
    python3 -c "import json; json.load(open('Task.json', encoding='utf-8'))" 2>/dev/null && check_ok "Task.json 格式正确" || check_fail "Task.json 格式错误"
else
    check_warn "Python 不可用，跳过 JSON 验证"
fi

# 5. 显示任务概览
echo ""
echo "5. 任务概览..."
# 优先使用 python
if command -v python &> /dev/null; then
    PYTHON_CMD="python"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD=""
fi

if [ -n "$PYTHON_CMD" ]; then
    $PYTHON_CMD << 'EOF'
import json

with open('Task.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

tasks = data.get('tasks', [])
status_count = {}
for task in tasks:
    status = task.get('status', 'unknown')
    status_count[status] = status_count.get(status, 0) + 1

print(f"  总任务数: {len(tasks)}")
for status, count in sorted(status_count.items()):
    print(f"  - {status}: {count}")

# 显示下一个可领取的任务
pending_tasks = [t for t in tasks if t.get('status') == 'pending']
if pending_tasks:
    # 检查依赖
    completed_ids = {t['id'] for t in tasks if t.get('status') == 'completed'}
    for task in pending_tasks:
        deps = task.get('depends_on', [])
        if all(d in completed_ids for d in deps):
            print(f"\n  下一个可领取任务: {task['id']}")
            print(f"  描述: {task['description']}")
            break
EOF
else
    echo "  (Python 不可用，无法显示任务概览)"
fi

# 6. 检查验证脚本
echo ""
echo "6. 检查验证脚本..."
if [ -f "scripts/verify.sh" ]; then
    check_ok "scripts/verify.sh 存在"
    if [ -x "scripts/verify.sh" ]; then
        check_ok "scripts/verify.sh 可执行"
    else
        check_warn "scripts/verify.sh 不可执行，正在添加执行权限..."
        chmod +x scripts/verify.sh
        check_ok "已添加执行权限"
    fi
else
    check_warn "scripts/verify.sh 不存在（需要创建）"
fi

echo ""
echo "=========================================="
echo "  初始化完成"
echo "=========================================="
echo ""
echo "下一步操作："
echo "  1. 读取 progress.txt 了解历史进度"
echo "  2. 从 Task.json 领取一个任务"
echo "  3. 开始开发"
echo ""
