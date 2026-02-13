#!/bin/bash
# run_forever.sh - 无限循环运行脚本
# 实现持续推进的 Agent 工作流

# 不使用 set -e，因为我们需要手动控制退出

echo "=========================================="
echo "  Long-Running Agent Harness"
echo "  无限循环运行器"
echo "=========================================="
echo ""

# 配置
MAX_CONSECUTIVE_FAILURES=3
LOOP_DELAY_SECONDS=5
LOG_FILE="runner.log"

# 状态变量
CONSECUTIVE_FAILURES=0
LOOP_COUNT=0

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}[$timestamp]${NC} $1"
    echo "[$timestamp] $1" >> "$LOG_FILE"
}

log_error() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${RED}[$timestamp] ERROR:${NC} $1"
    echo "[$timestamp] ERROR: $1" >> "$LOG_FILE"
}

log_success() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${GREEN}[$timestamp] SUCCESS:${NC} $1"
    echo "[$timestamp] SUCCESS: $1" >> "$LOG_FILE"
}

log_warn() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${YELLOW}[$timestamp] WARN:${NC} $1"
    echo "[$timestamp] WARN: $1" >> "$LOG_FILE"
}

# 检查安全刹车
check_stop() {
    if [ -f "STOP" ]; then
        log_warn "检测到 STOP 文件，停止运行"
        return 1
    fi
    return 0
}

# 检查是否有阻塞任务需要人工介入
check_blocked() {
    local PYTHON_CMD=""
    if command -v python &> /dev/null; then
        PYTHON_CMD="python"
    elif command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        return 0
    fi

    local blocked_count=$($PYTHON_CMD << 'EOF'
import json
with open('Task.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
blocked = [t for t in data.get('tasks', []) if t.get('status') == 'blocked']
print(len(blocked))
EOF
)

    if [ -n "$blocked_count" ] && [ "$blocked_count" -gt 0 ] 2>/dev/null; then
        log_warn "存在 $blocked_count 个阻塞任务，需要人工介入"
        return 1
    fi
    return 0
}

# 获取下一个可领取的任务
get_next_task() {
    local PYTHON_CMD=""
    if command -v python &> /dev/null; then
        PYTHON_CMD="python"
    elif command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        echo ""
        return
    fi

    $PYTHON_CMD << 'EOF'
import json

with open('Task.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

tasks = data.get('tasks', [])
completed_ids = {t['id'] for t in tasks if t.get('status') == 'completed'}

for task in tasks:
    if task.get('status') == 'pending':
        deps = task.get('depends_on', [])
        if all(d in completed_ids for d in deps):
            print(task['id'])
            break
EOF
}

# 检查是否所有任务都完成
all_tasks_done() {
    local PYTHON_CMD=""
    if command -v python &> /dev/null; then
        PYTHON_CMD="python"
    elif command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        return 1
    fi

    local pending_count=$($PYTHON_CMD << 'EOF'
import json
with open('Task.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
pending = [t for t in data.get('tasks', []) if t.get('status') in ['pending', 'in_progress']]
print(len(pending))
EOF
)

    if [ -n "$pending_count" ] && [ "$pending_count" -eq 0 ] 2>/dev/null; then
        return 0
    fi
    return 1
}

# 运行初始化
run_init() {
    log "运行初始化脚本..."
    if ./init.sh > /dev/null 2>&1; then
        log_success "初始化成功"
        return 0
    else
        log_error "初始化失败"
        return 1
    fi
}

# 运行验证
run_verify() {
    log "运行验证脚本..."
    if ./scripts/verify.sh > /dev/null 2>&1; then
        log_success "验证通过"
        return 0
    else
        log_error "验证失败"
        return 1
    fi
}

# 主循环
main_loop() {
    log "启动主循环..."
    echo ""

    while true; do
        LOOP_COUNT=$((LOOP_COUNT + 1))
        log "========== 循环 #$LOOP_COUNT =========="

        # 1. 检查安全刹车
        if ! check_stop; then
            log "安全刹车触发，退出循环"
            break
        fi

        # 2. 检查阻塞任务
        if ! check_blocked; then
            log "存在阻塞任务，退出循环等待人工介入"
            break
        fi

        # 3. 检查是否所有任务完成
        if all_tasks_done; then
            log_success "所有任务已完成！"
            break
        fi

        # 4. 运行初始化
        if ! run_init; then
            CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
            log_error "初始化失败 (连续失败: $CONSECUTIVE_FAILURES/$MAX_CONSECUTIVE_FAILURES)"
            if [ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]; then
                log_error "连续失败次数达到上限，退出循环"
                break
            fi
            sleep $LOOP_DELAY_SECONDS
            continue
        fi

        # 5. 获取下一个任务
        NEXT_TASK=$(get_next_task)
        if [ -z "$NEXT_TASK" ]; then
            log_warn "没有可领取的任务（可能存在依赖阻塞）"
            sleep $LOOP_DELAY_SECONDS
            continue
        fi

        log "下一个任务: $NEXT_TASK"

        # 6. 这里是 Agent 执行任务的位置
        # 在实际使用中，这里会调用 Claude API 或其他 Agent
        # 目前只是占位符，打印提示信息
        log ">>> 等待 Agent 领取并执行任务: $NEXT_TASK"
        log ">>> 在实际部署中，这里会调用 Claude API"
        log ">>> 当前为演示模式，跳过实际执行"

        # 7. 运行验证
        if run_verify; then
            CONSECUTIVE_FAILURES=0
            log_success "本轮循环完成"
        else
            CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
            log_error "验证失败 (连续失败: $CONSECUTIVE_FAILURES/$MAX_CONSECUTIVE_FAILURES)"
            if [ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]; then
                log_error "连续失败次数达到上限，退出循环"
                break
            fi
        fi

        # 8. 延迟后进入下一轮
        log "等待 ${LOOP_DELAY_SECONDS} 秒后进入下一轮..."
        sleep $LOOP_DELAY_SECONDS

        # 演示模式：只运行一轮
        log_warn "演示模式：只运行一轮，退出循环"
        break
    done

    log "主循环结束，共运行 $LOOP_COUNT 轮"
}

# 清理函数
cleanup() {
    log "收到终止信号，正在清理..."
    # 这里可以添加清理逻辑
    exit 0
}

# 捕获信号
trap cleanup SIGINT SIGTERM

# 启动
echo "按 Ctrl+C 停止运行"
echo "或创建 STOP 文件: touch STOP"
echo ""

main_loop

echo ""
log "运行器已退出"
