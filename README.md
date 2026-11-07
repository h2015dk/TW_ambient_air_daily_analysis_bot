# 台灣空品區每日空氣品質日報 LINE 機器人

每天台北時間 10:00 左右，自動抓取環境部前一天的空氣品質小時值，依 7 個空品區各產生一張分析圖，並推送到指定的 LINE 群組。

整個流程跑在 GitHub Actions 上，不需要自備伺服器或開著電腦。

## 功能

每張圖對應一個空品區（北部、竹苗、中部、雲嘉南、高屏、宜蘭、花東），包含：

- **PM2.5、NOx、SO2 逐時變化**：全區平均線，以及各測站最小到最大的範圍帶。
- **日均最高測站**：PM2.5、NOx、SO2 各自日均最高的測站，以黑色粗線疊在對應的圖上，圖例標示站名與日均值。
- **風向玫瑰圖**：徑向為次數（測站 × 小時），並標示風速加權的合成風向與平均風速。
- **最高測站摘要**：右下角列出三項污染物的最高測站、所在縣市、日均值與小時最高值。
- **統計測站名單**：圖片底部列出實際納入統計的測站（依縣市分組），並標出缺哪些測項。
- **指定比較測站**：可額外指定某測站以紫色虛線疊圖（目前設定為雲嘉南的 SO2 疊上嘉義測站）。

## 運作流程

```
GitHub Actions 排程 (每天 UTC 02:00 = 台北 10:00)
  → 抓環境部開放資料 (小時值 + 測站基本資料)
  → 以測站編號對應空品區
  → 繪製 7 張圖 → commit 到 docs/images/<日期>/
  → 透過 LINE Messaging API 推送圖片（分 4 次）
```

LINE 推送分成四組：北部＋竹苗、中部＋雲嘉南、高屏、宜蘭＋花東。

## 資料來源

