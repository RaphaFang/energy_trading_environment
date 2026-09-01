# Energinet Energi Data Service — 日前電價(論文的目標變數 y)

來源:https://api.energidataservice.dk/dataset/
  price_dk*    `Elspotprices`     逐時
  price15_dk*  `DayAheadPrices`   15 分鐘

## 🔑 兩個 dataset 是**接力**,不是重疊

  Elspotprices    2018-12-31 → **2025-09-30 21:00 UTC**(SDAC 改 15 分制後停止發布)
  DayAheadPrices  **2025-09-30 22:00 UTC** → 至今

2026-08-11 驗證:兩者**完美對接,沒有重疊也沒有缺口**。
DK2 在 2025-09-30 → 2026-07-31 有 29,184 筆、100% 非空、相鄰間隔全部剛好 15 分鐘。
`load_duckdb.py` 有 `price_is_15min_derived` 旗標讓這個結構斷點看得見。

🔴 **兩份不合併。** 15 分的原始解析度存下來,**不在儲存層聚合**。

## 誰在讀(整個 repo 被讀最多次的資料)
  new_src/trading/imbalance_regimes.py:66   🔴 交易主線
  new_src/data/load_duckdb.py:171,179       training view 的 TARGET y_price_eur
  new_src/heat/validate.py
  new_src/heat/waste_reallocation.py
  new_src/battery/v1_single.py

## ⚠️ 聚合成逐時要用 mean 不是 sum
價格是**強度量不是流量**。(這與 production 那邊「先 resample 再加總」是同一件事的兩面。)
在 P 於小時內為常數的前提下,簡單平均是**恆等式不是近似**。

## 🔴 三個實測到的事實
1. **`SpotPriceDKK` 最低 −3,277.4 / `SpotPriceEUR` 最低 −440.1**
   → 負電價是真的(風大又沒人用電)。**絕不能設 ge(0)。**
2. **`HourDK` 有 6 個重複** —— 秋季 DST 結束那小時,本地時間會重複。
   → 主鍵一定要用 `HourUTC`,不能用 `HourDK`。
3. **DKK/EUR 匯率是浮動的**(實測 7.000–7.500,424 個相異值)
   → 兩欄都要留,一欄導不出另一欄。