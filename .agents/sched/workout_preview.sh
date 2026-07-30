#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

TODAY=$(date +%Y-%m-%d)

BASE_JSON=$(python3 .agents/sched/workout_preview.py --json 2>/dev/null)
if [ -z "$BASE_JSON" ]; then
    echo "FATAL: Cannot get deterministic base data" >&2
    exit 1
fi

PHASE=$(echo "$BASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['phase'])")
IS_DELOAD=$(echo "$BASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['is_deload'])")
WEEKDAY=$(echo "$BASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['weekday'])")

EXERCISE_LINES=$(echo "$BASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for i, e in enumerate(data['exercises'], 1):
    tag = ' [减载]' if e['is_deload'] else ''
    print(f\"{i}. {e['name']}  × {e['sets']}组 × {e['reps']}{e['weight_hint']}{tag}\")
")

DELOAD_NOTE=""
if [ "$IS_DELOAD" = "True" ]; then
    DELOAD_NOTE="- ⚠️ 当前是减载周：组数已减半，重量不变，RPE 5-6，30 分钟内离场"
fi

PROMPT_FILE=$(mktemp /tmp/workout-prompt-$$-XXXXXX.txt)
trap "rm -f $PROMPT_FILE" EXIT

cat > "$PROMPT_FILE" <<'PROMPT_EOF'
你是训记训练助手。以下是脚本分析出的今日训练数据。请据此生成训练预告并发送到 Discord。

## 今日数据（脚本已分析好，不要修改动作列表）
- 日期: TODAY_PLACEHOLDER (WEEKDAY_PLACEHOLDER)
- PPL 阶段: PHASE_PLACEHOLDER 日
DELOAD_PLACEHOLDER

### 今日动作
EXERCISES_PLACEHOLDER

## 你的任务
1. 读取 .agents/profile.md 了解用户偏好、限制、当前阶段
2. 基于以上数据和 profile，生成 Discord 消息并发送
3. 用 discord_send_message 工具发送到 target="学习星球/健身打卡"
4. 发送完成后输出 Done

## 消息格式（严格遵循）
- 用中文，简洁有力
- 动作列表中的组数/次数不要修改
- 可以丰富 💡 提示部分（结合 profile 和数据给出个性化建议）
- 消息不超过 800 字符

示例格式：
🏋️ **今日训练预告 — 推日**
📅 2026-07-28（周二）| 🎯 渐进增肌

1. 杠铃卧推  × 4组 × 6-10次 @ 60-90kg
2. 器械坐姿推举  × 4组 × 10-12次 @ 40kg
3. 绳索侧平举（单边）  × 3组 × 12-15次
4. 绳索臂屈伸  × 3组 × 10-15次

💡 卧推先做，力竭前保留 1-2 rep；辅助动作控制离心。

## 约束
- 动作列表和组数已由脚本确定，不要修改
- 你可以调整重量建议（如有数据支持）、丰富个性化提示
- 减载周务必提醒「不要力竭」
- 发送完成后必须输出 Done（只输出一次）
PROMPT_EOF

sed -i '' \
    -e "s/TODAY_PLACEHOLDER/$TODAY/g" \
    -e "s/WEEKDAY_PLACEHOLDER/$WEEKDAY/g" \
    -e "s/PHASE_PLACEHOLDER/$PHASE/g" \
    "$PROMPT_FILE"

if [ -n "$DELOAD_NOTE" ]; then
    sed -i '' "s/DELOAD_PLACEHOLDER/$DELOAD_NOTE/g" "$PROMPT_FILE"
else
    sed -i '' '/DELOAD_PLACEHOLDER/d' "$PROMPT_FILE"
fi

TMP_PROMPT2=$(mktemp /tmp/workout-prompt2-$$-XXXXXX.txt)
while IFS= read -r line; do
    if [[ "$line" == "EXERCISES_PLACEHOLDER" ]]; then
        echo "$EXERCISE_LINES" >> "$TMP_PROMPT2"
    else
        echo "$line" >> "$TMP_PROMPT2"
    fi
done < "$PROMPT_FILE"
mv "$TMP_PROMPT2" "$PROMPT_FILE"

MAX_ATTEMPTS=3
TIMEOUT_SEC=90
RETRY_DELAY=10

for attempt in $(seq 1 $MAX_ATTEMPTS); do
    echo "[$(date '+%H:%M:%S')] Attempt $attempt/$MAX_ATTEMPTS: launching opencode..." >&2

    opencode run \
        --pure \
        --auto \
        --dir "$PROJECT_DIR" \
        --title "训练预告 $TODAY" \
        "$(cat "$PROMPT_FILE")" &
    OP_PID=$!

    elapsed=0
    while [ $elapsed -lt $TIMEOUT_SEC ]; do
        if ! kill -0 $OP_PID 2>/dev/null; then
            wait $OP_PID
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 0 ]; then
                echo "[$(date '+%H:%M:%S')] ✓ opencode success (attempt $attempt)" >&2
                exit 0
            fi
            echo "[$(date '+%H:%M:%S')] ✗ opencode exit=$EXIT_CODE (attempt $attempt)" >&2
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if kill -0 $OP_PID 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] ✗ opencode timeout after ${TIMEOUT_SEC}s (attempt $attempt)" >&2
        kill $OP_PID 2>/dev/null
        wait $OP_PID 2>/dev/null || true
    fi

    if [ $attempt -lt $MAX_ATTEMPTS ]; then
        echo "[$(date '+%H:%M:%S')] Retrying in ${RETRY_DELAY}s..." >&2
        sleep $RETRY_DELAY
    fi
done

echo "[$(date '+%H:%M:%S')] FATAL: All $MAX_ATTEMPTS attempts failed" >&2
exit 1
