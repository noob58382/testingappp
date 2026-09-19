import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

APPLE_API = "https://www.apple.com/hk-zh/shop/fulfillment-messages"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.apple.com/hk/shop/buy-iphone",
}


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if not Path(STATE_FILE).exists():
        return {
            "alerted": {}
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "alerted": {}
        }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    print("Telegram notification sent successfully.")


def get_store_name(store):
    return (
        store.get("storeName")
        or store.get("storeNameEN")
        or store.get("name")
        or store.get("storeNumber")
        or "Unknown Apple Store"
    )


def get_store_number(store):
    return (
        store.get("storeNumber")
        or store.get("storeId")
        or store.get("id")
        or "UNKNOWN"
    )


def is_available_today(part_info):
    if not isinstance(part_info, dict):
        return False

    pickup_display = str(
        part_info.get("pickupDisplay", "")
    ).lower()

    store_pick_eligible = part_info.get(
        "storePickEligible"
    ) is True

    pickup_quote = str(
        part_info.get("storePickupQuote", "")
    ).lower()

    pickup_message = str(
        part_info.get("pickupMessage", "")
    ).lower()

    pickup_search_quote = str(
        part_info.get("pickupSearchQuote", "")
    ).lower()

    available = (
        pickup_display == "available"
        and store_pick_eligible
    )

    if not available:
        return False

    today_words = [
        "today",
        "今日",
        "今天"
    ]

    quote_text = (
        pickup_quote
        + " "
        + pickup_message
        + " "
        + pickup_search_quote
    )

    return any(word in quote_text for word in today_words)


def extract_stores(data):
    stores = []

    body = data.get("body", {})

    # Current / newer structure
    if isinstance(body.get("stores"), list):
        stores.extend(body["stores"])

    # Older structure
    content = body.get("content", {})

    pickup_message = content.get(
        "pickupMessage",
        {}
    )

    if isinstance(
        pickup_message.get("stores"),
        list
    ):
        stores.extend(
            pickup_message["stores"]
        )

    # Another possible structure
    pickup_message_2 = body.get(
        "PickupMessage",
        {}
    )

    if isinstance(
        pickup_message_2.get("stores"),
        list
    ):
        stores.extend(
            pickup_message_2["stores"]
        )

    # Remove duplicate stores
    unique = {}

    for store in stores:
        store_number = get_store_number(store)

        if store_number not in unique:
            unique[store_number] = store

    return list(unique.values())


def request_stock(part_numbers, timeout):
    params = {
        "fae": "true",
        "little": "false",
        "mts.0": "regular",
        "mts.1": "sticky",
        "fts": "true"
    }

    for index, part_number in enumerate(part_numbers):
        params[f"parts.{index}"] = part_number

    print()
    print("Apple API request:")
    print(APPLE_API)

    try:
        response = requests.get(
            APPLE_API,
            params=params,
            headers=HEADERS,
            timeout=timeout
        )
    except requests.RequestException as e:
        print(f"❌ Apple request failed: {e}")
        return None

    print(f"HTTP status: {response.status_code}")

    if response.status_code != 200:
        print()
        print("❌ Apple API did not return HTTP 200.")
        print(
            "This is NOT treated as 'out of stock'."
        )

        if response.status_code in (403, 541):
            print(
                "⚠️ Apple Shield / anti-bot protection "
                "may have blocked this request."
            )

        return None

    try:
        return response.json()
    except ValueError:
        print("❌ Apple response is not valid JSON.")
        return None


