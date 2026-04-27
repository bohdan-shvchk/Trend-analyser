import csv
import io
import json
import threading
import random
import time
from datetime import datetime
from pathlib import Path

import sqlite3
from flask import Flask, jsonify, request, send_from_directory, Response

from seeds import get_taxonomy_tree, load_config, save_config, DEFAULT_ENABLED
from crawler import crawl, init_db
from pinterest_crawler import crawl_pinterest, crawl_pinterest_category, load_categories
from report import generate_report

init_db()
app = Flask(__name__, static_folder="static")
DB_PATH = Path(__file__).parent / "data" / "niches.db"

crawl_state = {
    "running": False,
    "pct": 0,
    "current_keyword": "",
    "started_at": None,
    "saved": 0,
    "max": 0,
    "error": None,
    "run_id": None,
}

pinterest_crawl_state = {
    "running": False,
    "pct": 0,
    "current_keyword": "",
    "started_at": None,
    "saved": 0,
    "max": 0,
    "error": None,
}

trend_search_state = {
    "running": False,
    "pct": 0,
    "current_keyword": "",
    "error": None,
    "tree": None,
    "processed": 0,
    "total": 0,
    "started_at": None,
}

TIMEFRAME_MAP = {
    "7D": "now 7-d",
    "30D": "today 1-m",
    "90D": "today 3-m",
    "1Y": "today 12-m",
}

LABEL_TO_DB = {
    "relevant": "✅ Цікаво",
    "blocked": "❌ Не релевантно",
    "review": "🔍 Перевірити",
    "priority": "⭐ Пріоритет",
    "none": None,
}

LABEL_FROM_DB = {v: k for k, v in LABEL_TO_DB.items() if v}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _spark(avg, trend):
    import random
    rng = random.Random(round(avg * 137))
    pts = []
    for i in range(8):
        if trend == "growing":
            v = avg * (0.45 + i * 0.08) + rng.uniform(-3, 3)
        elif trend == "declining":
            v = avg * (1.55 - i * 0.08) + rng.uniform(-3, 3)
        else:
            v = avg * (0.85 + rng.random() * 0.3)
        pts.append(max(1, v))
    mx = max(pts) or 1
    return [round(v / mx * 100) for v in pts]


# ── Static ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Niches ────────────────────────────────────────────────────────

@app.route("/api/niches")
def api_niches():
    geo = request.args.get("geo", "US")
    run_date = request.args.get("run_date", "")
    run_id = request.args.get("run_id", "")
    conn = get_db()
    rows = []
    if run_id:
        rows = conn.execute(
            """
            SELECT DISTINCT n.keyword, n.parent, n.avg_interest, n.trend_direction,
                   n.peak_interest, n.score, ul.label
            FROM niches n
            LEFT JOIN user_labels ul ON n.keyword = ul.keyword
            WHERE n.run_id = ?
            GROUP BY n.keyword
            ORDER BY n.score DESC
            """,
            (run_id,),
        ).fetchall()
    if not rows:
        # Legacy fallback by geo + run_date
        for try_geo in [geo, ""]:
            if not run_date:
                row = conn.execute(
                    "SELECT run_date FROM niches WHERE geo=? GROUP BY run_date ORDER BY COUNT(*) DESC LIMIT 1",
                    (try_geo,),
                ).fetchone()
                effective_date = row[0] if row else ""
            else:
                effective_date = run_date
            if effective_date:
                rows = conn.execute(
                    """
                    SELECT DISTINCT n.keyword, n.parent, n.avg_interest, n.trend_direction,
                           n.peak_interest, n.score, ul.label
                    FROM niches n
                    LEFT JOIN user_labels ul ON n.keyword = ul.keyword
                    WHERE n.geo=? AND n.run_date=?
                    GROUP BY n.keyword
                    ORDER BY n.score DESC
                    """,
                    (try_geo, effective_date),
                ).fetchall()
                if rows:
                    break
    if not rows:
        conn.close()
        return jsonify([])
    conn.close()
    trend_map = {"growing": "up", "stable": "flat", "declining": "down"}
    result = []
    for i, r in enumerate(rows):
        avg = float(r["avg_interest"] or 0)
        trend = r["trend_direction"] or "stable"
        label_raw = r["label"]
        result.append(
            {
                "id": i + 1,
                "name": r["keyword"],
                "cat": r["parent"] or "General",
                "icon": "📊",
                "score": round(float(r["score"] or 0)),
                "trend": trend_map.get(trend, "flat"),
                "comp": "Med",
                "vol": str(round(avg)),
                "margin": "—",
                "label": LABEL_FROM_DB.get(label_raw, "none"),
                "spark": _spark(avg, trend),
            }
        )
    return jsonify(result)


