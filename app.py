import sqlite3
import json as _json
import threading
import time
import random
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from pytrends.request import TrendReq

from crawler import crawl, DB_PATH
from report import generate_report
from seeds import get_taxonomy_tree, load_config, save_config, DEFAULT_ENABLED, CONFIG_PATH

_SAVE_PORT = 8503

HIDDEN_CATEGORIES = {"Arts & Entertainment", "Food, Beverages & Tobacco", "Software", "Hardware"}


class _SaveHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path != "/save":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = _json.loads(body)
            CONFIG_PATH.write_text(_json.dumps(data, ensure_ascii=False, indent=2))
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception:
            self.send_response(500)
            self.end_headers()

    def log_message(self, *a):
        pass


if "save_server_started" not in st.session_state:
    def _run():
        HTTPServer(("localhost", _SAVE_PORT), _SaveHandler).serve_forever()
    threading.Thread(target=_run, daemon=True).start()
    st.session_state.save_server_started = True


def _build_nodes(node, path, depth):
    result = []
    for name in sorted(node.keys()):
        if depth == 0 and name in HIDDEN_CATEGORIES:
            continue
        current_path = f"{path} > {name}" if path else name
        item = {"label": name, "value": current_path}
        if node[name] and depth < 3:
            item["children"] = _build_nodes(node[name], current_path, depth + 1)
        result.append(item)
    return result


def _collect_all_paths(node, path, depth):
    result = []
    for name in sorted(node.keys()):
        if depth == 0 and name in HIDDEN_CATEGORIES:
            continue
        current_path = f"{path} > {name}" if path else name
        result.append(current_path)
        if node[name] and depth < 3:
            result.extend(_collect_all_paths(node[name], current_path, depth + 1))
    return result


