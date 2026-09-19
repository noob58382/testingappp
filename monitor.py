import os
import requests


def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

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
    return response.json()


def is_stock_available(part):
    pickup_display = str(part.get("pickupDisplay", "")).lower()
    store_pick_eligible = part.get("storePickEligible") is True
    pickup_quote = str(part.get("storePickupQuote", "")).lower()

    available = (
        pickup_display == "available"
        and store_pick_eligible
        and "today" in pickup_quote
    )

    print(f"pickupDisplay: {pickup_display}")
    print(f"storePickEligible: {store_pick_eligible}")
    print(f"storePickupQuote: {pickup_quote}")
    print(f"Stock available: {available}")

    return available


def test_stock_logic():
    print("=" * 50)
    print("TESTING APPLE STORE STOCK LOGIC")
    print("=" * 50)

    # Fake Apple Store response
    fake_store = {
        "storeName": "TEST Apple Store",
        "storeNumber": "TEST001",
        "partsAvailability": {
            "TESTPART": {
                "pickupDisplay": "available",
                "storePickEligible": True,
                "storePickupQuote": "Today"
            }
        }
    }

    part_number = "TESTPART"
    part = fake_store["partsAvailability"][part_number]

    print("\nSimulated Apple response:")
    print(part)

    print("\nChecking stock...")

    available = is_stock_available(part)

    if available:
        print("\n✅ STOCK LOGIC PASSED")
        print("Sending test Telegram notification...")

        message = (
            "🚨📱 TEST — iPhone 18 Pro 有貨\n\n"
            "• 512GB 冰川色 — TEST Apple Store "
            "(備妥於：今日)\n\n"
            "⚠️ 這是測試通知，不是真實庫存。"
        )

        send_telegram(message)

        print("✅ Telegram test notification sent.")

    else:
        print("\n❌ STOCK LOGIC FAILED")
        print("Telegram notification was NOT sent.")


if __name__ == "__main__":
    test_stock_logic()