@app.route("/api/run_dates")
def api_run_dates():
    geo = request.args.get("geo", "US")
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT run_date FROM niches WHERE geo=? OR geo='' ORDER BY run_date DESC",
        (geo,),
    ).fetchall()
    conn.close()
    return jsonify([r["run_date"] for r in rows])


@app.route("/api/subniche")
def api_subniche():
    keyword = request.args.get("keyword", "")
    geo = request.args.get("geo", "US")
    conn = get_db()
    rows = conn.execute(
        """
        SELECT rq.related_query, MAX(rq.value) as value,
               n.trend_direction, n.avg_interest
        FROM related_queries rq
        LEFT JOIN niches n ON rq.related_query = n.keyword AND n.geo = ?
        WHERE rq.keyword = ?
        GROUP BY rq.related_query
        ORDER BY CAST(MAX(rq.value) AS REAL) DESC
        LIMIT 10
        """,
        (geo, keyword),
    ).fetchall()
    conn.close()
    trend_map = {"growing": "up", "stable": "flat", "declining": "down", None: "flat"}
    return jsonify(
        [
            {
                "term": r["related_query"],
                "vol": str(round(float(r["avg_interest"] or 0))),
                "trend": trend_map.get(r["trend_direction"], "flat"),
            }
            for r in rows
        ]
    )


# ── Labels ────────────────────────────────────────────────────────

