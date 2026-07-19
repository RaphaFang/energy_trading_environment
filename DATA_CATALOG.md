# 資料字典 — DK1/DK2 電價預測 pipeline

> 一份表看懂:**每個資料從哪來、有哪些欄位、留哪些丟哪些、變成哪個檔、會不會 leak**。
> Leak 規則見 `~/.claude/.../memory/weather-no-leak.md`:預測 D 日價格,只能用 D-1 就拿得到的資訊。

## 因果鏈:先搞懂每個源站在哪一層

```
天氣(風速/輻射/雲量/溫度)  →  [轉換]  →  出力 MW(風/光)  →  ┐
   ↑ Open-Meteo(2 點,原料)          ↑ Energinet/ENTSO-E(半成品)   │
                                                                    ├→  價格 y
需求(負載)、跨境容量、水庫水位、燃料價 ─────────────────────────────┘
```

- **出力 MW 預測比天氣更接近價格**(TSO 已幫你把全區風機做完空間聚合 + 物理轉換)。
- **天氣仍要留**:溫度→需求、且能讓模型修正官方預測的殘差。
- **Energinet 管丹麥自己(一手最準),ENTSO-E 管鄰居和負載,Open-Meteo 管溫度+殘差校正。三者不重疊。**

---

## 主表:來源 → 欄位 → 檔案

| #   | 來源(API/dataset)                           | 抓取腳本                        | 輸出檔                                 | 角色                        | Leak                   |
| --- | ------------------------------------------- | ------------------------------- | -------------------------------------- | --------------------------- | ---------------------- |
| 1   | Energinet `Elspotprices`                    | `new_src/data/elspot_price.py`       | `new_data/price/price_*.parquet`       | **目標 y**                  | —                      |
| 2   | Open-Meteo `historical-forecast-api`        | `new_src/data/weather_forecast.py`   | `new_data/weather/weather_*.parquet`   | 天氣(溫度+殘差)             | leak-free              |
| 3   | Energinet `Forecasts_Hour`                  | `new_src/data/energinet_forecast.py` | `new_data/forecast/forecast_*.parquet` | **DK 風光出力(主力)**       | 只 DayAhead 免 leak    |
| 4   | Energinet `ProductionConsumptionSettlement` | `new_src/data/residual_demand.py`    | `new_data/residual/residual_*.parquet` | 負載/residual(**只當 lag**) | 實測 → 同時刻會 leak   |
| 5   | 計算(無 API)                                | `new_src/data/calendar_features.py`  | `new_data/calendar/calendar_*.parquet` | Tier-1 特徵 + **spine**     | 決定性,零 leak         |
| 6   | ENTSO-E Transparency                        | `new_src/data/entsoe_features.py` ⏳ | `new_data/entsoe/*.parquet`            | **Tier-2 鄰居+DK負載**      | 全 day-ahead,leak-free |
| 7   | ENTSO-E 水庫 / 天然氣TTF / CO2              | (未建)                          | —                                      | Tier-3 慢變數               | leak-free(週/日公布)   |
| —   | 合併                                        | `new_src/data/load_duckdb.py`        | `new_data/energy.duckdb`               | 5 源 → `training` view      | —                      |

---

## 各源欄位:留 / 丟

### 1. Elspotprices（目標 y）

| 欄位                   | 留/丟       | 說明                                    |
| ---------------------- | ----------- | --------------------------------------- |
| `SpotPriceEUR`         | ✅ **目標** | 訓練的 y                                |
| `PriceArea`, `HourUTC` | ✅ key      | join 鍵                                 |
| `SpotPriceDKK`         | ❌ 丟       | 跟 EUR 只差匯率,共線                    |
| `HourDK`               | ❌ 丟       | 跟 HourUTC 重複(本地時間由 calendar 給) |

- 覆蓋:2018-12-31 → **2025-09-30**(hourly 停在 15 分鐘制度切換)。

### 2. Open-Meteo 天氣（2 點:DK1 56/9、DK2 55.7/12.3）

| 欄位                                                     | 留/丟       | 說明                                      |
| -------------------------------------------------------- | ----------- | ----------------------------------------- |
| `temperature_2m`                                         | ✅ **重點** | 唯一的需求(暖/冷氣)驅動                   |
| `wind_speed_100m`,`wind_gusts_10m`,`wind_direction_100m` | 🟡 次要     | 風出力主力用 #3 的 MW 預測;這留當殘差校正 |
| `shortwave/direct/diffuse_radiation`,`cloud_cover`       | 🟡 次要     | 同上,太陽出力主力用 MW 預測               |

- 覆蓋:2019-01 → 2026-07。**不值得為風光加更多點**——區級 MW 預測已做完聚合。

### 3. Energinet Forecasts_Hour（DK 風光出力,主力）