def _tree_html(nodes_data, checked_list, defaults_list, all_paths_list):
    nodes_json = _json.dumps(nodes_data, ensure_ascii=False)
    checked_json = _json.dumps(checked_list, ensure_ascii=False)
    defaults_json = _json.dumps(defaults_list, ensure_ascii=False)
    all_paths_json = _json.dumps(all_paths_list, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; background: transparent; }}
  .node-row {{ display: flex; align-items: center; padding: 2px 0; line-height: 1.4; }}
  .node-row:hover {{ background: rgba(0,0,0,0.04); border-radius: 3px; }}
  .toggle {{ width: 16px; min-width: 16px; cursor: pointer; color: #888; font-size: 10px; text-align: center; user-select: none; }}
  .toggle:hover {{ color: #333; }}
  .children {{ margin-left: 16px; padding-left: 8px; border-left: 1px solid #ddd; }}
  .children.hidden {{ display: none; }}
  input[type=checkbox] {{ margin: 0 5px 0 2px; cursor: pointer; }}
  label {{ cursor: pointer; color: #333; }}
  .actions {{ display: flex; gap: 6px; padding: 6px 0 2px; border-top: 1px solid #eee; margin-top: 4px; }}
  .btn {{ flex: 1; padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; font-size: 12px; background: #fff; }}
  .btn:hover {{ opacity: 0.8; }}
  .count {{ font-size: 11px; color: #888; margin-bottom: 4px; }}
</style>
</head>
<body>
<div class="count" id="count"></div>
<div id="tree"></div>
<div class="actions">
  <button class="btn" onclick="selectAll()">Всі</button>
  <button class="btn" onclick="selectNone()">Зняти всі</button>
  <button class="btn" onclick="setDefaults()">↺ Defaults</button>
</div>
<script>
  var nodes = {nodes_json};
  var checked = new Set({checked_json});
  var expanded = new Set();
  var defaults = {defaults_json};
  var allPaths = {all_paths_json};
  var saveTimer = null;

  function renderNode(parent, node, depth) {{
    var hasChildren = node.children && node.children.length > 0;
    var row = document.createElement('div');
    row.className = 'node-row';
    var toggle = document.createElement('span');
    toggle.className = 'toggle';
    if (hasChildren) {{
      toggle.textContent = expanded.has(node.value) ? '▾' : '▸';
      toggle.onclick = (function(n) {{
        return function() {{
          if (expanded.has(n.value)) expanded.delete(n.value);
          else expanded.add(n.value);
          rerenderTree();
        }};
      }})(node);
    }}
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'cb_' + node.value.replace(/\\W/g, '_');
    cb.checked = checked.has(node.value);
    cb.onchange = (function(v) {{
      return function() {{
        if (this.checked) checked.add(v);
        else checked.delete(v);
        updateCount();
        scheduleSave();
      }};
    }})(node.value);
    var label = document.createElement('label');
    label.htmlFor = cb.id;
    label.textContent = node.label;
    row.appendChild(toggle);
    row.appendChild(cb);
    row.appendChild(label);
    parent.appendChild(row);
    if (hasChildren) {{
      var childWrap = document.createElement('div');
      childWrap.className = 'children' + (expanded.has(node.value) ? '' : ' hidden');
      node.children.forEach(function(child) {{ renderNode(childWrap, child, depth + 1); }});
      parent.appendChild(childWrap);
    }}
  }}

  function rerenderTree() {{
    var el = document.getElementById('tree');
    el.innerHTML = '';
    nodes.forEach(function(n) {{ renderNode(el, n, 0); }});
    updateCount();
    setHeight();
  }}

  function updateCount() {{
    document.getElementById('count').textContent = checked.size + ' активних';
  }}

  function setHeight() {{
    document.body.style.height = 'auto';
    var h = document.documentElement.scrollHeight;
    window.parent.postMessage({{ type: 'streamlit:setFrameHeight', height: h }}, '*');
  }}

  function scheduleSave() {{
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 300);
  }}

  function save() {{
    fetch('http://localhost:{_SAVE_PORT}/save', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(Array.from(checked))
    }}).catch(function() {{}});
  }}

  function selectAll() {{
    allPaths.forEach(function(p) {{ checked.add(p); }});
    rerenderTree();
    save();
  }}

  function selectNone() {{
    checked.clear();
    rerenderTree();
    save();
  }}

  function setDefaults() {{
    checked = new Set(defaults);
    rerenderTree();
    save();
  }}

  rerenderTree();
</script>
</body>
</html>"""


st.set_page_config(page_title="Trends Analyzer", page_icon="📈", layout="wide")

GEO_LABELS = {
    "": "Worldwide",
    "US": "USA",
    "GB": "UK",
    "CA": "Canada",
    "AU": "Australia",
    "NZ": "Нова Зеландія",
    "IE": "Ірландія",
    "FR": "Франція",
    "AT": "Австрія",
    "BE": "Бельгія",
    "IT": "Італія",
    "ES": "Іспанія",
}
TREND_ICONS = {"growing": "⬆️ Росте", "stable": "➡️ Стабільно", "declining": "⬇️ Падає"}
REPORTS_DIR = Path(__file__).parent / "data" / "reports"


def _scheduled_job():
    try:
        crawl(geo="", timeframe="today 5-y", max_niches=100)
    except Exception:
        pass


if "scheduler" not in st.session_state:
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(_scheduled_job, "cron", day_of_week="sun", hour=9, minute=0)
    sched.start()
    st.session_state.scheduler = sched


def load_data(geo, run_date):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT keyword, level, parent, avg_interest, trend_direction, peak_interest, score FROM niches WHERE run_date=? AND geo=? ORDER BY score DESC",
        conn, params=(run_date, geo),
    )
    conn.close()
    return df


def get_all_run_dates(geo):
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT run_date FROM niches WHERE geo=? ORDER BY run_date DESC", (geo,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def get_runs_history():
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT id, start_time, end_time, status, niches_found, geo FROM runs ORDER BY id DESC",
            conn,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


LABEL_OPTIONS = ["", "✅ Цікаво", "🔍 Перевірити", "❌ Не релевантно", "⭐ Пріоритет"]


def get_labels():
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT keyword, label FROM user_labels").fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def set_label(keyword, label):
    conn = sqlite3.connect(DB_PATH)
    if label:
        conn.execute(
            "INSERT OR REPLACE INTO user_labels (keyword, label, created_at) VALUES (?, ?, ?)",
            (keyword, label, datetime.now().isoformat()),
        )
    else:
        conn.execute("DELETE FROM user_labels WHERE keyword=?", (keyword,))
    conn.commit()
    conn.close()


def last_run_info():
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT start_time, status, niches_found FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return row
    except Exception:
        return None


# ── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Параметри")
    geo = st.selectbox("Регіон", list(GEO_LABELS.keys()), format_func=lambda x: GEO_LABELS[x], index=list(GEO_LABELS.keys()).index(""))
    timeframe = st.selectbox(
        "Діапазон",
        ["today 5-y", "today 12-m"],
        format_func=lambda x: "5 років" if x == "today 5-y" else "12 місяців",
    )
    unlimited = st.checkbox("Без ліміту", value=True)
    if unlimited:
        max_niches = 999999
        st.caption("Краулер пройде всі категорії до кінця")
    else:
        max_niches = st.number_input("Макс. запитів за запуск", min_value=10, max_value=100000, value=500, step=100)

    info = last_run_info()
    if info:
        st.caption(f"Останній запуск: {info[0][:10] if info[0] else '—'} · {info[2] or 0} ніш · `{info[1]}`")

    st.markdown("---")
    kw_input = st.text_input("🔍 Пошук по слову", placeholder="наприклад: yoga mat")
    search_btn = st.button("Шукати", use_container_width=True)

    st.markdown("---")
    st.markdown("**Категорії**")

    tree = get_taxonomy_tree()
    if tree:
        nodes_data = _build_nodes(tree, "", 0)
        all_paths = _collect_all_paths(tree, "", 0)
        checked_list = load_config()
        defaults_list = list(DEFAULT_ENABLED)
        html = _tree_html(nodes_data, checked_list, defaults_list, all_paths)
        tree_height = len(nodes_data) * 23 + 48
        components.html(html, height=tree_height, scrolling=True)
    else:
        st.warning("Не вдалося завантажити категорії.")

    st.markdown("---")
    run_btn = st.button("🚀 Запустити зараз", type="primary", use_container_width=True)
    col_rep, col_exp = st.columns(2)
    report_btn = col_rep.button("📄 Звіт", use_container_width=True)
    export_btn = col_exp.button("⬇️ CSV", use_container_width=True)
    st.markdown("---")
    st.caption("⏰ Авто: щонеділі о 09:00")


# ── MAIN ─────────────────────────────────────────────────────────────────────
st.markdown("<style>h1 a, h2 a, h3 a { display: none !important; }</style>", unsafe_allow_html=True)
st.title("Trends Analyzer")

if run_btn:
    progress = st.progress(0)
    status = st.empty()

    def on_progress(keyword, done, total):
        progress.progress(min(done / total, 1.0))
        status.caption(f"Аналізую: **{keyword}** ({done}/{total})")

    with st.spinner("Краулер працює…"):
        try:
            count = crawl(geo=geo, timeframe=timeframe, max_niches=max_niches, progress_callback=on_progress)
            progress.progress(1.0)
            status.empty()
            st.success(f"Готово! Знайдено {count} ніш.")
            st.rerun()
        except Exception as e:
            st.error(f"Помилка: {e}")

tab_overview, tab_search, tab_history = st.tabs(["📊 Огляд", "🔍 Пошук по слову", "📋 Історія запусків"])

# ── TAB: ОГЛЯД ───────────────────────────────────────────────────────────────
with tab_overview:
    run_dates = get_all_run_dates(geo)

    if not run_dates:
        st.info("База порожня. Натисни **🚀 Запустити зараз** щоб почати.")
        st.stop()

    selected_run = st.selectbox(
        "Запуск",
        run_dates,
        format_func=lambda d: f"📅 {d}",
        index=0,
    )

    df = load_data(geo, selected_run)

    if df.empty:
        st.info("Немає даних для цього запуску.")
        st.stop()

    if report_btn:
        path = generate_report(geo=geo)
        if path:
            content = path.read_text(encoding="utf-8")
            st.download_button("⬇️ Завантажити MD звіт", content, file_name=path.name, mime="text/markdown")
        else:
            st.warning("Немає даних.")

    if export_btn:
        st.download_button("⬇️ Завантажити CSV", df.to_csv(index=False), file_name=f"niches_{selected_run}_{geo}.csv", mime="text/csv")

    st.markdown(f"**Регіон:** {GEO_LABELS[geo]} · **Всього ніш:** {len(df)}")
    m1, m2, m3 = st.columns(3)
    m1.metric("⬆️ Зростають", len(df[df.trend_direction == "growing"]))
    m2.metric("➡️ Стабільні", len(df[df.trend_direction == "stable"]))
    m3.metric("⬇️ Падають", len(df[df.trend_direction == "declining"]))

    st.markdown("---")
    st.subheader("🏆 Топ-10 ніш")
    top10 = df.head(10)
    colors = ["#2ecc71" if t == "growing" else "#3498db" if t == "stable" else "#e74c3c" for t in top10.trend_direction]
    fig = go.Figure(go.Bar(
        x=top10["score"], y=top10["keyword"], orientation="h",
        marker_color=colors, text=top10["score"].round(1), textposition="outside",
    ))
    fig.update_layout(height=340, margin=dict(l=0, r=60, t=5, b=0), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📋 Всі ніші")
    labels_dict = get_labels()

    filter_col1, filter_col2 = st.columns([1, 1])
    show_blocked = filter_col1.checkbox("Показати ❌ Не релевантно", value=False)
    show_review = filter_col2.checkbox("Показати тільки 🔍 Перевірити", value=False)

    df_filtered = df.copy()
    if not show_blocked:
        blocked_kws = {kw for kw, lbl in labels_dict.items() if lbl == "❌ Не релевантно"}
        df_filtered = df_filtered[~df_filtered["keyword"].isin(blocked_kws)]
    if show_review:
        review_kws = {kw for kw, lbl in labels_dict.items() if lbl == "🔍 Перевірити"}
        df_filtered = df_filtered[df_filtered["keyword"].isin(review_kws)]

    display = df_filtered.copy()
    display["trend_direction"] = display["trend_direction"].map(TREND_ICONS)
    display["Мітка"] = display["keyword"].map(labels_dict).fillna("")
    display.columns = ["Ніша", "Рівень", "Батьківська", "Сер. інтерес", "Тренд", "Пік", "Оцінка", "Мітка"]
    edited = st.data_editor(
        display,
        column_config={
            "Мітка": st.column_config.SelectboxColumn(
                "Мітка", options=LABEL_OPTIONS, required=False,
            )
        },
        disabled=["Ніша", "Рівень", "Батьківська", "Сер. інтерес", "Тренд", "Пік", "Оцінка"],
        hide_index=True,
        use_container_width=True,
        height=420,
    )
    for i, row in edited.iterrows():
        kw = display.iloc[i]["Ніша"]
        if row["Мітка"] != labels_dict.get(kw, ""):
            set_label(kw, row["Мітка"] or None)

    review_count = sum(1 for lbl in labels_dict.values() if lbl == "🔍 Перевірити")
    if review_count:
        st.caption(f"🔍 {review_count} ніш очікують перевірки — увімкни фільтр вище щоб переглянути")

    blocked_kws = [kw for kw, lbl in labels_dict.items() if lbl == "❌ Не релевантно"]
    if blocked_kws:
        with st.expander(f"🚫 Заблоковані слова ({len(blocked_kws)})"):
            for kw in sorted(blocked_kws):
                col_kw, col_btn = st.columns([4, 1])
                col_kw.markdown(f"`{kw}`")
                if col_btn.button("Розблокувати", key=f"unblock_{kw}"):
                    set_label(kw, None)
                    st.rerun()

    st.subheader("🔎 Суб-ніші топ-5")
    conn = sqlite3.connect(DB_PATH)
    for _, row in df.head(5).iterrows():
        subs = pd.read_sql_query(
            "SELECT related_query, value FROM related_queries WHERE keyword=? AND run_date=? AND geo=? LIMIT 8",
            conn, params=(row.keyword, selected_run, geo),
        )
        icon = "⬆️" if row.trend_direction == "growing" else "➡️" if row.trend_direction == "stable" else "⬇️"
        with st.expander(f"{icon} **{row.keyword}** — оцінка: {row.score:.0f}"):
            if subs.empty:
                st.caption("Суб-ніші не знайдено")
            else:
                for _, s in subs.iterrows():
                    st.markdown(f"- {s.related_query} `{s.value}`")
    conn.close()

# ── TAB: ПОШУК ───────────────────────────────────────────────────────────────
with tab_search:
    if search_btn and kw_input.strip():
        with st.spinner("Запитуємо Google Trends…"):
            try:
                pt = TrendReq(hl="en-US", tz=0, timeout=(10, 35), retries=2, backoff_factor=1)
                pt.build_payload([kw_input], cat=0, timeframe=timeframe, geo=geo, gprop="froogle")
                df_trend = pt.interest_over_time()
                time.sleep(random.uniform(1.5, 2.5))
                pt.build_payload([kw_input], cat=0, timeframe=timeframe, geo=geo, gprop="froogle")
                related = pt.related_queries()

                st.session_state.kw_result = {
                    "keyword": kw_input,
                    "trend": df_trend,
                    "related": related,
                }
            except Exception as e:
                st.error(f"Помилка: {e}")

    if "kw_result" in st.session_state:
        res = st.session_state.kw_result
        kw = res["keyword"]
        df_trend = res["trend"]
        related = res["related"]

        st.markdown(f"**Результати для:** `{kw}`")

        if not df_trend.empty and kw in df_trend.columns:
            series = df_trend[kw]
            if "isPartial" in df_trend.columns:
                series = series[df_trend["isPartial"] == False]
            fig_kw = go.Figure(go.Scatter(
                x=series.index, y=series.values,
                mode="lines", fill="tozeroy",
                line=dict(color="#3498db", width=2),
            ))
            fig_kw.update_layout(
                height=280, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="Інтерес (0–100)", xaxis_title="",
            )
            st.plotly_chart(fig_kw, use_container_width=True)
        else:
            st.warning("Немає даних тренду для цього запиту.")

        if related and kw in related:
            col_top, col_rising = st.columns(2)
            with col_top:
                st.markdown("**Топ схожих запитів**")
                top_df = related[kw].get("top")
                if top_df is not None and not top_df.empty:
                    for _, r in top_df.head(10).iterrows():
                        st.markdown(f"- {r['query']} `{r['value']}`")
                else:
                    st.caption("Немає даних")
            with col_rising:
                st.markdown("**Зростаючі запити**")
                rising_df = related[kw].get("rising")
                if rising_df is not None and not rising_df.empty:
                    for _, r in rising_df.head(10).iterrows():
                        st.markdown(f"- {r['query']} `{r['value']}`")
                else:
                    st.caption("Немає даних")

# ── TAB: ІСТОРІЯ ─────────────────────────────────────────────────────────────
with tab_history:
    st.subheader("Всі запуски краулера")
    hist_df = get_runs_history()

    if hist_df.empty:
        st.info("Ще не було жодного запуску.")
    else:
        hist_df["start_time"] = hist_df["start_time"].str[:16].str.replace("T", " ")
        hist_df["end_time"] = hist_df["end_time"].str[:16].str.replace("T", " ", regex=False)
        hist_df["status"] = hist_df["status"].map({"done": "✅ done", "running": "🔄 running", "error": "❌ error"}).fillna(hist_df["status"])
        hist_df["geo"] = hist_df["geo"].map(GEO_LABELS).fillna(hist_df["geo"])
        hist_df.columns = ["ID", "Початок", "Кінець", "Статус", "Ніш знайдено", "Регіон"]
        st.dataframe(hist_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.caption("Дані: Google Shopping Trends · Авто-оновлення: щонеділі")
