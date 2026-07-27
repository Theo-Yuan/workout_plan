#!/usr/bin/env python3
"""Generate Discord workout summary from today's train data."""
import json
import subprocess
import sys
from datetime import date

DISCORD_PYTHON = "/Users/theoyuan/.local/share/discord-mcp/venv/bin/python"

TODAY = date.today().isoformat()
TARGET = "学习星球/健身打卡"


def query_date(date_str: str) -> list:
    args = ["python3", ".agents/db/query_train.py", "--date", date_str, "--json"]
    if date_str >= TODAY:
        args.append("--force-api")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def pick_train(trains: list) -> dict:
    for t in trains:
        if t.get("duration_s", 0) > 0:
            return t
    return max(trains, key=lambda t: sum(
        len(m.get("sets", [])) for m in t.get("movements", [])
    ))


def is_warmup(weight, max_weight):
    if weight is None or max_weight is None:
        return False
    return weight < max_weight


def generate_summary(data: list) -> str:
    trains = data[0]["trains"]
    train = pick_train(trains)
    title = train["title"]
    movements = train["movements"]

    duration_min = train.get("duration_s", 0) // 60 if train.get("duration_s", 0) > 0 else 0

    move_lines = []
    warmup_count = 0
    working_sets = 0
    working_reps = 0
    seen_movements = set()

    for m in movements:
        name = m["name"]
        sets = m["sets"]
        if not sets:
            continue

        sets_key = tuple((s.get("weight_kg"), s.get("reps")) for s in sets)
        if (name, sets_key) in seen_movements:
            continue
        seen_movements.add((name, sets_key))

        max_w = max((s.get("weight_kg") or 0) for s in sets)

        working = []
        warmup = []
        for s in sets:
            w = s.get("weight_kg")
            w_str = f"{int(w)}kg" if w is not None and w == int(w) else (f"{w}kg" if w is not None else "自重")
            entry = f"{w_str} × {s['reps']}"
            if is_warmup(w, max_w):
                warmup.append(entry)
            else:
                working.append(entry)
                working_sets += 1
                working_reps += s["reps"]

        warmup_count += len(warmup)

        if working:
            working_str = " + ".join(working)
            warmup_str = f"（热身 {', '.join(warmup)}）" if warmup else ""
            move_lines.append(f"{name}     {working_str}{warmup_str}")
        elif warmup:
            move_lines.append(f"{name}     （仅热身 {', '.join(warmup)}）")

    if "腿" in title:
        day_type = "腿"
    elif "推" in title:
        day_type = "推"
    elif "拉" in title:
        day_type = "拉"
    else:
        day_type = title

    duration_line = f"⏱ {duration_min}分钟 | " if duration_min else ""
    warmup_line = f"（{warmup_count} 组热身不计入）" if warmup_count else ""

    lines = [
        f"✅ **今日训练完成 — {day_type}日**",
        "",
        f"📅 {TODAY} | {duration_line}🎯 {title}",
        "",
        "```",
        *move_lines,
        "```",
        "",
        f"📊 正式组：{working_sets} 组 · {working_reps} 次{warmup_line}",
        "",
        f"💪 坚持就是胜利！ #{day_type}日",
    ]
    return "\n".join(lines)


def send_discord(message: str, target: str = TARGET):
    result = subprocess.run(
        [DISCORD_PYTHON, ".agents/sched/send_discord.py", target],
        input=message, capture_output=True, text=True
    )
    print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode == 0


def main():
    data = query_date(TODAY)
    if not data:
        print(f"No training data for {TODAY}")
        return

    summary = generate_summary(data)
    print(summary)
    print()

    if send_discord(summary):
        print("Sent to Discord")
    else:
        print("Failed to send to Discord", file=sys.stderr)


if __name__ == "__main__":
    main()
