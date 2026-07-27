#!/usr/bin/env python3
"""
训记训练数据查询脚本 — cache-through 模式

优先查本地 SQLite，未命中则调 API → 写回缓存 → 返回。
过去无训练的天也会标记为空，避免缓存穿透。

用法:
    python .agents/db/query_train.py --date 2026-07-27
    python .agents/db/query_train.py --date 2026-07-27 --json
    python .agents/db/query_train.py --range 2026-07-01 2026-07-27
    python .agents/db/query_train.py --check 2026-07-27    # 仅查本地
"""

import argparse
import gzip
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

DB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DB_DIR.parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DB_PATH = DB_DIR / "train.db"
API_URL = "https://trains.xunjiapp.cn/api_trains_for_llm_v2"


def load_api_key() -> str:
    if not ENV_FILE.exists():
        print(f"[错误] 找不到 {ENV_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("XUNJI_TRAIN_API_KEY") and "=" in line:
                val = line.split("=", 1)[1].strip()
                if val and not val.startswith("your_"):
                    return val
    print("[错误] XUNJI_TRAIN_API_KEY 未设置", file=sys.stderr)
    sys.exit(1)


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection):
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


def _is_date_synced(conn: sqlite3.Connection, datestr: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sync_meta WHERE key = ?", (f"synced_{datestr}",)
    ).fetchone()
    return row is not None


def _mark_synced(conn: sqlite3.Connection, datestr: str):
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        (f"synced_{datestr}", "1"),
    )
    conn.commit()


def _query_local(conn: sqlite3.Connection, datestr: str) -> Optional[list]:
    rows = conn.execute(
        "SELECT * FROM trains WHERE datestr = ? ORDER BY start_ms", (datestr,)
    ).fetchall()
    if not rows:
        return None

    result = []
    for t in rows:
        train = {
            "localid": t["localid"],
            "datestr": t["datestr"],
            "title": t["title"],
            "start_ms": t["start_ms"],
            "end_ms": t["end_ms"],
            "duration_s": t["duration_s"],
            "movements": [],
        }
        movements = conn.execute(
            "SELECT * FROM movements WHERE train_id = ? ORDER BY idx",
            (t["localid"],),
        ).fetchall()
        for m in movements:
            movement = {
                "name": m["name"],
                "idx": m["idx"],
                "difficulty": m["difficulty"],
                "sets": [],
            }
            sets = conn.execute(
                """SELECT * FROM sets WHERE movement_id = ? ORDER BY idx""",
                (m["id"],),
            ).fetchall()
            for s in sets:
                movement["sets"].append({
                    "idx": s["idx"],
                    "done": bool(s["done"]),
                    "weight_kg": s["weight_kg"],
                    "reps": s["reps"],
                    "rpe": s["rpe"],
                    "time_s": s["time_s"],
                    "self_weight": bool(s["self_weight"]),
                })
            train["movements"].append(movement)
        result.append(train)
    return result


def _fetch_api(api_key: str, datestr: str) -> Optional[dict]:
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
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            text = raw.decode("utf-8")
            if "too frequent" in text.lower():
                err = json.loads(text)
                return {"__rate_limited__": True, "retry_after_ms": err.get("retry_after_ms", 15000)}
        except Exception:
            pass
        print(f"  HTTP {e.code}: {raw.decode('utf-8', errors='replace')[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  请求异常: {e}", file=sys.stderr)
        return None


def _store_api_result(conn: sqlite3.Connection, datestr: str, data: dict):
    res = data.get("res", data)
    if isinstance(res, str):
        _mark_synced(conn, datestr)
        return
    trains = res.get("trains", [])
    if not trains:
        _mark_synced(conn, datestr)
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
            """INSERT OR REPLACE INTO trains (localid, datestr, title, start_ms, end_ms, duration_s, note)
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
        _mark_synced(conn, datestr)
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


def query_date(datestr: str, api_key: str, conn: sqlite3.Connection,
               force_api: bool = False) -> dict:
    if not force_api:
        local = _query_local(conn, datestr)
        if local is not None:
            return {"source": "local", "date": datestr, "trains": local}

        if _is_date_synced(conn, datestr):
            return {"source": "local", "date": datestr, "trains": [], "note": "no training this day"}

    api_result = _fetch_api(api_key, datestr)
    if api_result is None:
        return {"source": "error", "date": datestr, "error": "API request failed"}

    if api_result.get("__rate_limited__"):
        retry = api_result["retry_after_ms"] / 1000
        return {"source": "rate_limited", "date": datestr, "retry_after_s": retry}

    _store_api_result(conn, datestr, api_result)
    local = _query_local(conn, datestr)
    if local is not None:
        return {"source": "api", "date": datestr, "trains": local}
    else:
        return {"source": "api", "date": datestr, "trains": [], "note": "no training this day"}


def format_human(result: dict) -> str:
    if result["source"] == "error":
        return f"✗ {result['date']}: {result['error']}"
    if result["source"] == "rate_limited":
        return f"⏳ {result['date']}: 限频，请等 {result['retry_after_s']:.0f}s 后重试"
    if result["source"] == "local":
        src = "本地"
    else:
        src = "API"

    trains = result.get("trains", [])
    if not trains:
        return f"📭 {result['date']}: 无训练 ({src})"

    lines = [f"📅 {result['date']} ({src})"]
    for t in trains:
        dur = f"{t['duration_s'] // 60}分" if t.get("duration_s") else ""
        lines.append(f"  🏋️ {t['title']} {dur}")
        for m in t.get("movements", []):
            total_sets = len(m.get("sets", []))
            done_sets = sum(1 for s in m["sets"] if s.get("done"))
            lines.append(f"    {m['name']}  {done_sets}/{total_sets}组")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="查询训练数据（cache-through）")
    parser.add_argument("--date", type=str, help="查询单日 YYYY-MM-DD")
    parser.add_argument("--range", type=str, nargs=2, metavar=("START", "END"),
                        help="查询日期范围")
    parser.add_argument("--check", type=str, help="仅查本地，不调 API")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--force-api", action="store_true",
                        help="跳过本地缓存，强制从 API 拉取")
    args = parser.parse_args()

    if not (args.date or args.range or args.check):
        parser.print_help()
        sys.exit(1)

    api_key = load_api_key() if not args.check else None
    conn = get_conn()

    dates = []
    if args.date:
        dates.append(args.date)
    elif args.range:
        start = date.fromisoformat(args.range[0])
        end = date.fromisoformat(args.range[1])
        d = start
        while d <= end:
            dates.append(d.isoformat())
            d += timedelta(days=1)
    elif args.check:
        dates.append(args.check)

    results = []
    for datestr in dates:
        if args.check:
            local = _query_local(conn, datestr)
            synced = _is_date_synced(conn, datestr)
            if local is not None:
                results.append({"source": "local", "date": datestr, "trains": local})
            elif synced:
                results.append({"source": "local", "date": datestr, "trains": [], "note": "no training this day"})
            else:
                results.append({"source": "local", "date": datestr, "trains": [], "note": "not synced"})
        else:
            result = query_date(datestr, api_key, conn, force_api=args.force_api)
            results.append(result)
            if result["source"] == "rate_limited":
                time.sleep(result["retry_after_s"])
                result = query_date(datestr, api_key, conn, force_api=args.force_api)
                results[-1] = result

    conn.close()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(format_human(r))
            print()


if __name__ == "__main__":
    main()
