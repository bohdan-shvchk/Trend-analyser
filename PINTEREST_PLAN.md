# План: Pinterest Crawler — Ідентичний Google Trends

## 1. Default Categories для Pinterest

### Pinterest Product Categories (дефолтні seeds)

Замість ручного введення, мають бути готові категорії як у Google Taxonomy.

**Категорії (рівень 1):**
- Home & Decor
- Fashion & Accessories
- Health & Beauty
- Food & Recipes
- DIY & Crafts
- Garden & Outdoor
- Pets & Animals
- Sports & Fitness
- Weddings & Events
- Kids & Toys

**Підкатегорії (рівень 2) — приклад для Home & Decor:**
- Interior Design
- Furniture
- Wall Decor
- Kitchen Organization
- Bedroom Ideas
- Living Room
- Bathroom
- Office Decor

**Дефолтні seeds генеруються з листу підкатегорій (рівень 2).**

---

## 2. Алгоритм експансії (як у Google)

### BFS структура

```
Seed: "yoga mat"
│
├─ L1 (related suggestions):
│  ├─ yoga mat designs (vol: 120K)
│  ├─ yoga mat non-slip (vol: 95K)
│  ├─ eco-friendly yoga mat (vol: 78K)
│  └─ ...
│
├─ L2 (from L1):
│  ├─ mandala yoga mat designs (vol: 45K)
│  ├─ abstract yoga mat (vol: 38K)
│  └─ ...
│
└─ L3 (from L2):
   ├─ colorful mandala yoga mat (vol: 12K)
   └─ ...
```

**Логіка:**
1. Стартує з seed (напр. "yoga mat")
2. Запитує `GET /v5/keywords/suggestions` → отримує список related keywords
3. Top-10 suggestions → додає в чергу як L1
4. Для кожного L1 → повторює процес → L2
5. Для кожного L2 → повторює процес → L3
6. Зупиняється на L3

**Результат:** Одна ніша = 1 seed + всі розгалуження = ~100–200 ключових слів в одній групі

---

## 3. Scoring & Metrics

| Метрика | Google | Pinterest |
|---------|--------|-----------|
| Основна оцінка | avg_interest | monthly_volume_est |
| Нормалізація | 0–100 (залежно від даних) | 0–100 (залежно від даних) |
| Trend direction | growing/stable/declining | [НЕ ДОСТУПНО — Pinterest не дає часових рядів] |
| Trend multiplier | 1.5 / 1.0 / 0.5 | [Не застосовується] |

**Pinterest специфіка:** Немає часових рядів, тільки поточний обсяг. Trend direction = не буде.

---

## 4. База даних

### Таблиці (нові + зміни)

```sql
-- Категорії
CREATE TABLE pinterest_categories (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
    level INTEGER,  -- 1 = top, 2 = subcategory
    parent_id INTEGER,
    enabled BOOLEAN DEFAULT 1
);

-- Seeds (генеруються з категорій)
CREATE TABLE pinterest_seeds (
    id INTEGER PRIMARY KEY,
    keyword TEXT UNIQUE,
    category_id INTEGER,
    FOREIGN KEY(category_id) REFERENCES pinterest_categories(id)
);

-- Результати краулінгу
CREATE TABLE pinterest_niches (
    keyword TEXT,
    level INTEGER,
    parent TEXT,
    pin_volume REAL,
    score REAL,  -- normalized 0-100
    run_date TEXT,
    PRIMARY KEY (keyword, run_date)
);

-- Запуски
CREATE TABLE pinterest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT,
    end_time TEXT,
    status TEXT,
    niches_found INTEGER,
    category TEXT,  -- яка категорія була seed
    run_type TEXT  -- 'single_seed' або 'category'
);
```

---

## 5. API Endpoints

