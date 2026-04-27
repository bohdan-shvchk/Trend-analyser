import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

TAXONOMY_URL = "https://www.google.com/basepages/producttype/taxonomy.en-US.txt"
CACHE_PATH = Path(__file__).parent / "data" / "taxonomy_cache.txt"
CONFIG_PATH = Path(__file__).parent / "data" / "categories_config.json"
CACHE_TTL_DAYS = 7

DEFAULT_ENABLED = [
    "Animals & Pet Supplies > Pet Supplies > Dog Supplies",
    "Animals & Pet Supplies > Pet Supplies > Cat Supplies",
    "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils",
    "Home & Garden > Bathroom Accessories",
    "Home & Garden > Decor",
    "Home & Garden > Lawn & Garden > Gardening",
    "Electronics > Communications > Telephony > Mobile Phone Accessories",
    "Electronics > Computers & Electronics > Computer Accessories & Peripherals",
    "Electronics > Home Automation",
    "Vehicles & Parts > Vehicle Parts & Accessories > Car Electronics",
    "Vehicles & Parts > Vehicle Parts & Accessories > Auto Interior Accessories",
    "Sporting Goods > Exercise & Fitness > Fitness Equipment",
    "Sporting Goods > Exercise & Fitness > Yoga & Pilates",
    "Baby & Toddler > Baby Safety",
    "Baby & Toddler > Nursery Furniture & Décor",
    "Apparel & Accessories > Handbags, Wallets & Cases > Handbags",
    "Apparel & Accessories > Jewelry > Watches",
    "Furniture > Outdoor Furniture",
    "Toys & Games > Toys > Educational Toys",
    "Health & Beauty > Personal Care > Hair Care",
]


def fetch_taxonomy() -> str:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_PATH.exists():
        mtime = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
        if datetime.now() - mtime < timedelta(days=CACHE_TTL_DAYS):
            return CACHE_PATH.read_text(encoding="utf-8")
    resp = requests.get(TAXONOMY_URL, timeout=15)
    resp.raise_for_status()
    text = resp.text
    CACHE_PATH.write_text(text, encoding="utf-8")
    return text


def parse_taxonomy(text: str) -> dict:
    tree: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(">")]
        node = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]
    return tree


def load_config() -> list[str]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_ENABLED)
        return list(DEFAULT_ENABLED)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(enabled_paths: list[str]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(enabled_paths, indent=2, ensure_ascii=False), encoding="utf-8")


def _collect_descendants(node: dict, result: set, depth: int = 0, max_depth: int = 4) -> None:
    """Add all descendant leaf names from a taxonomy node."""
    if depth >= max_depth:
        return
    for name, children in node.items():
        result.add(name)
        if children:
            _collect_descendants(children, result, depth + 1, max_depth)


def get_seeds() -> list[str]:
    enabled = load_config()
    if not enabled:
        return []

    try:
        text = fetch_taxonomy()
        tree = parse_taxonomy(text)
    except Exception:
        # Fallback: just use leaf names
        return [path.split(">")[-1].strip() for path in enabled]

    seeds: set[str] = set()
    for path in enabled:
        parts = [p.strip() for p in path.split(">")]
        # Navigate to the node in the tree
        node = tree
        for part in parts:
            if part in node:
                node = node[part]
            else:
                node = None
                break
        # Add the leaf name itself
        seeds.add(parts[-1])
        # Add all descendants of this node
        if node:
            _collect_descendants(node, seeds)

    return list(seeds)


def get_taxonomy_tree() -> dict:
    try:
        text = fetch_taxonomy()
        return parse_taxonomy(text)
    except Exception:
        return {}


if __name__ == "__main__":
    seeds = get_seeds()
    print(f"Seeds ({len(seeds)}): {seeds}")
