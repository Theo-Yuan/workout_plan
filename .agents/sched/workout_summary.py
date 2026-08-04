#!/usr/bin/env python3
"""Generate Discord workout summary from today's train data."""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

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


def pick_train(trains: list) -> dict | None:
    if not trains:
        return None
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


def generate_summary(data: list) -> str | None:
    trains = data[0]["trains"]
    if not trains:
        return None
    train = pick_train(trains)
    if not train:
        return None
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


def _recent_same_type(title: str, limit: int = 3):
    """直接从本地 SQLite 查询最近 N 次同类分化训练（供对比）。"""
    import sqlite3
    day_type = None
    for t in ("腿", "推", "拉"):
        if t in title:
            day_type = t
            break
    if not day_type:
        return []

    db_path = Path(__file__).resolve().parent.parent / "db" / "train.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT t.localid, t.datestr, t.title, t.duration_s
           FROM trains t
           WHERE t.title LIKE ? AND t.duration_s > 0
           ORDER BY t.datestr DESC LIMIT ?""",
        (f"%{day_type}%", limit),
    ).fetchall()
    out = []
    for r in rows:
        movements = conn.execute(
            """SELECT m.name, COUNT(s.id) AS sets
               FROM movements m LEFT JOIN sets s ON s.movement_id = m.id
               WHERE m.train_id = ?
               GROUP BY m.id""",
            (r["localid"],),
        ).fetchall()
        out.append({
            "datestr": r["datestr"],
            "title": r["title"],
            "duration_min": (r["duration_s"] or 0) // 60,
            "movements": [
                {"name": m["name"], "sets": m["sets"]} for m in movements
            ],
        })
    conn.close()
    return out


def _summary_data():
    """Agent 决策数据：今日训练 + 最近同类对比 + profile，供 agent 生成个性化摘要。"""
    data = query_date(TODAY)
    if not data:
        return {"date": TODAY, "error": "今日无训练数据"}

    trains = data[0]["trains"]
    if not trains:
        return {"date": TODAY, "error": "今日无训练数据"}
    train = pick_train(trains)
    if not train:
        return {"date": TODAY, "error": "今日无训练数据"}
    title = train.get("title", "")
    movements = train.get("movements", [])
    duration_min = (train.get("duration_s") or 0) // 60 if train.get("duration_s") else 0

    profile_text = ""
    profile_path = Path(__file__).resolve().parent.parent / "profile.md"
    if profile_path.exists():
        profile_text = profile_path.read_text()

    return {
        "date": TODAY,
        "title": title,
        "duration_min": duration_min,
        "movements": [
            {
                "name": m.get("name"),
                "sets": [
                    {"weight": s.get("weight_kg"), "reps": s.get("reps"),
                     "done": s.get("done")}
                    for s in m.get("sets", [])
                ],
            }
            for m in movements
        ],
        "recent_same_type": _recent_same_type(title),
        "profile": profile_text,
    }


def main():
    if "--data" in sys.argv:
        import json as _json
        print(_json.dumps(_summary_data(), ensure_ascii=False))
        return

    data = query_date(TODAY)
    if not data:
        print(f"No training data for {TODAY}")
        return

    summary = generate_summary(data)
    if not summary:
        print(f"No training data for {TODAY}")
        return
    print(summary)
    print()

    if send_discord(summary):
        print("Sent to Discord")
    else:
        print("Failed to send to Discord", file=sys.stderr)


if __name__ == "__main__":
    main()
