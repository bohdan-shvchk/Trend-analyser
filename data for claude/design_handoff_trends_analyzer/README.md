# Handoff: Trends Analyzer Dashboard

## Overview
A full-featured dropshipping niche research SaaS dashboard. Users can configure crawl parameters, run a keyword/niche crawler, explore trend analytics, and manage historical crawl runs. The UI is dark-themed with a glassmorphism aesthetic and premium analytics feel.

## About the Design Files
The file `Trends Analyzer.html` in this bundle is a **design reference created in HTML/React** — a high-fidelity prototype showing the intended look, layout, and interactive behavior. It is **not production code to copy directly**. Your task is to **recreate this design in your existing codebase** (React, Next.js, Vue, etc.) using its established component libraries, routing, and state management patterns. If no codebase exists yet, React + Tailwind CSS is recommended.

## Fidelity
**High-fidelity.** The prototype uses final colors, typography, spacing, interactions, and chart rendering (Chart.js). Recreate pixel-accurately using your codebase's design system — or derive tokens directly from the values listed below if no system exists.

---

## Layout

### Shell
- `display: flex; height: 100vh; overflow: hidden`
- **Sidebar** — fixed width `270px`, full height, left-anchored
- **Main area** — flex: 1, contains topbar + scrollable content

### Sidebar
- Background: `linear-gradient(180deg, #0b1220 0%, #070c14 100%)`
- Right border: `1px solid rgba(255,255,255,0.08)`
- Header (logo area): `padding: 20px 18px 16px`, bottom border
- Body: `padding: 14px`, `overflow-y: auto`, `gap: 18px` between sections

### Topbar
- Height: `52px`, `padding: 0 24px`
- Background: `rgba(7,12,20,0.8)` + `backdrop-filter: blur(10px)`
- Bottom border: `1px solid rgba(255,255,255,0.08)`
- Contains: tab navigation (left) + status pills + avatar (right)

### Content area
- `padding: 24px`, `overflow-y: auto`
- `gap: 20px` between sections

---

## Design Tokens

### Colors
```
--bg:           #070c14          /* page background */
--bg2:          #0c1220
--bg3:          #111827
--glass:        rgba(255,255,255,0.04)   /* card background */
--glass-hover:  rgba(255,255,255,0.07)
--border:       rgba(255,255,255,0.08)
--border-bright:rgba(255,255,255,0.15)

--accent:       oklch(0.62 0.2 245)   /* electric blue — primary */
--accent-dim:   oklch(0.62 0.2 245 / 0.15)
--accent-glow:  oklch(0.62 0.2 245 / 0.3)
--violet:       oklch(0.62 0.2 285)
--violet-dim:   oklch(0.62 0.2 285 / 0.15)
--green:        oklch(0.65 0.16 155)
--green-dim:    oklch(0.65 0.16 155 / 0.15)
--amber:        oklch(0.72 0.16 75)
--amber-dim:    oklch(0.72 0.16 75 / 0.15)
--red:          oklch(0.62 0.2 25)
--red-dim:      oklch(0.62 0.2 25 / 0.15)

--text:         #e2e8f0
--text-muted:   #64748b
--text-dim:     #94a3b8
```

### Typography
- **Font families:** `DM Sans` (UI text), `DM Mono` (numbers, code)
- Body: 13px / 1.5 — DM Sans 400
- Labels/meta: 10–11px, weight 500–600, `letter-spacing: 0.3–1px`, uppercase
- Card titles: 14px, weight 700
- Metric values: 26px, weight 700, `letter-spacing: -0.5px`
- Table headers: 10.5px, weight 600, uppercase, `letter-spacing: 0.6px`
- Table cells: 12.5px, weight 400

### Spacing & Radius
- Card border-radius: `10px`
- Small elements (inputs, badges, buttons): `6px`
- Card padding: `18px 20px`
- Section gap: `20px`
- Inner gap (grids, lists): `8–14px`

### Shadows
- Primary button: `0 4px 16px oklch(0.62 0.2 245 / 0.3)`
- Primary button hover: `0 6px 20px oklch(0.62 0.2 245 / 0.3)`, `translateY(-1px)`
- Tweaks panel: `0 20px 60px rgba(0,0,0,0.5)`

