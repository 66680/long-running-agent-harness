#!/bin/bash
# setup_harness.sh - 在新项目中初始化 harness 系统
#
# 使用方法:
#   curl -s https://raw.githubusercontent.com/.../setup_harness.sh | bash
#   或者
#   bash setup_harness.sh
#
# 然后打开 Claude Code，说 "帮我拆分任务：[你的需求]"

set -e

HARNESS_DIR="D:/claude automation"

echo "=========================================="
echo "  Long-Running Agent Harness 初始化"
echo "=========================================="
echo ""

# 检查是否在项目目录
if [ ! -d ".git" ]; then
    echo "警告: 当前目录不是 git 仓库"
    read -p "是否初始化 git? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git init
    fi
fi

# 复制核心文件
echo "复制 harness 文件..."

cp "$HARNESS_DIR/CLAUDE.md" . 2>/dev/null || echo "  CLAUDE.md 需要手动复制"
cp "$HARNESS_DIR/init.sh" . 2>/dev/null || echo "  init.sh 需要手动复制"
cp "$HARNESS_DIR/isolated_runner.py" . 2>/dev/null || echo "  isolated_runner.py 需要手动复制"

mkdir -p scripts
cp "$HARNESS_DIR/scripts/verify.sh" scripts/ 2>/dev/null || echo "  verify.sh 需要手动复制"

# 创建空的 Task.json
if [ ! -f "Task.json" ]; then
    cat > Task.json << 'EOF'
{
  "version": "1.0",
  "last_modified": "",
  "tasks": []
}
EOF
    echo "  创建了空的 Task.json"
fi

# 创建空的 progress.txt
if [ ! -f "progress.txt" ]; then
    cat > progress.txt << 'EOF'
================================================================================
                    Long-Running Agent Harness - 工作日志
================================================================================

格式: 时间 | 任务 | 操作 | 结果 | 下一步

================================================================================

EOF
    echo "  创建了空的 progress.txt"
fi

# 添加执行权限
chmod +x init.sh scripts/verify.sh 2>/dev/null || true

echo ""
echo "=========================================="
echo "  初始化完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "  1. 打开 Claude Code: claude"
echo "  2. 告诉我你的需求: '帮我拆分任务：做一个 XXX 系统'"
echo "  3. 开始执行: '继续'"
echo ""
echo "或者自动执行："
echo "  python isolated_runner.py --loop"
echo ""
