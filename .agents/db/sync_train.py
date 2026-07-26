#!/usr/bin/env python3
"""
训记训练数据同步脚本

增量拉取训练数据到本地 SQLite，支持断点续传。
用法:
    python .agents/db/sync_train.py                  # 拉取近6个月
    python .agents/db/sync_train.py --months 12      # 拉取近12个月
    python .agents/db/sync_train.py --start 2026-01-01 --end 2026-07-25
    python .agents/db/sync_train.py --status         # 查看同步状态
"""

import argparse
import gzip
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

# ── 路径 ──
DB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DB_DIR.parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DB_PATH = DB_DIR / "train.db"

API_URL = "https://trains.xunjiapp.cn/api_trains_for_llm_v2"
RATE_LIMIT_SECONDS = 15  # 普通读取限频


# ── 读 Key ──
def load_api_key() -> str:
    if not ENV_FILE.exists():
        print(f"[错误] 找不到 {ENV_FILE}，请先复制 .env.example 并填入 Key")
        sys.exit(1)
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("XUNJI_TRAIN_API_KEY") and "=" in line:
                val = line.split("=", 1)[1].strip()
                if val and not val.startswith("your_"):
                    return val
    print("[错误] .env 中 XUNJI_TRAIN_API_KEY 未设置或仍是占位符")
    sys.exit(1)


