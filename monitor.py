import os
import requests

def test_stock_logic():
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

    part = fake_store["partsAvailability"]["TESTPART"]

    available = (
        part.get("pickupDisplay") == "available"
        and part.get("storePickEligible") is True
        and "today" in part.get("storePickupQuote", "").lower()
    )

    print("Stock available:", available)

    if available:
        message = """🚨📱 TEST — iPhone 18 Pro 有貨

• 512GB 冰川色 — TEST Apple Store (備妥於：今日)

⚠️ 這是測試通知，不是真實庫存。"""

        send_telegram(message)
