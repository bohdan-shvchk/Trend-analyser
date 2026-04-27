import sqlite3
import time
import random
import logging
from datetime import datetime
from pathlib import Path
from pytrends.request import TrendReq
from seeds import get_seeds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "niches.db"

STOP_WORDS = frozenset([
    "скачати", "скачать", "download", "torrent",
    "netflix", "youtube", "facebook", "instagram", "spotify", "tiktok",
    "how to", "what is", "when does", "where to",
    "near me", "deduction", "tax credit", "lawsuit", "for dummies",
    "planet fitness", "home depot", "walmart", "amazon",
    # Брендові дитячі товари - найбільші фальш-позитиви
    "similac", "enfamil", "gerber", "pampers", "huggies", "pampers", "luvs",
    "pampers swaddlers", "pampers cruisers", "pampers swaddlers newborn",
    "pampers pure", "pampers swaddlers size", "pampers swaddlers active",
    # Інші дорогі бренди
    "formula", "feeding", "bottle sterilizer", "breast pump",
])


NON_DROPSHIP_BLOCK = frozenset([
    "streaming", "subscription", "membership", "free trial",
    "tutorial", "explained", "definition", "meaning", "how does",
    "software", "plugin", "app for", "saas",
    "vs ", " vs.", "comparison", "compare",
    "salary", "career", "job", "interview", "resume",
    "recipe", "ingredient", "calories", "nutrition",
    "lyrics", "chords", "tab ", "sheet music",
    "movie", "series", "episode", "season ", "cast of",
    # news / media
    "breaking", "announces", "lawsuit", "recall ", "fda ",
    "scandal", "controversy", "incident", "accident",
    # digital / non-physical
    "coupon", "promo code", "discount code", "cashback",
    "insurance", "warranty", "repair service", "installation service",
    # brands (common false positives from related queries)
    "amazon", "walmart", "target ", "costco", "ebay", "alibaba",
    "apple ", "samsung", "google ", "microsoft", "sony ", "lg ",
    "nike ", "adidas", "zara ", "shein", "temu",
])

NON_DROPSHIP_REVIEW = frozenset([
    "review", "reviews", " rated", "rating",
    "for beginners", "guide to", "tips for", "best way to",
    "diy ", "homemade", "how i ", "my experience",
    "2019", "2020", "2021", "2022", "2023", "2024", "2025",
    "alternative", "alternatives", "similar to",
    "how to use", "how to clean", "how to install",
    "what is ", "what are ", "which is ",
    "near me", "in my area", "locally",
])


def classify_keyword(kw):
    kw_lower = kw.lower()
    for p in NON_DROPSHIP_BLOCK:
        if p in kw_lower:
            return "❌ Не релевантно"
    for p in NON_DROPSHIP_REVIEW:
        if p in kw_lower:
            return "🔍 Перевірити"
    return None


def _is_valid_keyword(kw, blocklist):
    if len(kw.split()) > 6:
        return False
    try:
        kw.encode("ascii")
    except UnicodeEncodeError:
        return False
    kw_lower = kw.lower()
    for sw in STOP_WORDS:
        if sw in kw_lower:
            return False
    return kw_lower not in blocklist


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS niches (
            keyword TEXT,
            level INTEGER,
            parent TEXT,
            avg_interest REAL,
            trend_direction TEXT,
            trend_score REAL,
            peak_interest INTEGER,
            score REAL,
            run_date TEXT,
            geo TEXT,
            run_id INTEGER,
            PRIMARY KEY (keyword, run_date, geo)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS related_queries (
            keyword TEXT,
            related_query TEXT,
            value TEXT,
            run_date TEXT,
            geo TEXT,
            PRIMARY KEY (keyword, related_query, run_date, geo)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            niches_found INTEGER,
            geo TEXT,
            categories TEXT,
            custom_keyword TEXT,
            custom_label TEXT
        )
    """)
    # Migrate existing tables: add columns if missing
    cursor = conn.execute("PRAGMA table_info(niches)")
    niches_cols = {row[1] for row in cursor.fetchall()}
    if "run_id" not in niches_cols:
        conn.execute("ALTER TABLE niches ADD COLUMN run_id INTEGER")
    cursor = conn.execute("PRAGMA table_info(runs)")
    runs_cols = {row[1] for row in cursor.fetchall()}
    if "categories" not in runs_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN categories TEXT")
    if "custom_keyword" not in runs_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN custom_keyword TEXT")
    if "custom_label" not in runs_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN custom_label TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_labels (
            keyword TEXT PRIMARY KEY,
            label TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pinterest_niches (
            keyword TEXT,
            level INTEGER,
            parent TEXT,
            pin_volume REAL,
            score REAL,
            run_date TEXT,
            PRIMARY KEY (keyword, run_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pinterest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            niches_found INTEGER,
            seed TEXT,
            category TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trend_search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT,
            geo TEXT,
            timeframe TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            total_words INTEGER,
            tree_json TEXT
        )
    """)
    conn.commit()
    conn.close()