| 欄位                                                                 | 留/丟              | 說明                                 |
| -------------------------------------------------------------------- | ------------------ | ------------------------------------ |
| `ForecastDayAhead`                                                   | ✅ **唯一免 leak** | pivot 成 offshore/onshore/solar 三欄 |
| `ForecastIntraday`,`Forecast5Hour`,`Forecast1Hour`,`ForecastCurrent` | ❌ 丟              | 對「隔日」預測全都 leak              |
| `ForecastType`,`HourUTC`,`PriceArea`                                 | ✅ key             | Offshore Wind / Onshore Wind / Solar |

- 覆蓋:**2019-10-31** 起(dataset 起點,決定左邊界)。DuckDB 內 → `offshore_wind_da_mwh` / `onshore_wind_da_mwh` / `solar_da_mwh`。

### 4. ProductionConsumptionSettlement（負載/residual,只當 lag）

| 欄位                      | 留/丟                 | 說明                                |
| ------------------------- | --------------------- | ----------------------------------- |
| `load_mwh`,`residual_mwh` | ✅ **只當 lag(≥24h)** | `load_lag24`,`residual_lag24`       |
| `wind_mwh`,`solar_mwh`    | 🟡                    | 實測出力,同樣只能 lag;風光隔日用 #3 |

- ⚠️ 全是**事後實測**:當 target/lag 不 leak,當同時刻特徵**必 leak**。且結算有公布延遲,lag 要留夠安全。

### 5. Calendar（Tier-1,零 leak,同時是 spine）

- ✅ 全留:`hour/dow/month/doy/is_weekend/is_holiday/holiday_name`、cyclical `*_sin/*_cos`、`daylight_hours/sunrise_hour/sunset_hour/is_daylight`。
- 決定性(只靠時間戳+緯度),可無限往未來算 → 當連續每小時 spine,其餘 LEFT JOIN 掛上。

### 6. ENTSO-E（Tier-2,⏳ 等 token）— 已修正分工

| 抓什麼        | 區域                  | method                                 | 為什麼                                    |
| ------------- | --------------------- | -------------------------------------- | ----------------------------------------- |
| 隔日負載預測  | `DK_1`,`DK_2`         | `query_load_forecast`                  | 補 Energinet 缺口(它沒 load 預測)         |
| 隔日風光預測  | `DE_LU`,`SE_3`,`SE_4` | `query_wind_and_solar_forecast`        | **純鄰居**;德國管波動                     |
| 隔日 NTC 容量 | 全邊界                | `query_net_transfer_capacity_dayahead` | 一個 method 打完,告訴模型每條線隔日開多大 |

- ❌ **不抓 DK_1/DK_2 的風光**:那份 ENTSO-E 資料本來就是 Energinet 報上去的,同源、共線,重複沒意義。
- ⚠️ 雷點:**每 request 最多 1 年**(腳本已加年切分);start/end 要帶 tz;回傳型別 Series/DataFrame 不一(已處理)。
- 鄰居拓撲隨歷史變:**用 DE_LU/NO_2/SE_3(DK1)+ DE_LU/SE_4(DK2)+ 內部 DK1–DK2;NL 可選;GB(2023-12 才上線)跳過**。別信 entsoe-py 寫死的 `NEIGHBOURS` 靜態表。

### 7. Tier-3（未建,慢變數）

- **水庫蓄水位**(ENTSO-E `query_aggregate_water_reservoirs_and_hydro_storage`,NO/SE):北歐電價**地板**(water value)。週資料 → forward-fill。leak-free(公布上週實測)。
- **天然氣 TTF + CO2 EUA**:火力邊際成本 → 2021–22 高價 regime 的真正解釋變數。

---

## 合併與可訓練窗（load_duckdb.py）

- 5 源標準化成 `(timestamp_utc, area)`,calendar 當 spine,其餘 LEFT JOIN(零 fan-out,缺口留 NULL)。
- lag 在 spine 上用 window function 算:`price_lag24/168`、`load_lag24`、`residual_lag24`(只碰 ≥24h 舊值 → leak-safe)。
- **可訓練 ~103,150 列:2019-11-01 → 2025-09-30**(左界卡 #3 forecast,右界卡 #1 price)。
- 取法:`SELECT * FROM training WHERE y_price_eur IS NOT NULL AND solar_da_mwh IS NOT NULL`。

## 日期邊界一覽

| 邊界          | 卡在哪                        | 原因                                                 |
| ------------- | ----------------------------- | ---------------------------------------------------- |
| 左 2019-10-31 | Energinet Forecasts_Hour 起點 | 早於此沒有官方隔日出力預測                           |
| 右 2025-09-30 | Elspotprices(hourly)止        | 歐洲 SDAC 改 15 分鐘 MTU;之後價格搬 `DayAheadPrices` |