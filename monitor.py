import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from playwright.sync_api import sync_playwright


CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

APPLE_SITE = "https://www.apple.com/hk-zh"
APPLE_BUY_URL = "https://www.apple.com/hk-zh/shop/buy-iphone"
APPLE_PICKUP_API = (
    "https://www.apple.com/hk-zh/shop/retail/pickup-message"
)


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if not Path(STATE_FILE).exists():
        return {"alerted": {}}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"alerted": {}}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing"
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    print("✅ Telegram notification sent.")


def is_available_today(part):
    if not isinstance(part, dict):
        return False

    pickup_display = str(
        part.get("pickupDisplay", "")
    ).lower()

    eligible = (
        part.get("storePickEligible") is True
    )

    quote = str(
        part.get("storePickupQuote", "")
    )

    search_quote = str(
        part.get("pickupSearchQuote", "")
    )

    message = str(
        part.get("pickupMessage", "")
    )

    text = (
        quote
        + " "
        + search_quote
        + " "
        + message
    ).lower()

    today = (
        "today" in text
        or "今日" in text
        or "今天" in text
    )

    return (
        pickup_display == "available"
        and eligible
        and today
    )


def get_store_name(store):
    return (
        store.get("storeName")
        or store.get("storeNameEN")
        or store.get("name")
        or store.get("storeNumber")
        or "Unknown Apple Store"
    )


def request_pickup_data(
    page,
    part_numbers
):
    print()
    print("=" * 70)
    print("Opening Apple Hong Kong Store...")
    print("=" * 70)

    try:
        page.goto(
            APPLE_BUY_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(5000)

    except Exception as e:
        print(
            f"❌ Apple page failed to load: {e}"
        )
        return None

    print(
        "Apple page loaded."
    )

    params = {
        "pl": "true",
        "mts.0": "regular"
        "location": "Hong Kong"
    }

    for index, part_number in enumerate(
        part_numbers
    ):
        params[
            f"parts.{index}"
        ] = part_number

    query = urlencode(
        params
    )

    api_url = (
        f"{APPLE_PICKUP_API}?{query}"
    )

    print()
    print(
        "Pickup API URL:"
    )
    print(
        api_url
    )

    try:
        # Use the browser's existing
        # Apple session/cookies.
        result = page.evaluate(
            """
            async (url) => {
                const response = await fetch(
                    url,
                    {
                        method: "GET",
                        credentials: "include",
                        headers: {
                            "Accept": "application/json, text/plain, */*"
                        }
                    }
                );

                const text = await response.text();

                return {
                    status: response.status,
                    url: response.url,
                    text: text
                };
            }
            """,
            api_url
        )

    except Exception as e:
        print()
        print(
            f"❌ Browser API request failed: {e}"
        )
        return None

    status = result.get(
        "status"
    )

    print()
    print(
        f"Pickup API HTTP status: {status}"
    )

    if status != 200:
        print()
        print(
            "❌ Apple pickup API did not "
            "return HTTP 200."
        )

        body = result.get(
            "text",
            ""
        )

        print(
            f"Response length: {len(body)}"
        )

        if body:
            print(
                "Response preview:"
            )
            print(
                body[:500]
            )

        return None

    try:
        data = json.loads(
            result["text"]
        )

    except Exception as e:
        print()
        print(
            f"❌ Apple response is not JSON: {e}"
        )
        return None

    print()
    print(
        "✅ Apple pickup JSON received."
    )

    return data


def extract_stores(data):
    body = data.get(
        "body",
        {}
    )

    stores = body.get(
        "stores",
        []
    )

    if isinstance(
        stores,
        list
    ):
        return stores

    return []


def check_stock(config):
    products = config.get(
        "products",
        []
    )

    if not products:
        raise RuntimeError(
            "No products configured."
        )

    part_numbers = [
        product["part_number"]
        for product in products
    ]

    print()
    print(
        f"Product(s): "
        f"{', '.join(part_numbers)}"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]
        )

        context = browser.new_context(
            locale="zh-HK",
            timezone_id="Asia/Hong_Kong",
            viewport={
                "width": 1440,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        data = request_pickup_data(
            page,
            part_numbers
        )

        browser.close()

    if data is None:
        return None

    stores = extract_stores(
        data
    )

    print()
    print(
        f"Apple returned "
        f"{len(stores)} store(s)."
    )

    if not stores:
        print(
            "❌ No stores found in Apple response."
        )

        return None

    matches = []

    for store in stores:

        store_name = get_store_name(
            store
        )

        store_number = (
            store.get(
                "storeNumber",
                "UNKNOWN"
            )
        )

        availability = store.get(
            "partsAvailability",
            {}
        )

        print()
        print(
            f"🏪 {store_name} "
            f"({store_number})"
        )

        for product in products:

            part_number = product[
                "part_number"
            ]

            part = availability.get(
                part_number,
                {}
            )

            available = (
                is_available_today(
                    part
                )
            )

            print(
                f"   Product: "
                f"{product['name']}"
            )

            print(
                f"   pickupDisplay: "
                f"{part.get('pickupDisplay', 'unknown')}"
            )

            print(
                f"   storePickEligible: "
                f"{part.get('storePickEligible', False)}"
            )

            print(
                f"   storePickupQuote: "
                f"{part.get('storePickupQuote', '')}"
            )

            print(
                f"   pickupSearchQuote: "
                f"{part.get('pickupSearchQuote', '')}"
            )

            print(
                f"   TODAY AVAILABLE: "
                f"{available}"
            )

            if available:

                matches.append({
                    "store_name": store_name,
                    "store_number": store_number,
                    "product_name": product[
                        "name"
                    ],
                    "part_number": part_number,
                    "pickup_quote": (
                        part.get(
                            "storePickupQuote"
                        )
                        or part.get(
                            "pickupSearchQuote"
                        )
                        or "今日"
                    ),
                    "product_url": product.get(
                        "product_url",
                        APPLE_BUY_URL
                    )
                })

    return matches


def build_message(matches):

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
            f"  備妥於："
            f"{item['pickup_quote']}"
        )

        lines.append("")

    lines.append(
        "🔗 Apple："
        + matches[0]["product_url"]
    )

    return "\n".join(lines)


def test_stock():
    print()
    print(
        "=" * 70
    )
    print(
        "🧪 TEST STOCK MODE"
    )
    print(
        "=" * 70
    )

    fake_part = {
        "pickupDisplay": "available",
        "storePickEligible": True,
        "storePickupQuote": "Today"
    }

    if is_available_today(
        fake_part
    ):

        message = (
            "🚨📱 TEST — iPhone 18 Pro 有貨\n\n"
            "• 512GB 冰川色 — TEST Apple Store\n"
            "  備妥於：今日\n\n"
            "⚠️ 測試通知，並非真實庫存。"
        )

        send_telegram(
            message
        )

        print(
            "✅ Test Telegram sent."
        )

    else:
        print(
            "❌ Test stock logic failed."
        )


def main():

    test_mode = (
        os.environ.get(
            "TEST_STOCK",
            "false"
        ).lower()
        == "true"
    )

    if test_mode:
        test_stock()
        return

    config = load_config()

    state = load_state()

    matches = check_stock(
        config
    )

    if matches is None:

        print()
        print(
            "❌ Inventory check failed."
        )

        print(
            "No stock conclusion was made."
        )

        sys.exit(1)

    if not matches:

        print()
        print(
            "No matching today-pickup "
            "stock found."
        )

        return

    message = build_message(
        matches
    )

    print()
    print(
        message
    )

    send_telegram(
        message
    )


if __name__ == "__main__":
    main()
