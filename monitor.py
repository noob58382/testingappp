import html
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests

CONFIG_FILE = os.getenv("CONFIG_FILE", "config.json")
STATE_FILE = os.getenv("STATE_FILE", "state.json")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 20

def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def normalize_domain(region: str) -> str:
    region = region.strip().lower()
    if region.startswith("https://"):
        return region.rstrip("/")
    if region.startswith("http://"):
        return region.rstrip("/")
    return "https://www.apple.com/" + region.strip("/")

def today_tokens() -> set[str]:
    now = datetime.now()
    return {
        "today", "today.", "today：", "today:",
        "今天", "今日", "本日",
        now.strftime("%Y-%m-%d"),
        now.strftime("%Y/%m/%d"),
        now.strftime("%Y.%m.%d"),
        now.strftime("%m/%d"),
        now.strftime("%m-%d"),
        now.strftime("%d/%m"),
        now.strftime("%d-%m"),
    }

def is_today_quote(quote: str) -> bool:
    if not quote:
        return False
    q = html.unescape(re.sub(r"<[^>]+>", " ", quote)).strip().lower()
    q = re.sub(r"\s+", " ", q)
    if any(token.lower() in q for token in today_tokens()):
        return True
    # Some Apple locales return a weekday + date. If the exact current
    # calendar date is present, accept it even if formatting differs.
    now = datetime.now()
    date_patterns = [
        rf"\b{now.year}[-/.]{now.month:02d}[-/.]{now.day:02d}\b",
        rf"\b{now.year}[-/.]{now.month}[-/.]{now.day}\b",
    ]
    return any(re.search(p, q) for p in date_patterns)

def get_nested(d: dict, *keys: str, default=None):
    cur = d
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default

def pickup_url(domain: str, part_numbers: list[str], location: str) -> str:
    params = [("location", location)]
    for i, part in enumerate(part_numbers):
        params.append((f"parts.{i}", part))
    from urllib.parse import urlencode
    return domain + "/shop/retail/pickup-message?" + urlencode(params)

def query_apple(domain: str, part_numbers: list[str], location: str, timeout: int) -> dict:
    url = pickup_url(domain, part_numbers, location)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        "Referer": domain + "/shop/buy-iphone",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"Apple HTTP {r.status_code}: {r.text[:300]}")
    return r.json()

def extract_stores(data: dict) -> list[dict]:
    stores = get_nested(data, "body", "stores")
    if stores is None:
        stores = get_nested(data, "body", "content", "pickupMessage", "stores")
    if not isinstance(stores, list):
        raise RuntimeError("Apple response did not contain a stores array.")
    return stores

def extract_availability(store: dict, part: str) -> dict | None:
    pa = store.get("partsAvailability", {}).get(part)
    if not isinstance(pa, dict):
        return None

    # Newer Apple responses may wrap fields in messageTypes.regular.
    regular = get_nested(pa, "messageTypes", "regular", default={})
    if not isinstance(regular, dict):
        regular = {}

    pickup_display = pa.get("pickupDisplay", regular.get("pickupDisplay", ""))
    eligible = pa.get("storePickEligible", regular.get("storePickEligible", False))
    quote = (
        pa.get("pickupSearchQuote")
        or pa.get("storePickupQuote")
        or regular.get("pickupSearchQuote")
        or regular.get("storePickupQuote")
        or ""
    )
    title = (
        pa.get("storePickupProductTitle")
        or regular.get("storePickupProductTitle")
        or part
    )

    return {
        "available": pickup_display == "available" and bool(eligible),
        "pickup_display": pickup_display,
        "eligible": bool(eligible),
        "quote": quote,
        "title": title,
    }

def store_name(store: dict) -> str:
    return (
        store.get("storeName")
        or get_nested(store, "address", "address")
        or "Apple Store"
    ).strip()

def store_id(store: dict) -> str:
    return str(
        store.get("storeNumber")
        or store.get("storelistnumber")
        or store.get("storeListNumber")
        or get_nested(store, "retailStore", "storeNumber")
        or store_name(store)
    )

def send_telegram(token: str, chat_id: str, title: str, lines: list[str], url: str | None) -> None:
    text = title + "\n" + "\n".join(f"• {x}" for x in lines)
    if url:
        text += f"\n\n🔗 {url}"
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    r = requests.post(api, json=payload, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:300]}")

