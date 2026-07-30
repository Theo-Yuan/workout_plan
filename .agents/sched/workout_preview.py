#!/usr/bin/env python3
"""每日训练预告生成器 — 确定性脚本，替代 opencode run AI Agent。

用法:
    python3 workout_preview.py              # 生成并发送到 Discord
    python3 workout_preview.py --dry-run    # 仅打印，不发送
"""

import json
import re
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / ".agents" / "db" / "train.db"
PROFILE_PATH = PROJECT_ROOT / ".agents" / "profile.md"

CHANNEL_ID = "1531141390208077895"

PPL_CYCLE = ["推", "拉", "腿"]

_DB_WEIGHT_NAMES = {
    "引体向上/高位下拉": ["引体向上", "器械高位划船"],
    "器械腿举": ["器械倒蹬", "器械腿举"],
}

PPL_TEMPLATES = {
    "推": [
        ("杠铃卧推", 4, "6-10次"),
        ("器械坐姿推举", 4, "10-12次"),
        ("绳索侧平举（单边）", 3, "12-15次"),
        ("绳索臂屈伸", 3, "10-15次"),
    ],
    "拉": [
        ("坐姿划船", 4, "8-12次"),
        ("引体向上/高位下拉", 4, "8-12次"),
        ("面拉", 3, "12-15次"),
        ("器械弯举", 3, "10-15次"),
    ],
    "腿": [
        ("哈克机深蹲", 4, "6-10次"),
        ("硬拉器硬拉", 4, "8-12次"),
        ("器械腿举", 3, "12-15次"),
        ("悬挂抬腿", 3, "10-15次"),
    ],
}

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TIPS = {
    "推": "卧推先做，力竭前保留 1-2 rep；辅助动作控制离心，感受目标肌群发力。",
    "拉": "主项先拉重，辅助动作感受背部收缩，避免手臂借力。",
    "腿": "哈克机优先，注意膝盖不要内扣；硬拉保持脊柱中立。安全第一。",
}