# ── 建表 ──
def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS trains (
            localid    INTEGER PRIMARY KEY,
            datestr    TEXT NOT NULL,
            title      TEXT,
            start_ms   INTEGER,
            end_ms     INTEGER,
            duration_s INTEGER,
            note       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trains_datestr ON trains(datestr);

        CREATE TABLE IF NOT EXISTS movements (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            train_id   INTEGER NOT NULL REFERENCES trains(localid),
            name       TEXT NOT NULL,
            idx        INTEGER,
            difficulty TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_movements_train ON movements(train_id);
        CREATE INDEX IF NOT EXISTS idx_movements_name ON movements(name);

        CREATE TABLE IF NOT EXISTS sets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            movement_id  INTEGER NOT NULL REFERENCES movements(id),
            idx          INTEGER,
            done         INTEGER,
            weight_kg    REAL,
            reps         INTEGER,
            rpe          TEXT,
            time_s       INTEGER,
            self_weight  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_sets_movement ON sets(movement_id);
    """)
    conn.commit()


def get_synced_dates(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT DISTINCT datestr FROM trains").fetchall()
    return {r[0] for r in rows}


def mark_date_synced(conn: sqlite3.Connection, datestr: str):
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        (f"synced_{datestr}", "1"),
    )


# ── API 请求 ──
def fetch_trains(api_key: str, datestr: str) -> Optional[dict]:
    body = json.dumps({
        "schema_version": "train_open_api_v2",
        "datestr": datestr,
        "include_full_data": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            # 处理 gzip 压缩响应
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            text = raw.decode("utf-8")
            if "too frequent" in text.lower():
                return {"__rate_limited__": True, "retry_after_ms": json.loads(text).get("retry_after_ms", 15000)}
        except Exception:
            text = raw[:200].hex()
        print(f"    HTTP {e.code}: {text[:200]}")
        return None
    except Exception as e:
        print(f"    请求异常: {e}")
        return None


# ── 入库 ──
def store_trains(conn: sqlite3.Connection, datestr: str, data: dict):
    res = data.get("res", data)  # 部分响应直接是 res 对象
    if isinstance(res, str):
        print(f"    ⚠ res 是字符串: {res[:100]}")
        mark_date_synced(conn, datestr)
        return
    trains = res.get("trains", [])
    if not trains:
        # 当天无训练，记录空日期避免重复拉取
        mark_date_synced(conn, datestr)
        return

    for t in trains:
        localid = t.get("localid")
        if not localid:
            continue
        start_ms = t.get("start") or t.get("started_at")
        end_ms = t.get("end") or t.get("ended_at")
        duration_s = ((end_ms or 0) - (start_ms or 0)) // 1000 if (start_ms and end_ms) else None
        note = t.get("note")
        if isinstance(note, dict):
            note = json.dumps(note, ensure_ascii=False)

        conn.execute(
            """INSERT OR REPLACE INTO trains
               (localid, datestr, title, start_ms, end_ms, duration_s, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (localid, datestr, t.get("title"), start_ms, end_ms, duration_s, note),
        )

        for m in t.get("movements", []):
            conn.execute(
                "INSERT INTO movements (train_id, name, idx, difficulty) VALUES (?, ?, ?, ?)",
                (localid, m.get("name"), m.get("index"), m.get("difficulty")),
            )
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for s in m.get("sets", []):
                # 处理超级组子项
                items = s.get("items", [])
                if items:
                    for item in items:
                        sub = item.get("set", {})
                        conn.execute(
                            """INSERT INTO sets (movement_id, idx, done, weight_kg, reps, rpe, time_s, self_weight)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (mid, sub.get("index"), 1 if sub.get("done") else 0,
                             _to_float(sub.get("weight")), _to_int(sub.get("reps")),
                             sub.get("rpe"), _to_int(sub.get("time")),
                             1 if sub.get("selfWeight") else 0),
                        )
                else:
                    conn.execute(
                        """INSERT INTO sets (movement_id, idx, done, weight_kg, reps, rpe, time_s, self_weight)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (mid, s.get("index"), 1 if s.get("done") else 0,
                         _to_float(s.get("weight")), _to_int(s.get("reps")),
                         s.get("rpe"), _to_int(s.get("time")),
                         1 if s.get("selfWeight") else 0),
                    )
        mark_date_synced(conn, datestr)
    conn.commit()


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


# ── 主流程 ──
def sync_range(api_key: str, start_date: date, end_date: date):
    conn = sqlite3.connect(str(DB_PATH))
    init_db(conn)
    synced = get_synced_dates(conn)

    total = (end_date - start_date).days + 1
    current = start_date
    pulled = 0
    skipped = 0
    errors = 0

    print(f"开始同步 {start_date} ~ {end_date}（共 {total} 天）")
    print(f"已同步: {len(synced)} 天 | 跳过已同步日期\n")

    while current <= end_date:
        datestr = current.isoformat()
        if datestr in synced:
            skipped += 1
            current += timedelta(days=1)
            continue

        print(f"  [{pulled + 1}/{total - skipped}] {datestr} ...", end=" ", flush=True)
        result = fetch_trains(api_key, datestr)

        if result is None:
            print("✗ 请求失败")
            errors += 1
        elif result.get("__rate_limited__"):
            wait = result.get("retry_after_ms", 15000) / 1000
            print(f"限频，等待 {wait:.0f}s ...")
            time.sleep(wait)
            continue  # 重试同一天
        else:
            store_trains(conn, datestr, result)
            train_count = len(result.get("res", result).get("trains", []))
            print(f"✓ ({train_count} 条训练)")
            pulled += 1

        current += timedelta(days=1)
        if current <= end_date:
            time.sleep(RATE_LIMIT_SECONDS)

    conn.close()
    print(f"\n完成！新增 {pulled} 天，跳过 {skipped} 天，失败 {errors} 天")


def show_status():
    conn = sqlite3.connect(str(DB_PATH))
    init_db(conn)
    count = conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0]
    dates = conn.execute("SELECT COUNT(DISTINCT datestr) FROM trains").fetchone()[0]
    date_range = conn.execute("SELECT MIN(datestr), MAX(datestr) FROM trains").fetchone()
    movements = conn.execute("SELECT COUNT(DISTINCT name) FROM movements").fetchone()[0]
    total_sets = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    conn.close()

    print("📊 训练数据同步状态")
    print(f"  数据库: {DB_PATH}")
    print(f"  训练天数: {dates}")
    print(f"  日期范围: {date_range[0]} ~ {date_range[1]}")
    print(f"  训练条数: {count}")
    print(f"  动作种类: {movements}")
    print(f"  总组数:   {total_sets}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步训记训练数据到本地 SQLite")
    parser.add_argument("--months", type=int, default=6, help="向前同步 N 个月（默认 6）")
    parser.add_argument("--start", type=str, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--status", action="store_true", help="查看同步状态")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    api_key = load_api_key()

    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    else:
        end = date.today()
        # 从 months 个月前第一天开始，确保覆盖整月
        start_month = end.month - args.months
        start_year = end.year
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start = date(start_year, start_month, 1)

    sync_range(api_key, start, end)
