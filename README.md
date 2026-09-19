# Apple Store 庫存監控 + Telegram

這個專案會查 Apple Store 公開的自提庫存 JSON，當指定 iPhone 在查詢結果中：

- `pickupDisplay == "available"`
- `storePickEligible == true`
- `pickupSearchQuote` / `storePickupQuote` 顯示「今日」或今天日期

就用 Telegram Bot 通知。

> Apple 沒有提供一個給一般開發者使用、保證穩定的「庫存 WebSocket」。本專案使用 Apple Store 網頁背後的 pickup JSON。Apple 可以隨時改 endpoint、欄位或加強反爬限制，所以要把 `unknown / HTTP 403 / 541` 視為查詢失敗，而不是「無貨」。

## 1. 先取得 Part Number

產品名稱不是 API 查詢鍵；你需要該配置的完整 Part Number，例如 `XXXXXZA/A`（香港）或其他地區對應的 SKU。

最穩陣方法：

1. 開 Apple Store 購買頁。
2. 選定 iPhone 型號、容量、顏色。
3. 選「查看取貨情況」。
4. 開瀏覽器 DevTools → Network。
5. 找 `pickup-message` 或 `fulfillment-messages`。
6. Response 中找 `partsAvailability` 下對應的 Part Number。

不同地區的 SKU 不同，不要直接把網上找到的 SKU 當成自己的地區 SKU。

## 2. 設定 config

```bash
cp config.example.json config.json
```

然後修改：

```json
{
  "region": "https://www.apple.com/hk",
  "locations": ["000000"],
  "products": [
    {
      "name": "iPhone 18 Pro 512GB 冰川色",
      "part_number": "你的實際PART_NUMBER",
      "product_url": "https://www.apple.com/hk/shop/buy-iphone"
    }
  ]
}
```

`locations` 是 Apple pickup query 的位置參數。Apple 通常會回傳該位置附近的 Apple Store；如果要盡量覆蓋一個大型區域，可以加入多個 postcode / location anchor，程式會自動去重門市。

## 3. Telegram

向 `@BotFather` 建立 Bot，取得：

- `TELEGRAM_BOT_TOKEN`

然後向你的 Bot 發一次訊息，再用 Telegram API / Bot 工具取得：

- `TELEGRAM_CHAT_ID`

不要把 token 寫入 Python 或 Git。

## 4. 本機測試

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
cp config.example.json config.json
python monitor.py
```

環境變數：

Windows PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:TELEGRAM_CHAT_ID="123456789"
python monitor.py
```

macOS/Linux:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"
python monitor.py
```

## 5. GitHub Actions

在 GitHub Repository → Settings → Secrets and variables → Actions 建立：

- `APPLE_CONFIG_JSON`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

`APPLE_CONFIG_JSON` 就是完整 `config.json` 內容。

Workflow 位於：

`.github/workflows/stock-monitor.yml`

它大約每 5 分鐘執行一次。

### 重要

GitHub Actions 的 `schedule` 不是精準 timer，GitHub 可能延遲 scheduled run；所以如果你要求「30 秒內通知」，不要依賴 GitHub-hosted Actions。

如果要真正低延遲，建議在自己的 PC / VPS / NAS / Raspberry Pi 上長駐：

```bash
while true; do
  python monitor.py
  sleep 30
done
```

或者用 systemd / Docker / Windows Task Scheduler 長駐。

## Apple endpoint

目前常見結構：

```text
https://www.apple.com/hk/shop/retail/pickup-message
    ?parts.0=PART_NUMBER
    &location=LOCATION
```

多產品時：

```text
?parts.0=PART1
&parts.1=PART2
&location=LOCATION
```

回應常見結構：

```text
body
└── stores[]
    ├── storeName
    └── partsAvailability
        └── PART_NUMBER
            ├── storePickEligible
            ├── pickupSearchQuote
            ├── storePickupQuote
            ├── storePickupProductTitle
            └── pickupDisplay
```

判定邏輯：

```python
pickupDisplay == "available"
and storePickEligible == True
and quote indicates today
```

## 注意事項

- 只查詢，不登入、不落單、不自動購買。
- Apple 可能回 HTTP 403/541；不要把這當成無貨。
- 庫存是即時狀態，收到通知後可能已經被其他人買走。
- Apple Store pickup API 是未公開的網站內部介面，不保證長期不變。