### Scrollbar
- Width: `4px`; thumb: `rgba(255,255,255,0.12)`, radius `2px`

---

## Screens / Views

### Tab 1 — Overview
Four stacked sections:

#### 1. Metric Cards Grid
- `display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px`
- Each card: glass background, `border-radius: 10px`, `padding: 16px 18px`
- Top edge accent: `2px` gradient line (blue/violet/green/amber per card)
- Fields: uppercase label (11px muted), large value (26px bold colored), delta row (11px)
- Hover: `translateY(-1px)`, brighter border
- Cards: **Niches Found** (blue), **High-Score Niches** (green), **Avg Trend Score** (violet), **Labeled Niches** (amber)

#### 2. Sub-niches Top-5 (accordion)
- Full-width card
- List of 5 items, each with: rank badge, emoji icon, niche name, score, chevron
- Click to expand: shows keywords list with trend badge (↑/→/↓) + volume (DM Mono, green)
- Expanded item: `border-color: rgba(255,255,255,0.15)`
- Chevron rotates 180° on open (CSS transition 0.18s)

#### 3. Charts Row
- `display: grid; grid-template-columns: 1fr 1.3fr; gap: 14px`
- **Breakpoint:** at `≤1400px` → `grid-template-columns: 1fr` (stacks vertically)
- Left card: **Score Distribution** — horizontal bar chart (Chart.js), height `240px`
  - Colors: score ≥85 → accent blue; ≥70 → mid blue; else → violet
  - Bar thickness: 18px, border-radius: 5px
  - Dark grid lines, transparent axis borders
- Right card: **Top 10 Niches** — data table with columns: `#`, Niche (icon + name), Score (progress bar), Trend (sparkline), Comp (badge), Label (cycle button)

##### Score bar
- Track: `80px wide`, `4px tall`, `rgba(255,255,255,0.08)` background
- Fill color: green if ≥80, accent if ≥65, amber otherwise

##### Sparkline
- 8 bars, `4px wide`, `2px gap`, aligned to bottom
- Last bar: full color; others: 33% opacity
- Colors: green (up), red (down), accent (flat)

##### Competition badge
- `Low` → green-dim bg + green text
- `Med` → amber-dim bg + amber text
- `High` → red-dim bg + red text
- `border-radius: 3px`, 10px font, `padding: 2px 7px`

##### Label cycle button
Clicking cycles through: `none → relevant → blocked → review → none`
- `none`: muted border, muted text, "— Label"
- `relevant`: green border + bg-dim, green text
- `blocked`: red border + bg-dim, red text
- `review`: amber border + bg-dim, amber text
- `border-radius: 20px`, `font-size: 10.5px`, `padding: 3px 9px`

---

### Tab 2 — Trend Search

#### Trend Analysis card
- Search input (full width) + "Analyze" button + 7D/30D/90D/1Y time buttons
- Progress bar (3px, accent→violet gradient) shown while analyzing
- Line chart (Chart.js): `height: 200px`, filled gradient area, tension 0.4
  - Gradient fill: accent at 0.25 opacity → transparent
  - Points: 4px radius, accent color
- 4 stat tiles below chart: `flex: 1` each, glass bg, `border-radius: 8px`, `padding: 10px 12px`
  - Fields: uppercase label (10px muted), value (16px bold), sub-label (10.5px muted)

#### Related Keywords card
- `display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px`
- Each chip: glass bg, border, `border-radius: 6px`, `padding: 10px 12px`
- Term (12px bold), meta row: volume (accent), CPC, competition badge
- Hover: brighter border + glass-hover bg

---

### Tab 3 — Run History

#### History list
- Each row: glass card, `border-radius: 10px`, `padding: 14px 18px`, flex row
- Left: colored status dot (8px circle) — green (success) or amber (partial), with matching `box-shadow` glow
- Center: title + tag pills, meta row (time, duration, status text)
- Right: two stat columns (Niches, Keywords) in DM Mono bold
- Far right: 3 icon buttons (28×28px) — Load, Export CSV, Delete
- Delete removes the row from state

---

## Sidebar Components

### Region + Timeframe selectors
- `display: flex; gap: 7px`
- Each: `flex: 1`, glass bg, border, `border-radius: 6px`, `padding: 7px 10px`
- Custom styled `<select>`, `appearance: none`
- Focus/hover: brighter border, brighter text