@app.route("/api/labels", methods=["POST"])
def api_save_label():
    data = request.json or {}
    keyword = data.get("keyword", "")
    label = data.get("label", "none")
    db_label = LABEL_TO_DB.get(label)
    conn = sqlite3.connect(DB_PATH)
    if db_label:
        conn.execute(
            "INSERT OR REPLACE INTO user_labels (keyword, label, created_at) VALUES (?,?,?)",
            (keyword, db_label, datetime.now().isoformat()),
        )
    else:
        conn.execute("DELETE FROM user_labels WHERE keyword=?", (keyword,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── Crawl ─────────────────────────────────────────────────────────

@app.route("/api/crawl", methods=["POST"])
def api_start_crawl():
    global crawl_state
    if crawl_state["running"]:
        return jsonify({"error": "Crawl already running"}), 409
    data = request.json or {}
    geo = data.get("geo", "US")
    timeframe_key = data.get("timeframe", "90D")
    max_niches = int(data.get("max_niches", 100))
    custom_keyword = data.get("keyword", "").strip()
    min_interest = int(data.get("min_interest", 5))
    tf = TIMEFRAME_MAP.get(timeframe_key, "today 3-m")
    custom_seeds = [custom_keyword] if custom_keyword else None

    categories = None
    if not custom_keyword:
        try:
            enabled = load_config()
            tree = get_taxonomy_tree()
            top_names = list(tree.keys())
            categories = [name for name in top_names if name in enabled]
        except Exception:
            categories = None

    def _run():
        global crawl_state
        crawl_state.update(
            running=True, pct=0, saved=0, max=max_niches,
            current_keyword="", error=None, run_id=None,
            started_at=datetime.now().isoformat(),
        )

        def progress_cb(kw, saved, total, run_id=None):
            if run_id is not None:
                crawl_state["run_id"] = run_id
            if kw is not None:
                crawl_state["current_keyword"] = kw
            crawl_state["saved"] = saved
            crawl_state["pct"] = round(saved / total * 100) if total else 0

        try:
            crawl(geo=geo, timeframe=tf, max_niches=max_niches, min_interest=min_interest,
                  progress_callback=progress_cb, custom_seeds=custom_seeds, categories=categories)
        except Exception as e:
            crawl_state["error"] = str(e)
        finally:
            crawl_state["running"] = False
            crawl_state["pct"] = 100

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/crawl/status")
def api_crawl_status():
    return jsonify(crawl_state)


@app.route("/api/crawl/live")
def api_crawl_live():
    run_id = request.args.get("run_id", "")
    if not run_id:
        return jsonify([])
    conn = get_db()
    rows = conn.execute(
        """
        SELECT keyword, parent, avg_interest, trend_direction, peak_interest, score, level
        FROM niches
        WHERE run_id = ?
        ORDER BY rowid DESC
        """,
        (run_id,),
    ).fetchall()
    conn.close()
    trend_map = {"growing": "up", "stable": "flat", "declining": "down"}
    result = []
    for r in rows:
        result.append({
            "keyword": r["keyword"],
            "parent": r["parent"] or "",
            "avg": round(float(r["avg_interest"] or 0)),
            "peak": int(r["peak_interest"] or 0),
            "score": round(float(r["score"] or 0)),
            "trend": trend_map.get(r["trend_direction"] or "stable", "flat"),
            "level": r["level"] or 0,
        })
    return jsonify(result)


@app.route("/api/runs/<int:run_id>/rename", methods=["POST"])
def api_rename_run(run_id):
    data = request.json or {}
    label = (data.get("label") or "").strip()
    conn = sqlite3.connect(DB_PATH)
    if label:
        conn.execute("UPDATE runs SET custom_label=? WHERE id=?", (label, run_id))
    else:
        conn.execute("UPDATE runs SET custom_label=NULL WHERE id=?", (run_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/runs/<int:run_id>", methods=["DELETE"])
def api_delete_run(run_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
    conn.execute("DELETE FROM niches WHERE run_id=?", (run_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── Pinterest Categories ────────────────────────────────────────

@app.route("/api/pinterest/categories")
def api_pinterest_categories():
    config = load_categories()
    categories = config.get("categories", [])
    enabled = config.get("enabled_categories", [])
    result = []
    for cat in categories:
        result.append({
            "id": cat.get("id"),
            "name": cat.get("name"),
            "level": cat.get("level"),
            "subcategories": cat.get("subcategories", []),
            "enabled": cat.get("id") in enabled
        })
    return jsonify({"categories": result})


# ── Pinterest Crawl ────────────────────────────────────────────

@app.route("/api/pinterest/crawl", methods=["POST"])
def api_start_pinterest_crawl():
    global pinterest_crawl_state
    if pinterest_crawl_state["running"]:
        return jsonify({"error": "Pinterest crawl already running"}), 409
    data = request.json or {}
    category = data.get("category", "").strip()
    keyword = data.get("keyword", "").strip()
    max_kw = int(data.get("max_keywords", 200))

    if not category and not keyword:
        return jsonify({"error": "category or keyword required"}), 400

    def _run():
        global pinterest_crawl_state
        pinterest_crawl_state.update(
            running=True, pct=0, saved=0, max=max_kw,
            current_keyword="", error=None,
            started_at=datetime.now().isoformat(),
        )
        def progress_cb(kw, saved, total):
            pinterest_crawl_state["current_keyword"] = kw
            pinterest_crawl_state["saved"] = saved
            pinterest_crawl_state["pct"] = round(saved / total * 100) if total else 0
        try:
            if category:
                crawl_pinterest_category(category=category, max_keywords=max_kw, progress_callback=progress_cb)
            else:
                crawl_pinterest(seed=keyword, max_keywords=max_kw, progress_callback=progress_cb)
        except Exception as e:
            pinterest_crawl_state["error"] = str(e)
        finally:
            pinterest_crawl_state["running"] = False
            pinterest_crawl_state["pct"] = 100

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/pinterest/crawl/status")
def api_pinterest_crawl_status():
    return jsonify(pinterest_crawl_state)


@app.route("/api/pinterest/niches")
def api_pinterest_niches():
    run_date = request.args.get("run_date", "")
    conn = get_db()
    if not run_date:
        row = conn.execute(
            "SELECT run_date FROM pinterest_niches GROUP BY run_date ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        effective_date = row[0] if row else ""
    else:
        effective_date = run_date

    if not effective_date:
        conn.close()
        return jsonify([])

    rows = conn.execute(
        """
        SELECT pn.keyword, pn.parent, pn.pin_volume, pn.score, ul.label
        FROM pinterest_niches pn
        LEFT JOIN user_labels ul ON pn.keyword = ul.keyword
        WHERE pn.run_date=?
        ORDER BY pn.score DESC
        """,
        (effective_date,),
    ).fetchall()
    conn.close()

    result = []
    for i, r in enumerate(rows):
        label_raw = r["label"]
        result.append({
            "id": i + 1,
            "name": r["keyword"],
            "cat": r["parent"] or "General",
            "score": int(r["score"] or 0),
            "pin_volume": int(r["pin_volume"] or 0),
            "label": LABEL_FROM_DB.get(label_raw, "none"),
        })
    return jsonify(result)


@app.route("/api/pinterest/runs")
def api_pinterest_runs():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pinterest_runs ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        start = r["start_time"] or ""
        end = r["end_time"] or ""
        duration = ""
        if start and end:
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(end)
                secs = int((e - s).total_seconds())
                duration = f"{secs // 60}m {secs % 60:02d}s"
            except Exception:
                pass
        try:
            time_str = datetime.fromisoformat(start).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            time_str = start
        status = r["status"] or "unknown"
        result.append({
            "id": r["id"],
            "label": f"Pinterest — {r['seed'] or 'N/A'}",
            "time": time_str,
            "duration": duration,
            "niches": r["niches_found"] or 0,
            "status": "success" if status == "done" else status,
            "seed": r["seed"] or "",
            "run_date": start[:10] if start else "",
        })
    return jsonify(result)


# ── Pinterest Export ───────────────────────────────────────────────

@app.route("/api/pinterest/report")
def api_pinterest_report():
    run_date = request.args.get("run_date", "")
    if not run_date:
        return jsonify({"error": "run_date required"}), 400

    conn = get_db()
    rows = conn.execute(
        """SELECT keyword, level, parent, pin_volume, score FROM pinterest_niches
           WHERE run_date=? ORDER BY score DESC LIMIT 100""",
        (run_date,)
    ).fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "no data found"}), 404

    report = f"""# Pinterest Keyword Analysis Report - {run_date}

## Summary
- Total keywords: {len(rows)}
- Top keyword: {rows[0][0] if rows else 'N/A'}
- Avg volume: {int(sum(r[3] or 0 for r in rows) / len(rows)) if rows else 0}

## Top Keywords
"""
    for i, row in enumerate(rows[:20], 1):
        report += f"{i}. **{row[0]}** (Score: {int(row[4] or 0)}, Volume: {int(row[3] or 0)})\n"

    report += f"\n## All Keywords\n"
    for i, row in enumerate(rows, 1):
        report += f"{i}. {row[0]} | Parent: {row[2] or 'N/A'} | Score: {int(row[4] or 0)} | Volume: {int(row[3] or 0)}\n"

    return jsonify({"report": report})


@app.route("/api/pinterest/export")
def api_pinterest_export():
    run_date = request.args.get("run_date", "")
    if not run_date:
        return jsonify({"error": "run_date required"}), 400

    conn = get_db()
    rows = conn.execute(
        """SELECT keyword, level, parent, pin_volume, score FROM pinterest_niches
           WHERE run_date=? ORDER BY score DESC""",
        (run_date,)
    ).fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "no data found"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#", "Ключове слово", "Батьківська", "Score", "Pin Volume"])
    for i, row in enumerate(rows, 1):
        writer.writerow([i, row[0], row[2] or "—", int(row[4] or 0), int(row[3] or 0)])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=pinterest_{run_date}.csv"}
    )


# ── Pinterest Search ───────────────────────────────────────────────

@app.route("/api/pinterest/search")
def api_pinterest_search():
    from pinterest_crawler import _fetch_suggestions, _extract_volume

    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "keyword required"}), 400

    try:
        suggestions = _fetch_suggestions(keyword)
        volume = _extract_volume(keyword, suggestions)

        # Top suggestions
        top_suggestions = []
        for i, sug in enumerate(suggestions[:15]):
            kw = sug.get("keyword", "").strip()
            m = sug.get("metrics", {})
            vol = (m.get("monthly_volume_est_lower", 0) or 0 + m.get("monthly_volume_est_upper", 0) or 0) / 2
            if kw:
                top_suggestions.append({"term": kw, "vol": int(vol)})

        return jsonify({
            "keyword": keyword,
            "volume": int(volume),
            "suggestions": top_suggestions
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Runs / History ─────────────────────────────────────────────────

def _build_run_label(r):
    custom_label = r["custom_label"] if "custom_label" in r.keys() else None
    if custom_label:
        return custom_label
    geo = r["geo"] or "—"
    parts = [f"Crawl — {geo}"]
    custom_keyword = r["custom_keyword"] if "custom_keyword" in r.keys() else None
    categories_raw = r["categories"] if "categories" in r.keys() else None
    if custom_keyword:
        parts.append(custom_keyword)
    elif categories_raw:
        try:
            cats = json.loads(categories_raw)
            if cats:
                shown = ", ".join(cats[:3])
                if len(cats) > 3:
                    shown += f" +{len(cats) - 3}"
                parts.append(shown)
        except Exception:
            pass
    return " — ".join(parts)


@app.route("/api/runs")
def api_runs():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        start = r["start_time"] or ""
        end = r["end_time"] or ""
        duration = ""
        if start and end:
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(end)
                secs = int((e - s).total_seconds())
                duration = f"{secs // 60}m {secs % 60:02d}s"
            except Exception:
                pass
        try:
            time_str = datetime.fromisoformat(start).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            time_str = start
        status = r["status"] or "unknown"
        custom_keyword = r["custom_keyword"] if "custom_keyword" in r.keys() else None
        categories_raw = r["categories"] if "categories" in r.keys() else None
        custom_label = r["custom_label"] if "custom_label" in r.keys() else None
        result.append(
            {
                "id": r["id"],
                "label": _build_run_label(r),
                "custom_label": custom_label,
                "custom_keyword": custom_keyword,
                "categories": json.loads(categories_raw) if categories_raw else [],
                "time": time_str,
                "duration": duration,
                "niches": r["niches_found"] or 0,
                "keywords": 0,
                "status": "success" if status == "done" else status,
                "tags": [r["geo"] or "—"],
                "run_date": start[:10] if start else "",
                "geo": r["geo"] or "US",
            }
        )
    return jsonify(result)


# ── Categories ─────────────────────────────────────────────────────

@app.route("/api/categories")
def api_get_categories():
    tree = get_taxonomy_tree()
    enabled_set = set(load_config())
    result = []
    for top_name, children in list(tree.items())[:40]:
        child_list = []
        for child_name, grandchildren in list(children.items())[:20]:
            path2 = f"{top_name} > {child_name}"
            gc_list = []
            for gc_name in list(grandchildren.keys())[:20]:
                path3 = f"{path2} > {gc_name}"
                gc_list.append(
                    {"name": gc_name, "path": path3, "enabled": path3 in enabled_set}
                )
            child_list.append(
                {
                    "name": child_name,
                    "path": path2,
                    "enabled": path2 in enabled_set,
                    "children": gc_list,
                }
            )
        enabled_count = sum(
            1 for p in enabled_set if p.startswith(top_name + " >") or p == top_name
        )
        result.append(
            {
                "name": top_name,
                "path": top_name,
                "enabled": top_name in enabled_set,
                "count": enabled_count,
                "children": child_list,
            }
        )
    return jsonify({"categories": result, "enabled": list(enabled_set)})


@app.route("/api/categories/defaults", methods=["POST"])
def api_reset_categories():
    save_config(list(DEFAULT_ENABLED))
    return jsonify({"ok": True, "enabled": list(DEFAULT_ENABLED)})


@app.route("/api/categories", methods=["POST"])
def api_save_categories():
    data = request.json or {}
    enabled = data.get("enabled", [])
    save_config(enabled)
    return jsonify({"ok": True})


# ── Export ─────────────────────────────────────────────────────────

@app.route("/api/report")
def api_report():
    geo = request.args.get("geo", "US")
    run_date = request.args.get("run_date", "") or None
    try:
        path = generate_report(run_date=run_date, geo=geo)
        if not path:
            # try empty geo fallback
            path = generate_report(run_date=run_date, geo="")
        if not path:
            return jsonify({"error": "No data"}), 404
        content = path.read_text(encoding="utf-8")
        return Response(
            content,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={path.name}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/labels/unblock", methods=["POST"])
def api_unblock():
    data = request.json or {}
    keyword = data.get("keyword", "")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM user_labels WHERE keyword=?", (keyword,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/export")
def api_export():
    geo = request.args.get("geo", "US")
    run_date = request.args.get("run_date", "")
    conn = get_db()
    if not run_date:
        row = conn.execute(
            "SELECT MAX(run_date) FROM niches WHERE geo=?", (geo,)
        ).fetchone()
        run_date = row[0] or ""
    rows = conn.execute(
        """
        SELECT n.keyword, n.score, n.avg_interest, n.trend_direction,
               n.peak_interest, n.run_date, ul.label
        FROM niches n
        LEFT JOIN user_labels ul ON n.keyword=ul.keyword
        WHERE n.geo=? AND n.run_date=?
        ORDER BY n.score DESC
        """,
        (geo, run_date),
    ).fetchall()
    conn.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Keyword", "Score", "Avg Interest", "Trend", "Peak", "Run Date", "Label"])
    for r in rows:
        w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6] or ""])
    fname = f"niches_{geo}_{run_date or 'latest'}.csv"
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── Trend Search ──────────────────────────────────────────────────

@app.route("/api/search")
def api_search():
    keyword = request.args.get("keyword", "").strip()
    geo = request.args.get("geo", "US")
    tf_key = request.args.get("timeframe", "90D")
    if not keyword:
        return jsonify({"error": "keyword required"}), 400
    tf = TIMEFRAME_MAP.get(tf_key, "today 3-m")
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(15, 60), retries=5, backoff_factor=2)
        pt.build_payload([keyword], cat=0, timeframe=tf, geo=geo, gprop="")
        delay = random.uniform(15123, 45789) / 1000  # 15.1-45.7 сек з мілісекундами
        time.sleep(delay)
        df = pt.interest_over_time()
        if df is None or df.empty or keyword not in df.columns:
            return jsonify({"error": "No data found"}), 404
        series = df[keyword]
        if "isPartial" in df.columns:
            series = series[df["isPartial"] == False]
        labels = [d.strftime("%b %d") for d in series.index]
        values = [int(v) for v in series.values]
        peak = int(series.max())
        current = int(series.iloc[-1]) if len(series) else 0
        avg = round(float(series.mean()))
        # Trend direction
        half = len(series) // 2
        first_h = series.iloc[:half].mean()
        second_h = series.iloc[half:].mean()
        if first_h < 1:
            forecast = "↑ Rising"
        elif second_h / first_h > 1.1:
            forecast = "↑ Rising"
        elif second_h / first_h < 0.9:
            forecast = "↓ Declining"
        else:
            forecast = "→ Stable"
        # Related queries
        pt.build_payload([keyword], cat=0, timeframe=tf, geo=geo, gprop="")
        delay = random.uniform(15123, 45789) / 1000  # 15.1-45.7 сек з мілісекундами
        time.sleep(delay)
        related = pt.related_queries()
        top_suggestions = []
        rising_suggestions = []
        if related and keyword in related:
            top_df = related[keyword].get("top")
            if top_df is not None and not top_df.empty:
                for _, row in top_df.iterrows():
                    top_suggestions.append({"term": str(row.get("query", "")), "vol": str(row.get("value", ""))})
            rising_df = related[keyword].get("rising")
            if rising_df is not None and not rising_df.empty:
                for _, row in rising_df.iterrows():
                    rising_suggestions.append({"term": str(row.get("query", "")), "vol": str(row.get("value", ""))})
        return jsonify(
            {
                "labels": labels,
                "values": values,
                "peak": peak,
                "current": current,
                "avg": avg,
                "forecast": forecast,
                "top": top_suggestions,
                "rising": rising_suggestions,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Trend Search (Recursive) ──────────────────────────────────

@app.route("/api/trend-search/start", methods=["POST"])
def api_start_trend_search():
    global trend_search_state
    if trend_search_state["running"]:
        return jsonify({"error": "Trend search already running"}), 409
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    geo = data.get("geo", "US")
    timeframe_key = data.get("timeframe", "90D")
    if not keyword:
        return jsonify({"error": "keyword required"}), 400
    tf = TIMEFRAME_MAP.get(timeframe_key, "today 3-m")

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO trend_search_runs (keyword, geo, timeframe, start_time, status) VALUES (?,?,?,?,'running')",
        (keyword, geo, timeframe_key, datetime.now().isoformat()),
    )
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    def _run():
        global trend_search_state
        trend_search_state.update(
            running=True, pct=0, error=None, tree=None, processed=0,
            current_keyword="", started_at=datetime.now().isoformat(),
        )
        try:
            tree = _build_keyword_tree(keyword, geo, tf, run_id)
            trend_search_state["tree"] = tree
        except Exception as e:
            trend_search_state["error"] = str(e)
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE trend_search_runs SET status='error' WHERE id=?", (run_id,))
            conn.commit()
            conn.close()
        finally:
            trend_search_state["running"] = False
            trend_search_state["pct"] = 100

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/trend-search/status")
def api_trend_search_status():
    return jsonify(trend_search_state)


def _get_keyword_graph(keyword, geo, timeframe):
    from pytrends.request import TrendReq

    def _analyze_trend(series):
        if len(series) < 2:
            return "stable", 1.0
        half = len(series) // 2
        if half == 0:
            return "stable", 1.0
        first = series.iloc[:half].mean()
        second = series.iloc[half:].mean()
        if first < 1:
            return "growing", 1.5
        ratio = second / first
        if ratio > 1.15:
            return "growing", 1.5
        elif ratio < 0.85:
            return "declining", 0.5
        return "stable", 1.0

    try:
        pt = TrendReq(hl="en-US", tz=0, timeout=(15, 60), retries=5, backoff_factor=2)
        pt.build_payload([keyword], cat=0, timeframe=timeframe, geo=geo, gprop="")
        delay = random.uniform(25000, 45000) / 1000
        time.sleep(delay)

        df = pt.interest_over_time()
        if df is not None and not df.empty and keyword in df.columns:
            series = df[keyword]
            if "isPartial" in df.columns:
                series = series[df["isPartial"] == False]

            labels = [d.strftime("%b %d") for d in series.index]
            values = [int(v) for v in series.values]
            peak = int(series.max())
            current = int(series.iloc[-1]) if len(series) else 0
            avg = round(float(series.mean()))
            trend_dir, trend_mult = _analyze_trend(series)
            score = avg * trend_mult

            return {
                "labels": labels,
                "values": values,
                "peak": peak,
                "current": current,
                "avg": avg,
                "trend": trend_dir,
                "score": round(score),
            }
    except Exception:
        pass
    return None


def _build_keyword_tree(root_keyword, geo, timeframe, run_id=None):
    from pytrends.request import TrendReq

    def _analyze_trend(series):
        if len(series) < 2:
            return "stable", 1.0
        half = len(series) // 2
        if half == 0:
            return "stable", 1.0
        first = series.iloc[:half].mean()
        second = series.iloc[half:].mean()
        if first < 1:
            return "growing", 1.5
        ratio = second / first
        if ratio > 1.15:
            return "growing", 1.5
        elif ratio < 0.85:
            return "declining", 0.5
        return "stable", 1.0

    root = {
        "keyword": root_keyword,
        "vol": None,
        "peak": None,
        "current": None,
        "avg": None,
        "trend": None,
        "score": None,
        "forecast": None,
        "labels": [],
        "values": [],
        "children": [],
    }
    nodes_map = {root_keyword: root}
    queue = [(root_keyword, 0)]
    processed = 0
    total_est = 1 + 10 + 100
    level_1_count = 0

    while queue:
        kw, depth = queue.pop(0)
        processed += 1
        trend_search_state["current_keyword"] = kw
        trend_search_state["processed"] = processed
        trend_search_state["total"] = max(total_est, processed + len(queue))
        trend_search_state["pct"] = round(processed / trend_search_state["total"] * 100)

        node = nodes_map[kw]
        should_fetch_graph = depth <= 1

        if should_fetch_graph:
            try:
                pt = TrendReq(hl="en-US", tz=0, timeout=(15, 60), retries=5, backoff_factor=2)
                pt.build_payload([kw], cat=0, timeframe=timeframe, geo=geo, gprop="")
                delay = random.uniform(25000, 45000) / 1000
                time.sleep(delay)

                df = pt.interest_over_time()

                if df is not None and not df.empty and kw in df.columns:
                    series = df[kw]
                    if "isPartial" in df.columns:
                        series = series[df["isPartial"] == False]

                    labels = [d.strftime("%b %d") for d in series.index]
                    values = [int(v) for v in series.values]
                    peak = int(series.max())
                    current = int(series.iloc[-1]) if len(series) else 0
                    avg = round(float(series.mean()))
                    trend_dir, trend_mult = _analyze_trend(series)
                    score = avg * trend_mult

                    node["labels"] = labels
                    node["values"] = values
                    node["peak"] = peak
                    node["current"] = current
                    node["avg"] = avg
                    node["trend"] = trend_dir
                    node["score"] = round(score)

                    if depth == 0:
                        if trend_dir == "growing":
                            node["forecast"] = "↑ Rising"
                        elif trend_dir == "declining":
                            node["forecast"] = "↓ Declining"
                        else:
                            node["forecast"] = "→ Stable"
            except Exception:
                pass

        if depth < 2:
            try:
                pt.build_payload([kw], cat=0, timeframe=timeframe, geo=geo, gprop="")
                delay = random.uniform(25000, 45000) / 1000
                time.sleep(delay)
                related = pt.related_queries()
                if related and kw in related:
                    top_df = related[kw].get("top")
                    if top_df is not None and not top_df.empty:
                        for _, row in top_df.iterrows():
                            child_kw = str(row.get("query", "")).strip()
                            if child_kw and child_kw not in nodes_map:
                                child_node = {
                                    "keyword": child_kw,
                                    "vol": str(row.get("value", "")),
                                    "peak": None,
                                    "current": None,
                                    "avg": None,
                                    "trend": None,
                                    "score": None,
                                    "forecast": None,
                                    "labels": [],
                                    "values": [],
                                    "children": [],
                                }
                                nodes_map[kw]["children"].append(child_node)
                                nodes_map[child_kw] = child_node
                                if depth == 0:
                                    queue.append((child_kw, depth + 1))
            except Exception:
                pass

    if run_id:
        def _count_words(node):
            count = 1
            for child in node.get("children", []):
                count += _count_words(child)
            return count

        total_words = _count_words(root)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE trend_search_runs SET end_time=?, status='done', total_words=?, tree_json=? WHERE id=?",
            (datetime.now().isoformat(), total_words, json.dumps(root), run_id),
        )
        conn.commit()
        conn.close()

    return root


# ── Trend Search History ──────────────────────────────────────

@app.route("/api/trend-search/runs")
def api_trend_search_runs():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trend_search_runs ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        start = r["start_time"] or ""
        end = r["end_time"] or ""
        duration = ""
        if start and end:
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(end)
                secs = int((e - s).total_seconds())
                duration = f"{secs // 60}m {secs % 60:02d}s"
            except Exception:
                pass
        try:
            time_str = datetime.fromisoformat(start).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            time_str = start
        status = r["status"] or "unknown"
        result.append({
            "id": r["id"],
            "keyword": r["keyword"] or "—",
            "geo": r["geo"] or "US",
            "timeframe": r["timeframe"] or "—",
            "time": time_str,
            "duration": duration,
            "total_words": r["total_words"] or 0,
            "status": "success" if status == "done" else status,
        })
    return jsonify(result)


@app.route("/api/trend-search/result")
def api_trend_search_result():
    run_id = request.args.get("run_id", "")
    if not run_id:
        return jsonify({"error": "run_id required"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT tree_json FROM trend_search_runs WHERE id=?", (run_id,)
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return jsonify({"error": "run not found"}), 404
    return jsonify(json.loads(row[0]))


@app.route("/api/trend-search/export")
def api_trend_search_export():
    run_id = request.args.get("run_id", "")
    if not run_id:
        return jsonify({"error": "run_id required"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT tree_json, keyword FROM trend_search_runs WHERE id=?", (run_id,)
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return jsonify({"error": "run not found"}), 404
    tree = json.loads(row[0])
    keyword = row[1] or "export"

    def flatten_tree(node, level=0, parent=""):
        rows = [(node["keyword"], level, parent if parent else "—", node.get("vol", "—"))]
        for child in node.get("children", []):
            rows.extend(flatten_tree(child, level + 1, node["keyword"]))
        return rows

    flat = flatten_tree(tree)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Keyword", "Level", "Parent", "Vol"])
    for kw, level, parent, vol in flat:
        w.writerow([kw, level, parent, vol])
    fname = f"trend_search_{keyword}_{run_id}.csv"
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.route("/api/trend-search/graph", methods=["POST"])
def api_trend_search_graph():
    data = request.json or {}
    keyword = data.get("keyword", "").strip()
    geo = data.get("geo", "US")
    timeframe_key = data.get("timeframe", "90D")

    if not keyword:
        return jsonify({"error": "keyword required"}), 400

    tf = TIMEFRAME_MAP.get(timeframe_key, "today 3-m")
    graph = _get_keyword_graph(keyword, geo, tf)

    if graph:
        return jsonify(graph)
    return jsonify({"error": "failed to fetch graph"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8501, threaded=True)