def _get_token():
    result = subprocess.run(
        ["security", "find-generic-password",
         "-s", "discord-bot-token", "-a", "opencode", "-w"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        print(f"ERROR: Cannot read bot token: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _send_http(token, channel_id, content):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bot {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "WorkoutBot/1.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"ERROR: Discord API: {e}", file=sys.stderr)
        return False


def _get_last_training(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT datestr, title FROM trains ORDER BY datestr DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None, None
    return row["datestr"], row["title"]


def _get_exercise_weights(db_path, name, limit=3):
    names = _DB_WEIGHT_NAMES.get(name, [name])
    conn = sqlite3.connect(str(db_path))
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(f"""
        SELECT s.weight_kg
        FROM sets s
        JOIN movements m ON m.id = s.movement_id
        JOIN trains t ON t.localid = m.train_id
        WHERE m.name IN ({placeholders}) AND s.done = 1 AND s.weight_kg > 0
        ORDER BY t.datestr DESC, s.weight_kg DESC
        LIMIT ?
    """, (*names, limit)).fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


def _detect_phase(title):
    if not title:
        return None
    for p in PPL_CYCLE:
        if p in title:
            return p
    return None


def _determine_today(last_date_str, last_phase):
    if last_phase not in PPL_CYCLE:
        return PPL_CYCLE[0]

    last_dt = datetime.strptime(last_date_str, "%Y-%m-%d").date()
    today = date.today()
    days_since = (today - last_dt).days
    if days_since < 0:
        return PPL_CYCLE[0]

    idx = PPL_CYCLE.index(last_phase)
    return PPL_CYCLE[(idx + days_since) % 3]


def _is_deload(profile_text):
    m = re.search(
        r'减载周执行[^）)]*[（(]\s*([\d/]+)\s*~\s*([\d/]+)\s*[）)]',
        profile_text,
    )
    if not m:
        return False

    today = date.today()
    year = str(today.year)
    try:
        start = datetime.strptime(
            f"{year}-{m.group(1).replace('/', '-')}", "%Y-%m-%d"
        ).date()
        end = datetime.strptime(
            f"{year}-{m.group(2).replace('/', '-')}", "%Y-%m-%d"
        ).date()
    except ValueError:
        return False

    return start <= today <= end


def _format_weight_hint(weights):
    if not weights:
        return ""
    lo, hi = int(min(weights)), int(max(weights))
    return f" @ {lo}kg" if lo == hi else f" @ {lo}-{hi}kg"


def generate_message(phase, is_deload, db_path):
    today = date.today()
    weekday = WEEKDAY_CN[today.weekday()]
    date_str = today.strftime("%Y-%m-%d")
    exercises = PPL_TEMPLATES.get(phase, PPL_TEMPLATES["推"])

    if is_deload:
        emoji, stage = "🔄", "减载周 · 组数减半 · 重量不变"
        tip = "💡 减载周：组数减半，重量不变，RPE 5-6，30 分钟内离场。做完感觉「还能做 4-5 次」即可。"
    else:
        emoji, stage = "🏋️", "渐进增肌"
        tip = f"💡 {TIPS.get(phase, '控制节奏，感受目标肌群发力。')}"

    move_lines = []
    for i, (name, sets, reps) in enumerate(exercises, 1):
        weight_hint = _format_weight_hint(_get_exercise_weights(db_path, name))
        if is_deload:
            ds = max(1, sets // 2)
            move_lines.append(f"{i}. {name}  × {ds}组 × {reps}{weight_hint}  [减载]")
        else:
            move_lines.append(f"{i}. {name}  × {sets}组 × {reps}{weight_hint}")

    return "\n".join([
        f"{emoji} **今日训练预告 — {phase}日**",
        f"📅 {date_str}（{weekday}）| 🎯 {stage}",
        "```",
        *move_lines,
        "```",
        tip,
    ])


def _get_payload():
    profile_text = ""
    if PROFILE_PATH.exists():
        profile_text = PROFILE_PATH.read_text()

    last_date, last_title = _get_last_training(DB_PATH)
    if not last_date or not last_title:
        print("ERROR: No training data in SQLite", file=sys.stderr)
        sys.exit(1)

    last_phase = _detect_phase(last_title)
    if not last_phase:
        print(f"ERROR: Cannot detect PPL phase from title '{last_title}'",
              file=sys.stderr)
        sys.exit(1)

    today_phase = _determine_today(last_date, last_phase)
    is_deload = _is_deload(profile_text)

    exercises = []
    for name, sets, reps in PPL_TEMPLATES.get(today_phase, PPL_TEMPLATES["推"]):
        weights = _get_exercise_weights(DB_PATH, name)
        weight_hint = _format_weight_hint(weights)
        ds = max(1, sets // 2) if is_deload else sets
        exercises.append({
            "name": name,
            "sets": ds,
            "reps": reps,
            "weight_hint": weight_hint,
            "is_deload": is_deload,
        })

    today = date.today()

    return {
        "date": today.strftime("%Y-%m-%d"),
        "weekday": WEEKDAY_CN[today.weekday()],
        "phase": today_phase,
        "is_deload": is_deload,
        "last_training_date": last_date,
        "last_phase": last_phase,
        "exercises": exercises,
    }


def main():
    json_mode = "--json" in sys.argv
    dry_run = "--dry-run" in sys.argv

    payload = _get_payload()

    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return

    msg = generate_message(payload["phase"], payload["is_deload"], DB_PATH)
    print(msg)
    print()

    if dry_run:
        print("[DRY RUN] 未发送到 Discord")
        return

    token = _get_token()
    if _send_http(token, CHANNEL_ID, msg):
        print("✓ 已发送到 Discord #健身打卡")
    else:
        print("✗ Discord 发送失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