def _safe_request(func, retries=7):
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            error_msg = str(e).lower()
            # Спеціальний handling для rate limiting (429)
            if "429" in error_msg or "too many" in error_msg or "max retries exceeded" in error_msg:
                wait = (attempt + 1) * 40 + random.uniform(20123, 40789) / 1000  # 60-120+ сек з мілісекундами
                log.warning(f"Rate limited (attempt {attempt + 1}/{retries}). Waiting {wait:.1f}s...")
                time.sleep(wait)
            else:
                wait = (attempt + 1) * 15 + random.uniform(10123, 20789) / 1000  # 25-50 сек з мілісекундами
                log.warning(f"Request failed (attempt {attempt + 1}/{retries}): {e}. Retrying in {wait:.1f}s")
                time.sleep(wait)
    log.error(f"Request failed after {retries} retries")
    return None


def _analyze_trend(series):
    if series is None or len(series) < 4:
        return "stable", 1.0
    half = len(series) // 2
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


def crawl(geo="US", timeframe="today 5-y", max_niches=100, min_interest=5, progress_callback=None, custom_seeds=None, categories=None):
    import json as _json
    init_db()
    run_date = datetime.now().strftime("%Y-%m-%d")

    custom_keyword = custom_seeds[0] if custom_seeds and len(custom_seeds) == 1 else None
    categories_json = _json.dumps(categories) if categories else None

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO runs (start_time, status, geo, categories, custom_keyword) VALUES (?, 'running', ?, ?, ?)",
        (datetime.now().isoformat(), geo, categories_json, custom_keyword),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    if progress_callback:
        progress_callback(None, 0, max_niches, run_id=run_id)

    pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 35), retries=2, backoff_factor=1)

    blocked = set(
        r[0].lower() for r in
        conn.execute("SELECT keyword FROM user_labels WHERE label='❌ Не релевантно'").fetchall()
    )

    seeds = custom_seeds if custom_seeds else get_seeds()
    queue = [(kw, 0, None) for kw in seeds]
    visited = set()
    saved = 0

    try:
        while queue and saved < max_niches:
            keyword, level, parent = queue.pop(0)

            if keyword.lower() in visited:
                continue
            visited.add(keyword.lower())
            if not _is_valid_keyword(keyword, blocked):
                continue

            if progress_callback:
                progress_callback(keyword, saved, max_niches)

            log.info(f"[L{level}] {keyword}")

            def fetch_interest(kw=keyword):
                pytrends.build_payload([kw], cat=0, timeframe=timeframe, geo=geo, gprop="")
                return pytrends.interest_over_time()

            df = _safe_request(fetch_interest)
            delay = random.uniform(15123, 45789) / 1000  # 15.1-45.7 сек з мілісекундами
            log.info(f"Waiting {delay:.1f}s before next request...")
            time.sleep(delay)

            if df is None or df.empty or keyword not in df.columns:
                continue

            series = df[keyword]
            if "isPartial" in df.columns:
                series = series[df["isPartial"] == False]

            avg_interest = float(series.mean())
            peak_interest = int(series.max())

            if avg_interest < min_interest:
                continue

            trend_dir, trend_mult = _analyze_trend(series)
            score = avg_interest * trend_mult

            conn.execute(
                """INSERT OR REPLACE INTO niches
                   (keyword, level, parent, avg_interest, trend_direction, trend_score,
                    peak_interest, score, run_date, geo, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (keyword, level, parent, avg_interest, trend_dir, trend_mult,
                 peak_interest, score, run_date, geo, run_id),
            )
            conn.commit()
            saved += 1

            auto_label = classify_keyword(keyword)
            if auto_label:
                conn.execute(
                    "INSERT OR IGNORE INTO user_labels (keyword, label, created_at) VALUES (?, ?, ?)",
                    (keyword, auto_label, datetime.now().isoformat()),
                )
                conn.commit()

            if level < 3:
                def fetch_related(kw=keyword):
                    pytrends.build_payload([kw], cat=0, timeframe=timeframe, geo=geo, gprop="")
                    return pytrends.related_queries()

                related = _safe_request(fetch_related)
                delay = random.uniform(15123, 45789) / 1000  # 15.1-45.7 сек з мілісекундами
                log.info(f"Waiting {delay:.1f}s before next request...")
                time.sleep(delay)

                if related and keyword in related:
                    seen_related = set()
                    for query_type in ["top", "rising"]:
                        queries = related[keyword].get(query_type)
                        if queries is None or queries.empty:
                            continue
                        for _, row in queries.head(10).iterrows():
                            q = str(row.get("query", "")).strip()
                            v = str(row.get("value", ""))
                            if not q or q.lower() in visited or q in seen_related:
                                continue
                            seen_related.add(q)
                            conn.execute(
                                """INSERT OR REPLACE INTO related_queries
                                   (keyword, related_query, value, run_date, geo)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (keyword, q, v, run_date, geo),
                            )
                            if _is_valid_keyword(q, blocked):
                                queue.append((q, level + 1, keyword))
                    conn.commit()

        conn.execute(
            "UPDATE runs SET end_time=?, status='done', niches_found=? WHERE id=?",
            (datetime.now().isoformat(), saved, run_id),
        )
        conn.commit()

    except Exception as e:
        conn.execute(
            "UPDATE runs SET end_time=?, status='error', niches_found=? WHERE id=?",
            (datetime.now().isoformat(), saved, run_id),
        )
        conn.commit()
        log.error(f"Crawl error: {e}")
        raise

    finally:
        conn.close()

    log.info(f"Done. Saved {saved} niches.")
    return saved