| Endpoint | Метод | Параметри | Результат |
|----------|-------|-----------|-----------|
| `/api/pinterest/categories` | GET | - | Список категорій з enabled флагом |
| `/api/pinterest/categories` | POST | `{enabled: [...]}` | Зберігає вибір |
| `/api/pinterest/crawl` | POST | `{category: "...", max_keywords: 200}` | Старт краулу |
| `/api/pinterest/crawl/status` | GET | - | {running, pct, current_keyword} |
| `/api/pinterest/niches` | GET | `run_date` | Список ніш з scores |
| `/api/pinterest/runs` | GET | - | Історія запусків |
| `/api/pinterest/search` | GET | `keyword` | Пошук по одному слову (volume + suggestions) |
| `/api/pinterest/export` | GET | `run_date` | CSV export |

---

## 6. UI (Frontend)

### Sidebar

```
┌─ Джерело ──────────────────┐
│ [Google Trends] [Pinterest] │
└─────────────────────────────┘

{source === 'pinterest' && (
  <div>
    {/* Categories */}
    <div className="sec-label">Категорії</div>
    <CategoryTree
      categories={pinterestCategories}
      enabled={pEnabledCategories}
      onToggle={togglePCategory}
    />

    {/* Controls */}
    <div className="sec-label">Краулер</div>
    <select value={pSelectedCategory}>
      <option>-- Вибери категорію --</option>
      {pinterestCategories.map(c => <option key={c.id}>{c.name}</option>)}
    </select>

    <input type="number" 
      value={pMaxKeywords} 
      placeholder="Макс ключів" 
      min={10} max={500} step={10}
    />

    <button onClick={startPinterestCrawl}>
      {pCrawling ? `${pCrawlPct}%` : 'Pinterest Crawl'}
    </button>
  </div>
)}
```

### Вкладки (Pinterest)

- **Pinterest Огляд** — таблиця ніш, метрики (кількість, макс volume)
- **Pinterest Історія** — запуски по категоріям, розкриття з таблицею ніш
- **Pinterest Пошук** — (як у Google) пошук по конкретному слову через Pinterest API

---

## 7. Порядок реалізації

1. **pinterest_categories.json** — дефолтні категорії + підкатегорії (JSON конфіг)
2. **pinterest_crawler.py** — оновити:
   - `get_default_seeds()` — повертає seeds для вибраної категорії
   - `crawl_pinterest(category, ...)` — приймає категорію замість seed
3. **server.py** — нові endpoints для категорій
4. **static/index.html** — CategoryTree для Pinterest, вибір категорії перед краулом
5. **Тестування** — запустити краулер для однієї категорії, перевірити структуру

---

## 8. Приклад результату

**Seed категорія:** "Home & Decor > Kitchen Organization"

**Дефолтний seed:** "kitchen organization"

**L1 (related keywords):**
- kitchen storage ideas
- kitchen drawer organization
- under sink organization
- pantry organization
- kitchen cabinet organization

**L2 (from "kitchen storage ideas"):**
- small kitchen storage ideas
- kitchen storage ideas with baskets
- kitchen storage ideas on a budget
- modern kitchen storage ideas

**Фінальний result:** ~150 ключових слів в групі "kitchen organization"

---

## 9. Різниці від Google

| Функція | Google | Pinterest |
|---------|--------|-----------|
| Default seeds | Taxonomy | Categories (кастомні) |
| Trend direction | Є | НЕ |
| Geo-таргетинг | Є | Глобально |
| Timeframe | 7D/30D/1Y | Не підтримується |
| Search функція | Є (з графіком) | Є (тільки обсяг) |
| Export | CSV + MD | CSV + MD |

---

## 10. Що перенести з Google

✓ BFS логіка  
✓ Структура БД (таблиці, schemas)  
✓ API endpoints паттерн  
✓ UI pattern (категорії, краулер, історія)  
✓ Auto-classification (labels)  
✓ Manual labels (relevant/review/blocked/priority)  
✓ Export функція  

---

## Статус

**Завершено:** BFS логіка, API endpoints базові  
**Потрібно:** Default категорії, UI категорій, Search endpoint
