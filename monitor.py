import os
import requests

def send_test_notification():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": "🚨📱 Apple Store Stock Monitor 測試通知\n\nTelegram 通知功能正常！"
        },
        timeout=20
    )

    print(response.status_code)
    print(response.text)


if __name__ == "__main__":
    send_test_notification()
