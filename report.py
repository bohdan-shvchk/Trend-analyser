import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "niches.db"
REPORTS_DIR = Path(__file__).parent / "data" / "reports"


def generate_report(run_date=None, geo="US"):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    if run_date is None:
        row = conn.execute("SELECT MAX(run_date) FROM niches WHERE geo=?", (geo,)).fetchone()
        run_date = row[0] if row and row[0] else datetime.now().strftime("%Y-%m-%d")

    niches = conn.execute(
        """SELECT keyword, level, parent, avg_interest, trend_direction, peak_interest, score
           FROM niches WHERE run_date=? AND geo=?
           ORDER BY score DESC""",
        (run_date, geo),
    ).fetchall()

    if not niches:
        conn.close()
        return None

    total = len(niches)
    top20 = [n for n in niches if n[4] != "declining"][:20]
    growing = [n for n in niches if n[4] == "growing"][:15]
    declining = [n for n in niches if n[4] == "declining"][:10]

    lines = [
        "# Niche Analysis Report",
        f"**Date:** {run_date} | **Region:** {geo} | **Total niches analyzed:** {total}",
        "",
        "---",
        "",
        "## Top 20 Niches (sorted by score)",
        "",
        "| # | Keyword | Avg Interest | Trend | Peak | Score | Parent |",
        "|---|---------|-------------|-------|------|-------|--------|",
    ]

    for i, (kw, lvl, parent, avg, trend, peak, score) in enumerate(top20, 1):
        icon = "⬆️" if trend == "growing" else "➡️" if trend == "stable" else "⬇️"
        lines.append(
            f"| {i} | **{kw}** | {avg:.1f} | {icon} {trend} | {peak} | {score:.1f} | {parent or '—'} |"
        )

    lines += ["", "---", "", "## Growing Niches with Sub-niches", ""]

    for kw, lvl, parent, avg, trend, peak, score in growing:
        subs = conn.execute(
            """SELECT related_query, value FROM related_queries
               WHERE keyword=? AND run_date=? AND geo=? LIMIT 6""",
            (kw, run_date, geo),
        ).fetchall()
        sub_text = ", ".join([f"`{q}` ({v})" for q, v in subs]) if subs else "—"
        lines.append(f"**{kw}** — avg: {avg:.0f}, peak: {peak}, score: {score:.1f}")
        lines.append(f"- Sub-niches: {sub_text}")
        lines.append("")

    lines += ["---", "", "## ⚠️ Declining Niches (avoid)", ""]
    for kw, *_, avg, trend, peak, score in declining:
        lines.append(f"- **{kw}** — avg: {avg:.0f}, peak: {peak}")

    lines += [
        "",
        "---",
        "",
        "## Notes for Claude Analysis",
        "",
        "Please analyze the above data and answer:",
        "1. Top 3 niches most suitable for organic dropshipping (Pinterest + faceless TikTok)",
        "2. Which niches have lowest competition but decent demand",
        "3. Any seasonal opportunities worth preparing for",
        "4. Recommended sub-niche for a first dropshipping store",
        "",
        "**Context:** beginner, English-speaking markets (US/UK/CA/AU/NZ), "
        "budget <$50, 5–15h/week, faceless content only.",
    ]

    conn.close()

    report_path = REPORTS_DIR / f"report_{run_date}_{geo}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