def check_stock(config):
    timeout = config.get(
        "timeout_seconds",
        20
    )

    products = config.get(
        "products",
        []
    )

    if not products:
        print("❌ No products configured.")
        return []

    part_numbers = [
        product["part_number"]
        for product in products
    ]

    print()
    print("=" * 70)
    print("Checking Apple Hong Kong Store inventory")
    print("=" * 70)

    print(
        "Products:",
        ", ".join(part_numbers)
    )

    data = request_stock(
        part_numbers,
        timeout
    )

    if data is None:
        return None

    stores = extract_stores(data)

    print(
        f"Apple API returned {len(stores)} store(s)."
    )

    if not stores:
        print(
            "⚠️ No stores were found in the response."
        )
        return []

    results = []

    for store in stores:
        store_name = get_store_name(store)
        store_number = get_store_number(store)

        parts_availability = store.get(
            "partsAvailability",
            {}
        )

        print()
        print(
            f"Store: {store_name} "
            f"({store_number})"
        )

        for product in products:
            part_number = product[
                "part_number"
            ]

            part_info = parts_availability.get(
                part_number,
                {}
            )

            pickup_display = part_info.get(
                "pickupDisplay",
                "unknown"
            )

            eligible = part_info.get(
                "storePickEligible",
                False
            )

            pickup_quote = part_info.get(
                "storePickupQuote",
                ""
            )

            available_today = (
                is_available_today(
                    part_info
                )
            )

            print(
                f"  {product['name']}"
            )
            print(
                f"    pickupDisplay: "
                f"{pickup_display}"
            )
            print(
                f"    storePickEligible: "
                f"{eligible}"
            )
            print(
                f"    storePickupQuote: "
                f"{pickup_quote}"
            )
            print(
                f"    TODAY AVAILABLE: "
                f"{available_today}"
            )

            if available_today:
                results.append({
                    "store_name": store_name,
                    "store_number": store_number,
                    "product_name": product["name"],
                    "part_number": part_number,
                    "pickup_quote": pickup_quote,
                    "product_url": product.get(
                        "product_url",
                        ""
                    )
                })

    return results


def build_telegram_message(matches):
    now = datetime.now().strftime(
        "%H:%M:%S"
    )

    lines = [
        f"🚨📱 Apple Store 有貨 {now}",
        ""
    ]

    for item in matches:
        lines.append(
            f"• {item['product_name']} — "
            f"{item['store_name']}"
        )

        lines.append(
            f"  備妥於：{item['pickup_quote'] or '今日'}"
        )

        lines.append("")

    urls = sorted(
        set(
            item["product_url"]
            for item in matches
            if item.get("product_url")
        )
    )

    if urls:
        lines.append(
            "🔗 Apple："
        )

        for url in urls:
            lines.append(url)

    return "\n".join(lines)


def handle_notifications(matches, state):
    alerted = state.setdefault(
        "alerted",
        {}
    )

    current_keys = set()

    new_matches = []

    for item in matches:
        key = (
            f"{item['part_number']}|"
            f"{item['store_number']}"
        )

        current_keys.add(key)

        if not alerted.get(key, False):
            new_matches.append(item)

    if new_matches:
        message = build_telegram_message(
            new_matches
        )

        print()
        print(
            "🚨 New stock detected!"
        )

        print(message)

        send_telegram(message)

        for item in new_matches:
            key = (
                f"{item['part_number']}|"
                f"{item['store_number']}"
            )

            alerted[key] = True

    # Reset stores that are no longer available.
    for key in list(alerted.keys()):
        if key not in current_keys:
            alerted[key] = False

    save_state(state)


def test_stock_logic():
    print("=" * 70)
    print("TEST MODE — FAKE APPLE STOCK")
    print("=" * 70)

    fake_part = {
        "pickupDisplay": "available",
        "storePickEligible": True,
        "storePickupQuote": "Today"
    }

    print()
    print("Fake Apple response:")
    print(fake_part)

    result = is_available_today(
        fake_part
    )

    print()
    print(
        f"Stock available today: {result}"
    )

    if result:
        print(
            "✅ Stock logic PASSED"
        )

        message = (
            "🚨📱 TEST — iPhone 18 Pro 有貨\n\n"
            "• 512GB 冰川色 — "
            "TEST Apple Store\n"
            "  備妥於：今日\n\n"
            "⚠️ 這是測試通知，不是真實庫存。"
        )

        send_telegram(message)

        print(
            "✅ Telegram test sent."
        )

    else:
        print(
            "❌ Stock logic FAILED"
        )


def main():
    config = load_config()

    test_mode = os.environ.get(
        "TEST_STOCK",
        "false"
    ).lower() == "true"

    if test_mode:
        test_stock_logic()
        return

    state = load_state()

    matches = check_stock(config)

    # VERY IMPORTANT:
    # API failure is not the same as "out of stock".
    if matches is None:
        print()
        print(
            "⚠️ Inventory check failed."
        )
        print(
            "No notification state was changed."
        )
        sys.exit(1)

    if not matches:
        print()
        print(
            "No matching today-pickup stock found."
        )

        # Reset previously alerted stores.
        handle_notifications(
            [],
            state
        )

        return

    handle_notifications(
        matches,
        state
    )


if __name__ == "__main__":
    main()