### Keyword search input
- Relative-positioned wrapper, SVG search icon at `left: 10px`
- Input: `padding: 8px 10px 8px 32px`, full width
- Focus: accent border + `box-shadow: 0 0 0 3px accent-dim`

### Score slider
- `<input type="range">`, height 4px track, accent thumb with glow shadow
- Value displayed in DM Mono, accent color

### Category tree
- Each parent row: checkbox (14×14px) + label + count badge + chevron
- Chevron: rotates 90° when open
- Checked checkbox: accent background + white checkmark SVG
- Children indented `18px`, smaller checkbox (12×12px), 11.5px text
- All rows: hover → glass-hover bg, `border-radius: 6px`

### Action buttons
- **Run Crawler** (primary): `linear-gradient(135deg, accent, violet)`, white text, glow shadow. Shows progress bar + pulsing green dot when running.
- **Export Data** (ghost): glass bg, muted border + text
- Both full width, `border-radius: 6px`, `padding: 9px 14px`, `font-size: 12px`, weight 600

### Crawl status indicator
- Green-dim bg + border, pulsing green dot (CSS `@keyframes pulse` opacity 1→0.3)

---

## Interactions & Behavior

| Interaction | Behavior |
|---|---|
| Run Crawler button | Animates progress bar 0→100% (random increments ~8%/220ms), shows crawl status, disables button |
| Tab navigation | Switches between Overview / Trend Search / Run History panels |
| Category tree chevron | Collapses/expands child list with state toggle |
| Category checkbox | Adds/removes category name from `checkedCats` array |
| Label cycle button | Cycles `none → relevant → blocked → review → none` |
| Trend Search "Analyze" | Shows progress bar 0→100% (faster), re-renders chart |
| History delete button | Removes run from list |
| Sidebar keyword filter | Filters niche table rows by name (case-insensitive substring) |
| Score slider | Filters high-score metric count in real time |

### Animations
- Button hover: `translateY(-1px)`, increased shadow, `transition: all 0.15s`
- Card hover: `translateY(-1px)`, brighter border
- Chevron open/close: `transform: rotate(90deg)` or `rotate(180deg)`, `transition: 0.18s`
- Progress bar: `transition: width 0.4s`
- Crawl dot: `@keyframes pulse` — opacity oscillates 1→0.3, 1.5s infinite
- Chart.js animations: `duration: 600ms`

---

## State Management

```
niches[]          — niche data with labels (cycled on click)
checkedCats[]     — selected category names
region            — string (US/UK/DE/AU/CA/FR/JP)
timeframe         — string (7d/30d/90d/12m)
keyword           — sidebar filter string
minScore          — number 0–100
crawling          — boolean
crawlPct          — number 0–100
tab               — 'overview' | 'search' | 'history'
openSubNicheId    — number | null (accordion)
historyRuns[]     — crawl run records
searchQuery       — string
```

---

## Charts (Chart.js v4)

### Bar Chart (Score Distribution)
```js
type: 'bar', indexAxis: 'y'
barThickness: 18, borderRadius: 5, borderSkipped: false
x-axis: min 0, max 100
Grid: rgba(255,255,255,0.05)
Tick color: #64748b, font size 10–11
```

### Line Chart (Trend Search)
```js
type: 'line', tension: 0.4, fill: true
Border: accent, 2px
Gradient fill: accent 0.25 → transparent
Points: 4px radius
Y-axis: 0–100, stepSize 25
Grid: rgba(255,255,255,0.04–0.05)
```

Both charts share dark tooltip style:
```js
backgroundColor: '#111827'
borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1
titleColor: '#e2e8f0', bodyColor: '#94a3b8', padding: 10
```

---

## Assets
- No external images used
- Icons: inline SVG only (no icon library)
- Fonts: Google Fonts — `DM Sans` (300/400/500/600/700), `DM Mono` (400/500)
- Charts: Chart.js v4.4.0 (`https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js`)

---

## Files in This Package
| File | Description |
|---|---|
| `Trends Analyzer.html` | Full hi-fi prototype (React/Babel, Chart.js). Open in browser to interact. |
| `README.md` | This document — full implementation spec. |
