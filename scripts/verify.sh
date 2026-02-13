#!/bin/bash
# verify.sh - 最小端到端验证脚本
# 用于验证系统状态和任务完成情况

# 不使用 set -e，因为我们需要手动控制退出

echo "=========================================="
echo "  验证脚本 - 端到端测试"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    WARN_COUNT=$((WARN_COUNT + 1))
}

# 测试 1: 核心文件存在性
echo "测试 1: 核心文件存在性"
echo "----------------------------------------"

[ -f "CLAUDE.md" ] && pass "CLAUDE.md 存在" || fail "CLAUDE.md 不存在"
[ -f "Task.json" ] && pass "Task.json 存在" || fail "Task.json 不存在"
[ -f "progress.txt" ] && pass "progress.txt 存在" || fail "progress.txt 不存在"
[ -f "init.sh" ] && pass "init.sh 存在" || fail "init.sh 不存在"

echo ""

# 测试 2: Task.json 格式验证
echo "测试 2: Task.json 格式验证"
echo "----------------------------------------"

PYTHON_CMD=""
if command -v python &> /dev/null; then
    PYTHON_CMD="python"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
fi

if [ -n "$PYTHON_CMD" ]; then
    if $PYTHON_CMD -c "import json; json.load(open('Task.json', encoding='utf-8'))" 2>/dev/null; then
        pass "Task.json 是有效的 JSON"
    else
        fail "Task.json 不是有效的 JSON"
    fi

    # 检查必要字段
    $PYTHON_CMD << 'EOF'
import json
import sys

with open('Task.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

errors = []

if 'tasks' not in data:
    errors.append("缺少 'tasks' 字段")
else:
    for i, task in enumerate(data['tasks']):
        required = ['id', 'description', 'status', 'last_update']
        for field in required:
            if field not in task:
                errors.append(f"任务 {i} 缺少 '{field}' 字段")

        valid_status = ['pending', 'in_progress', 'completed', 'failed', 'blocked']
        if task.get('status') not in valid_status:
            errors.append(f"任务 {task.get('id', i)} 状态无效: {task.get('status')}")

if errors:
    for e in errors:
        print(f"FIELD_ERROR: {e}")
    sys.exit(1)
else:
    print("FIELD_OK")
EOF
    if [ $? -eq 0 ]; then
        pass "Task.json 字段完整"
    else
        fail "Task.json 字段不完整"
    fi
else
    warn "Python 不可用，跳过 JSON 深度验证"
fi

echo ""

# 测试 3: Git 状态
echo "测试 3: Git 状态"
echo "----------------------------------------"

if [ -d ".git" ]; then
    pass "Git 仓库已初始化"

    # 检查是否有提交
    if git rev-parse HEAD &>/dev/null; then
        pass "存在 Git 提交历史"
        COMMIT_COUNT=$(git rev-list --count HEAD)
        echo "    提交数量: $COMMIT_COUNT"
    else
        warn "尚无 Git 提交"
    fi
else
    fail "Git 仓库未初始化"
fi

echo ""

# 测试 4: 脚本可执行性
echo "测试 4: 脚本可执行性"
echo "----------------------------------------"

if [ -x "init.sh" ]; then
    pass "init.sh 可执行"
else
    warn "init.sh 不可执行"
fi

if [ -f "run_forever.sh" ]; then
    if [ -x "run_forever.sh" ]; then
        pass "run_forever.sh 可执行"
    else
        warn "run_forever.sh 不可执行"
    fi
else
    warn "run_forever.sh 尚未创建"
fi

echo ""

# 测试 5: progress.txt 格式
echo "测试 5: progress.txt 格式"
echo "----------------------------------------"

if [ -f "progress.txt" ]; then
    LINE_COUNT=$(wc -l < progress.txt)
    if [ "$LINE_COUNT" -gt 5 ]; then
        pass "progress.txt 有内容 ($LINE_COUNT 行)"
    else
        warn "progress.txt 内容较少 ($LINE_COUNT 行)"
    fi
else
    fail "progress.txt 不存在"
fi

echo ""

# 汇总
echo "=========================================="
echo "  验证结果汇总"
echo "=========================================="
echo ""
echo -e "  ${GREEN}通过: $PASS_COUNT${NC}"
echo -e "  ${RED}失败: $FAIL_COUNT${NC}"
echo -e "  ${YELLOW}警告: $WARN_COUNT${NC}"
echo ""

if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${RED}验证未通过，存在 $FAIL_COUNT 个失败项${NC}"
    exit 1
else
    echo -e "${GREEN}验证通过${NC}"
    exit 0
fi