def validate_config(cfg: dict) -> None:
    required = ["region", "locations", "products"]
    missing = [x for x in required if x not in cfg]
    if missing:
        raise ValueError("Missing config fields: " + ", ".join(missing))
    if not isinstance(cfg["locations"], list) or not cfg["locations"]:
        raise ValueError("locations must be a non-empty list.")
    if not isinstance(cfg["products"], list) or not cfg["products"]:
        raise ValueError("products must be a non-empty list.")
    for p in cfg["products"]:
        for k in ("part_number", "name"):
            if not p.get(k):
                raise ValueError(f"Product is missing {k}: {p}")

def main() -> int:
    cfg = load_json(CONFIG_FILE, None)
    if cfg is None:
        print(f"Missing {CONFIG_FILE}. Copy config.example.json first.", file=sys.stderr)
        return 2

    validate_config(cfg)
    domain = normalize_domain(cfg["region"])
    timeout = int(cfg.get("timeout_seconds", DEFAULT_TIMEOUT))
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    state = load_json(STATE_FILE, {"alerted": {}})
    state.setdefault("alerted", {})

    products = cfg["products"]
    # Apple accepts multiple parts in one pickup request. Chunk conservatively.
    chunk_size = int(cfg.get("parts_per_request", 10))
    products_by_part = {p["part_number"]: p for p in products}
    all_found: dict[str, dict] = {}

    for start in range(0, len(products), chunk_size):
        chunk = products[start:start + chunk_size]
        parts = [p["part_number"] for p in chunk]

        for location in cfg["locations"]:
            try:
                data = query_apple(domain, parts, str(location), timeout)
                for store in extract_stores(data):
                    sid = store_id(store)
                    # Keep the first copy of a store, but merge product results.
                    existing = all_found.setdefault(sid, {
                        "store": store,
                        "products": {}
                    })
                    for part in parts:
                        a = extract_availability(store, part)
                        if a:
                            existing["products"][part] = a
            except Exception as e:
                print(f"[WARN] location={location} failed: {e}", file=sys.stderr)

    found = []
    for sid, item in all_found.items():
        store = item["store"]
        name = store_name(store)
        for part, a in item["products"].items():
            product = products_by_part[part]
            if a["available"] and is_today_quote(a["quote"]):
                key = f"{part}|{sid}"
                found.append((key, product, name, a["quote"], sid))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not found:
        print(f"[{now}] No matching today-pickup stock found.")
        return 0

    # Only alert when a product/store combination changes from not-alerted to alerted.
    new_found = []
    for key, product, name, quote, sid in found:
        if not state["alerted"].get(key, False):
            new_found.append((key, product, name, quote, sid))

    if not new_found:
        print(f"[{now}] Stock still available; no duplicate notification.")
        return 0

    by_product: dict[str, list[str]] = {}
    urls: dict[str, str] = {}
    for key, product, name, quote, sid in new_found:
        pname = product["name"]
        by_product.setdefault(pname, []).append(f"{pname} — {name} (備妥於：今日)")
        if product.get("product_url"):
            urls[pname] = product["product_url"]

    for pname, lines in by_product.items():
        title = f"🚨📱 iPhone {pname} 有貨 {datetime.now().strftime('%H:%M:%S')}"
        if telegram_token and telegram_chat_id:
            try:
                send_telegram(telegram_token, telegram_chat_id, title, lines, urls.get(pname))
                print(f"[OK] Telegram sent: {pname}")
            except Exception as e:
                print(f"[ERROR] Telegram failed: {e}", file=sys.stderr)
                # Do not mark alerted if notification failed.
                continue
        else:
            print(title)
            for line in lines:
                print("•", line)
            print("Telegram secrets not configured; console output only.")

    # Mark only after successful Telegram delivery, or always in console-only mode.
    telegram_ready = bool(telegram_token and telegram_chat_id)
    if not telegram_ready:
        for key, *_ in new_found:
            state["alerted"][key] = True
    else:
        # Telegram API was successful for the product groups above.
        for key, product, name, quote, sid in new_found:
            state["alerted"][key] = True

    save_json(STATE_FILE, state)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
