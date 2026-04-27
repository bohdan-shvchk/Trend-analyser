import sqlite3
import time
import logging
import json
from datetime import datetime
from pathlib import Path
import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manual .env loading if dotenv not available
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "niches.db"
CONFIG_PATH = Path(__file__).parent / "data" / "pinterest_categories_config.json"
PINTEREST_TOKEN = os.environ.get("PINTEREST_TOKEN", "")
BASE_URL = "https://api.pinterest.com/v5"

if not PINTEREST_TOKEN:
    log.warning(
        "PINTEREST_TOKEN not set. Pinterest crawler will not work. Add PINTEREST_TOKEN to .env file."
    )

HEADERS = {
    "Authorization": f"Bearer {PINTEREST_TOKEN}",
    "Content-Type": "application/json",
}


def load_categories():
    """Load Pinterest categories from config."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Error loading categories: {e}")
        return {}


def get_seeds_for_category(category_name: str) -> list:
    """Get seeds (subcategories) for a given category."""
    config = load_categories()
    for cat in config.get("categories", []):
        if cat.get("name", "").lower() == category_name.lower():
            return cat.get("subcategories", [])
    return []


def _fetch_suggestions(keyword: str) -> list:
    url = f"{BASE_URL}/keywords/suggestions"
    params = {"keyword": keyword, "limit": 200}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if r.status_code == 200:
            return r.json().get("items", [])
        elif r.status_code == 401:
            log.error(f"Pinterest auth failed (401): токен неправильний або застарілий. Перевірте PINTEREST_TOKEN в .env файлі")
            raise Exception("Pinterest authentication failed: invalid or expired token")
        elif r.status_code == 429:
            log.warning("Rate limited by Pinterest, sleeping 60s")
            time.sleep(60)
            return []
        else:
            log.warning(f"Pinterest API {r.status_code} for '{keyword}': {r.text[:200]}")
            return []
    except requests.exceptions.RequestException as e:
        log.error(f"Pinterest request error: {e}")
        return []


def _extract_volume(keyword: str, suggestions: list) -> float:
    for s in suggestions:
        if s.get("keyword", "").lower() == keyword.lower():
            m = s.get("metrics", {})
            lo = m.get("monthly_volume_est_lower", 0) or 0
            hi = m.get("monthly_volume_est_upper", 0) or 0
            return (lo + hi) / 2
    if suggestions:
        m = suggestions[0].get("metrics", {})
        lo = m.get("monthly_volume_est_lower", 0) or 0
        hi = m.get("monthly_volume_est_upper", 0) or 0
        return (lo + hi) / 2
    return 0


def crawl_pinterest_category(category: str, max_keywords: int = 200, progress_callback=None, max_api_requests: int = 500) -> int:
    """Crawl Pinterest by category. Generates seeds from subcategories and expands each."""
    seeds = get_seeds_for_category(category)
    if not seeds:
        log.error(f"Category '{category}' not found or has no seeds")
        return 0

    log.info(f"Crawling category '{category}' with seeds: {seeds}")
    return _crawl_with_seeds(category, seeds, max_keywords, progress_callback, max_api_requests)


def crawl_pinterest(seed: str, max_keywords: int = 200, progress_callback=None, max_api_requests: int = 500) -> int:
    """Crawl Pinterest with a single seed word."""
    return _crawl_with_seeds("Custom Seed", [seed], max_keywords, progress_callback, max_api_requests)


def _crawl_with_seeds(category: str, seeds: list, max_keywords: int = 200, progress_callback=None, max_api_requests: int = 500) -> int:
    conn = sqlite3.connect(DB_PATH)
    run_date = datetime.now().strftime("%Y-%m-%d")

    conn.execute(
        "INSERT INTO pinterest_runs (start_time, status, seed, category) VALUES (?, 'running', ?, ?)",
        (datetime.now().isoformat(), ",".join(seeds), category),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    queue = [(seed, 0, None) for seed in seeds]
    visited = set()
    saved = 0
    api_calls = 0

    try:
        while queue and saved < max_keywords and api_calls < max_api_requests:
            keyword, level, parent = queue.pop(0)

            if keyword.lower() in visited:
                continue
            visited.add(keyword.lower())

            if progress_callback:
                progress_callback(keyword, saved, max_keywords)

            log.info(f"[L{level}] {keyword}")

            suggestions = _fetch_suggestions(keyword)
            api_calls += 1
            time.sleep(1.0)

            if not suggestions:
                continue

            volume = _extract_volume(keyword, suggestions)

            conn.execute(
                """INSERT OR REPLACE INTO pinterest_niches
                   (keyword, level, parent, pin_volume, score, run_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (keyword, level, parent, volume, 0, run_date),
            )
            conn.commit()
            saved += 1

            if level < 3:
                for i, sug in enumerate(suggestions):
                    if i >= 10:
                        break
                    q = sug.get("keyword", "").strip()
                    if q and q.lower() not in visited:
                        queue.append((q, level + 1, keyword))

        rows = conn.execute(
            "SELECT keyword, pin_volume FROM pinterest_niches WHERE run_date=?", (run_date,)
        ).fetchall()
        max_vol = max((r[1] or 0 for r in rows), default=1) or 1
        for r in rows:
            score = round((r[1] or 0) / max_vol * 100)
            conn.execute(
                "UPDATE pinterest_niches SET score=? WHERE keyword=? AND run_date=?",
                (score, r[0], run_date),
            )
        conn.commit()

        conn.execute(
            "UPDATE pinterest_runs SET end_time=?, status='done', niches_found=? WHERE id=?",
            (datetime.now().isoformat(), saved, run_id),
        )
        conn.commit()

    except Exception as e:
        conn.execute(
            "UPDATE pinterest_runs SET end_time=?, status='error', niches_found=? WHERE id=?",
            (datetime.now().isoformat(), saved, run_id),
        )
        conn.commit()
        log.error(f"Crawl error: {e}")
        raise

    finally:
        conn.close()

    log.info(f"Done. Saved {saved} niches.")
    return saved