| 資料集 | 用途 |
|---|---|
| [AQX_P_13 空氣品質監測小時值資料（一般污染物，每日更新）](https://data.moenv.gov.tw/dataset/detail/AQX_P_13) | PM2.5、NOx、SO2、風向、風速的逐時值 |
| [AQX_P_07 空氣品質監測站基本資料](https://data.moenv.gov.tw/dataset/detail/AQX_P_07) | 以測站編號（`siteid`）對應空品區與縣市 |

資料來自環境部環境資料開放平臺，使用時請遵守該平臺的授權條款。

## 專案結構

```
.
├── aqi_report.py                 # 主程式（build 產圖 / send 推送）
├── requirements.txt              # Python 套件
├── .github/workflows/daily.yml   # 排程設定
└── docs/images/<日期>/           # 每日產出的圖片（自動產生，只保留最近 7 天）
```

## 部署方式

### 1. 建立 repo

- 將本專案放到你自己的 GitHub repo，**必須設為 Public**。
- 原因：LINE 需要從公開 HTTPS 網址抓取圖片，本專案使用 `raw.githubusercontent.com` 提供圖片，Private repo 的網址 LINE 無法存取。
- 請勿把任何機密或業主資料放進這個 repo。

### 2. 申請環境部 API 金鑰

到[環境部環境資料開放平臺](https://data.moenv.gov.tw/)註冊會員並取得 API 金鑰。

### 3. 建立 LINE Bot

LINE 已不能直接在 Developers Console 建立 Messaging API channel，流程如下：

1. 註冊 Business ID，並建立 LINE 官方帳號。
2. 在 [LINE Official Account Manager](https://manager.line.biz/) 的「設定 → Messaging API」啟用 Messaging API，選擇 Provider（指派後不能更改）。
3. 到 [LINE Developers Console](https://developers.line.biz/console/)，在該 channel 的 **Messaging API** 分頁最下方發行 **Channel access token**。
4. 在官方帳號的「回應設定」關閉自動回應，並開啟「加入群組與多人聊天室」。
5. 將 Bot 邀請進目標群組。

### 4. 取得群組 ID

1. 到 [webhook.site](https://webhook.site/) 取得一個臨時網址。
2. 在 channel 的 Messaging API 分頁，將 **Webhook URL** 設為該網址並開啟 **Use webhook**。
3. 在群組裡傳一則訊息。
4. 在 webhook.site 收到的 JSON 中，`source.groupId`（`C` 開頭的字串）即為群組 ID。
5. 取得後可關閉 webhook。

### 5. 設定 GitHub Secrets

到 repo 的 **Settings → Secrets and variables → Actions**，新增三個 Repository secrets：

| 名稱 | 內容 |
|---|---|
| `MOENV_API_KEY` | 環境部開放資料平臺 API 金鑰 |
| `LINE_CHANNEL_TOKEN` | LINE Channel access token |
| `LINE_GROUP_ID` | LINE 群組 ID |

### 6. 設定 Actions 權限

到 **Settings → Actions → General**：

- Actions permissions：選擇 **Allow all actions and reusable workflows**。
- Workflow permissions：選擇 **Read and write permissions**（需要把圖片 commit 回 repo）。

### 7. 手動測試

到 **Actions** 分頁，選擇 *Daily air quality report* → **Run workflow**。確認：

1. `docs/images/<昨天日期>/` 底下產生 7 張 PNG。
2. LINE 群組收到圖片。

之後每天會自動執行。

## 自訂設定

以下設定都在 `aqi_report.py` 開頭附近。

| 設定 | 說明 |
|---|---|
| `HIGHLIGHT` | 額外指定要疊圖比較的測站，格式 `{空品區: {測項: 測站名稱}}`，例如 `{"雲嘉南": {"SO2": "嘉義"}}`。設為 `{}` 即停用 |
| `SEND_GROUPS` | LINE 推送的分組方式。一次請求最多 5 則訊息 |
| `ZONE_FILE` | 空品區對應的圖片檔名 |
| `find_top(..., min_hours=18)` | 「日均最高測站」要求的最少有效小時數，不足的測站不參與比較 |
| `daily.yml` 的 `cron` | 排程時間，使用 UTC。目前 `0 2 * * *` 即台北 10:00 |

## 方法說明

- **日期**：以台北時區計算「前一天」，不受 GitHub runner 使用 UTC 影響。
- **空品區對應**：兩個資料集以測站編號 `siteid` 合併，空品區名稱取自測站基本資料。不屬於這 7 區的測站（例如「其他」）不會出圖。
- **風向**：優先使用小時平均風向與風速（`WD_HR`、`WS_HR`），沒有時改用 `WIND_DIREC`、`WIND_SPEED`。合成風向以風速加權的向量平均計算，不直接對角度做算術平均。
- **有效資料**：非數值的註記碼（例如 NR）視為缺值。「日均最高測站」需至少 18 小時有效值。
- **圖片快取**：推送時在圖片網址後加上時間戳參數，避免同一天重跑時 LINE 或 GitHub 顯示舊圖。
- **圖片保留**：只保留最近 7 天的圖片，舊資料夾在每次執行時自動刪除。

## 注意事項

- **排程可能延遲**：GitHub Actions 的排程在尖峰時段常延遲 10 到 30 分鐘，不保證準點。
- **資料可能有缺漏**：前一天的資料可能尚有未完成審核或缺漏的測站，圖上已標示納入統計的測站與缺項。
- **LINE 訊息額度**：Messaging API 的訊息數以請求次數乘以收訊人數計算。每天推送 4 次，若群組人數較多，可能超過免費方案的每月額度，請定期到官方帳號後台查看用量。
- **排程可能被停用**：公開 repo 若長時間沒有活動，GitHub 可能停用排程。本流程每天會 commit 圖片，通常不會發生，若被停用請到 Actions 分頁手動啟用。
- **官方資料的正確性**：本專案僅做資料視覺化，圖表不能取代官方公告，用於正式文件前請自行核對原始資料。

## 疑難排解

| 現象 | 可能原因與處理 |
|---|---|
| `JSONDecodeError`、`抓取失敗` | API 金鑰錯誤或為空，檢查 `MOENV_API_KEY`；也可能是 API 暫時異常，log 會印出回應開頭 |
| `沒有產出任何圖` | 空品區名稱或測站編號對應失敗，看 log 中的「空品區清單」與「測站對應失敗比例」 |
| Actions 分頁看不到 workflow | `daily.yml` 必須位於 `main` 分支的 `.github/workflows/` 底下 |
| `Commit images` 失敗（403） | Workflow permissions 未設為 Read and write |
| 流程成功但 LINE 沒收到 | 看 `Send to LINE` 的 log：圖片是否存在、群組 ID 是否為 `C` 開頭、Bot 是否仍在群組內、額度是否用完 |
| LINE 顯示舊圖 | 同日重跑造成的快取，程式已加時間戳參數；舊訊息無法由 Bot 撤回 |

## 授權

請依你的需求自行補上授權條款（例如 MIT）。
