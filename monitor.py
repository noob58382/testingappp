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


if __name__ == "__main__":
    test_stock_logic()
