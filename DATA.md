# 資料手冊 — 來源、欄位、坑、合併規則

> 合併自舊的 `DATA_CATALOG.md` + `TIER2_SCHEMA.md` + `TIER2_TIER3_FINDINGS.md`(2026-08-07)。
> 一份表看懂:**每個資料從哪來、有哪些欄位、留哪些丟哪些、變成哪個檔、會不會 leak**。
> 程式在 `new_src/data/`;合併在 `load_duckdb.py`;現況盤點見 `STATUS.md`。

**Leak 總規則**:預測 D 日的價格,只能用 D-1 就拿得到的資訊。天氣一定用 day-ahead 預報,
不能用事後實測(ERA5);燃料用 ≤ D-2 收盤;同時刻實測只能當 lag。

---

## 0. 因果鏈:先搞懂每個源站在哪一層

```
天氣(風速/輻射/雲量/溫度)  →  [轉換]  →  出力 MW(風/光)  →  ┐
   ↑ Open-Meteo(2 點,原料)          ↑ Energinet/ENTSO-E(半成品)   │
                                                                    ├→  價格 y
需求(負載)、跨境容量、水庫水位、燃料價 ─────────────────────────────┘
```

- **出力 MW 預測比天氣更接近價格**(TSO 已幫你做完空間聚合 + 物理轉換)。
- **天氣仍要留**:溫度→需求,且能讓模型修正官方預測的殘差。
- **Energinet 管丹麥自己(一手最準),ENTSO-E 管鄰居和負載,Open-Meteo 管溫度+殘差校正。三者不重疊。**

---

## 1. 主表:來源 → 腳本 → 檔案

| #   | 來源(dataset)                               | 腳本                       | 輸出                                      | 角色                          | Leak                 |
| --- | ------------------------------------------- | -------------------------- | ----------------------------------------- | ----------------------------- | -------------------- |
| 1   | Energinet `Elspotprices`                    | `elspot_price.py`          | `new_data/price/`                         | **目標 y**                    | —                    |
| 2   | Open-Meteo `historical-forecast-api`        | `weather_forecast.py`      | `new_data/weather/`                       | 天氣(溫度+殘差校正)           | leak-free            |
| 3   | Energinet `Forecasts_Hour`                  | `energinet_forecast.py`    | `new_data/forecast/`                      | **DK 風光出力(主力)**         | 只 DayAhead 免 leak  |
| 4   | Energinet `ProductionConsumptionSettlement` | `residual_demand.py`       | `new_data/residual_*.parquet`             | 負載/residual(**只當 lag**)   | 實測 → 同時刻會 leak |
| 5   | 計算(無 API)                                | `calendar_features.py`     | `new_data/calendar/`                      | Tier-1 特徵 + **spine**       | 決定性,零 leak       |
| 6   | ENTSO-E Transparency                        | `entsoe_features.py`       | `new_data/entsoe/`                        | **Tier-2 鄰居+DK負載**        | 全 day-ahead         |
| 7   | yfinance(TTF/API2/FX)+ ICAP(EUA)            | `fuel_prices.py`           | `new_data/fuel/`                          | **Tier-3 燃料與碳**           | 用 ≤D-2 收盤         |
| 8   | Energinet `ElectricityBalanceNonv`          | `production_by_fuel.py`    | `new_data/production/`                    | 分燃料逐時出力(熱側驗證)      | 實測,僅供驗證        |
| 9   | varmelast.dk `/api/v1/heatdata`             | `varmelast_heat.py`        | `new_data/heat/`                          | **DK2 實際逐時熱需求**        | 實測,僅供校準        |
| 10  | 丹麥能源署 Technology Catalogue             | (手動下載)                 | `new_data/DEA_data/`                      | **機組技術參數**              | 非時序               |
| 11  | Energinet `DayAheadPrices`(15 分)           | `elspot_price.py`          | `new_data/price/price15_*`                | **電價 2025-10 之後**         | —                    |
| 12  | 丹麥能源署 **SØB25** + 稅費費率             | `build_external_params.py` | `new_data/soeb25_&_extra_params/`         | **燃料價/排放/稅費/物價指數** | 非時序               |
| 13  | varmelast `/api/v1/heatdata/dictionary`     | (快照)                     | `new_data/heat/varmelast_dictionary.json` | **官方欄位定義存證**          | 非時序               |
| —   | 合併                                        | `load_duckdb.py`           | `new_data/energy.duckdb`                  | → `training` view             | —                    |

⚠️ `new_data/` 全部 gitignored,不進 repo。**所有指令從專案根目錄跑**(路徑是相對的)。

---

## 2. 各源欄位:留 / 丟

### 1. Elspotprices(目標 y)

| 欄位                  | 留/丟       | 說明                 |
| --------------------- | ----------- | -------------------- |
| `SpotPriceEUR`        | ✅ **目標** | 訓練的 y             |
| `PriceArea`,`HourUTC` | ✅ key      | join 鍵              |
| `SpotPriceDKK`        | ❌          | 跟 EUR 只差匯率,共線 |
| `HourDK`              | ❌          | 與 HourUTC 重複      |

覆蓋 2018-12-31 → **2025-09-30 21:00 UTC**(hourly 停在 15 分鐘制度切換)。

✅ **2026-08-11 接上 `DayAheadPrices`(15 分鐘)** → `new_data/price/price15_*.parquet`,
**2025-09-30 22:00 UTC → 2026-07-31**,DK1/DK2 各 **29,184 筆、100% 非空、相鄰間隔全部
剛好 15 分鐘(零缺口)**。與逐時檔**完美對接:間隙 0 分鐘,無重疊無缺口**(逐時最後一筆
涵蓋到 22:00 UTC,15 分鐘從 22:00 UTC 開始)。
→ 併起來後**電價 2019–2026 每年都完整**(2026 到 7 月共 5,086 小時)。
⚠️ 價格是**強度量不是流量**:聚合成逐時要用 **`resample('1h').mean()` 不是 sum**。
⚠️ 15 分鐘檔**單獨存**,不與逐時檔合併 —— 解析度不同,合併是分析時的決定。

### 2. Open-Meteo 天氣(DK1 56/9、DK2 55.7/12.3)

| 欄位                                                     | 留/丟       | 說明                           |
| -------------------------------------------------------- | ----------- | ------------------------------ |
| `temperature_2m`                                         | ✅ **重點** | 唯一的需求驅動;熱側的核心輸入  |
| `wind_speed_100m`,`wind_gusts_10m`,`wind_direction_100m` | 🟡 次要     | 風出力主力用 #3;這留當殘差校正 |
| `shortwave/direct/diffuse_radiation`,`cloud_cover`       | 🟡 次要     | 同上                           |

⚠️ **一定要用 `historical-forecast-api`(存的是模型預報)**,不能用 `archive-api`(ERA5 事後實測 = leak)。
⚠️ `_previous_dayN` 後綴實測全 null,沒作用。

### 3. Forecasts_Hour(DK 風光出力,主力)

| 欄位                                                         | 留/丟              | 說明                            |
| ------------------------------------------------------------ | ------------------ | ------------------------------- |
| `ForecastDayAhead`                                           | ✅ **唯一免 leak** | pivot 成 offshore/onshore/solar |
| `ForecastIntraday`,`Forecast5Hour`,`Forecast1Hour`,`Current` | ❌                 | 對「隔日」預測全都 leak         |

覆蓋 **2019-10-31 起**(決定整個管道的左邊界)。

### 4. ProductionConsumptionSettlement(只當 lag)

`load_mwh`、`residual_mwh`(= load − wind − solar)、`wind_mwh`、`solar_mwh`。
⚠️ 全是**事後實測**:當 target/lag 不 leak,當同時刻特徵**必 leak**。
⚠️ 這支存的是**衍生欄**(residual 是算出來的),不是純 raw。

### 5. Calendar(Tier-1,零 leak,同時是 spine)

`hour/dow/month/doy/is_weekend/is_holiday/holiday_name`、cyclical `*_sin/*_cos`、
`daylight_hours/sunrise_hour/sunset_hour/is_daylight`。決定性 → 可無限往未來算 → 當每小時 spine。

---

## 3. Tier-2(ENTSO-E)完整欄位表

共通:索引 `timestamp_utc`(UTC tz-aware),值 float64,單位 MW。檔名帶 `_2019-10-01_2025-10-01` 後綴。

### A. 隔日負載預測 `query_load_forecast`(A01)

| 檔                                       | 頻率      | 涵蓋              | 非空/總       |
| ---------------------------------------- | --------- | ----------------- | ------------- |
| `loadfc_dk_1` / `dk_2` / `se_3` / `se_4` | 1h        | 2019-10 → 2025-09 | 52608/52608   |
| `loadfc_de_lu`                           | **15min** | 同上              | 210232/210232 |

### B. 隔日風光預測 `query_wind_and_solar_forecast`(A69)

| 檔            | 欄位                       | 頻率      | 非空/總           | 備註                 |
| ------------- | -------------------------- | --------- | ----------------- | -------------------- |
| `resfc_de_lu` | Solar / Wind Off / Wind On | **15min** | ~210k             | 德國有離岸風         |
| `resfc_se_3`  | Wind Onshore / Solar       | 1h        | 52536 / **33505** | 瑞典太陽 2021 才發布 |
| `resfc_se_4`  | 同上                       | 1h        | 同上              | 瑞典**無離岸風**     |

### C. 隔日 NTC `query_net_transfer_capacity_dayahead`

| 方向                 | 涵蓋                  | 非空   |
| -------------------- | --------------------- | ------ |
| 德↔DK1、荷↔DK1(雙向) | 2019-10 → 2025-09     | 52608+ |
| 德↔DK2(雙向)         | 2019-10 → **2024-02** | 38711  |

### D. Offered Capacity `query_offered_capacity(from,to,'A01')`

北歐走 flow-based,NTC 端點不發布 → 改用這個。全雙向,只到 **2024-10-29**。
`oc_no_2_dk_1`、`oc_se_3_dk_1`、`oc_se_4_dk_2`、`oc_dk_2_dk_1`(各含反向),非空 44089。

### E. 衍生(`new_data/entsoe/derived/`,原始與衍生**分開放**)

`residual_{de_lu,se_3,se_4}` = 負載預測 − Σ風光預測(15min 先 resample 成 hourly 再相減)。

### F. 原始欄位 → 模型特徵名(`build_entsoe` 的分區掛載)

| 模型特徵                                              | DK1 來源             | DK2 來源    | 掛法           |
| ----------------------------------------------------- | -------------------- | ----------- | -------------- |
| `loadfc_mwh`                                          | loadfc_dk_1          | loadfc_dk_2 | 自己的         |
| `nbr_wind_on_mwh` `nbr_solar_mwh` `nbr_residual_mwh`  | SE_3                 | SE_4        | 自己的 SE 鄰居 |
| `ntc_imp_de` / `ntc_exp_de`                           | de_lu↔dk_1           | de_lu↔dk_2  | 自己↔德        |
| `ntc_imp_nl` / `ntc_exp_nl`                           | nl↔dk_1              | —(NULL)     | 僅 DK1         |
| `oc_imp_se` / `oc_exp_se`                             | se_3↔dk_1            | se_4↔dk_2   | 自己↔瑞        |
| `oc_imp_dk` / `oc_exp_dk`                             | dk_2↔dk_1            | dk_1↔dk_2   | DK1↔DK2 內部   |
| `oc_imp_no` / `oc_exp_no`                             | no_2↔dk_1            | —(NULL)     | 僅 DK1         |
| `de_solar_mwh` `de_wind_off/on_mwh` `de_residual_mwh` | resfc/residual_de_lu | **共用**    | broadcast 兩區 |
| 燃料欄                                                | fuel(shift −2 天)    | **共用**    | join on time   |

**共用 vs 分區**:德國風光/殘差 + 燃料 = 共用外部驅動;其餘按 area 掛。

---

## 4. Tier-3 燃料(2026-08-07 重整)

### 儲存原則:raw

`new_data/fuel/` **一個商品一個 parquet,沒有子資料夾**,存來源回傳的原始單位、原始幣別,
不挑欄位不換算。換算(USD→EUR、公噸→MWh)在 `load_duckdb.build_fuel()` 做
→ 換算規則改了不用重抓。

| 來源                              | 檔名              | **原始單位** | 涵蓋                          |
| --------------------------------- | ----------------- | ------------ | ----------------------------- |
| yfinance `TTF=F`                  | `ttf_gas_eur_mwh` | EUR/MWh      | 1,698 天,2019-01 → 2025-09    |
| yfinance `MTF=F`                  | `api2_coal_usd_t` | **USD/公噸** | 1,695 天,同上                 |
| **ICAP** Allowance Price Explorer | `eua_co2_eur_t`   | EUR/tCO2     | **1,483 天,2019-09 起(100%)** |
| yfinance `EURUSD=X`               | `eurusd_rate`     | USD per EUR  | 1,757 天                      |

碳價的原始 CSV 放在 `new_data/carbon_price_ICAP/`(使用者從 ICAP 網站下載),
`fuel_prices.load_carbon()` 讀它、轉成上表那個 parquet。

### 為什麼煤是美元、碳是歐元

- **煤**:API2 CIF ARA 是全球海運商品,國際慣例用 USD/公噸。沒有「丹麥煤價」,ARA 就是北歐參考價。
- **碳**:EU ETS 全歐單一價,無地區版本。
- **只有生質是區域性定價** → 需丹麥能源署資料,**目前仍缺**。

### 煤的換算(在合併層做)

```
EUR/MWh_fuel = (USD/公噸) ÷ (當日 USD per EUR) ÷ 6.978 MWh/公噸
```

熱值來自 API2 合約規格 6000 kcal/kg NAR:
`6000 kcal/kg × 1000 × 4184 J ÷ 3600 MJ/MWh ≈ 6.97 MWh/公噸`。
匯率逐日對齊,假日用**前一個有報價的日子**往前填(不會用未來值)。
⚠️ 真實電廠通常做匯率避險,即期換算是**邊際成本建模的標準做法**,不等於某業者實付價格。

### 碳價:2026-08-07 從 Yahoo 換成 ICAP(涵蓋 52% → 100%)

舊來源 Yahoo `CO2.L` 是一檔 ETC,只回到 2021-10-18(上市日)→ 涵蓋 52%。
現行來源 **ICAP Allowance Price Explorer** 的 `Primary Market` 欄(拍賣結算價),
2019-09 起近日頻。同一份匯出裡的 `Secondary Market` 只有 322 天,太稀疏,不要用。

**整段取代,不在 2021-10 接縫** —— 那正好是碳價起飛的位置,接兩個不同序列會在最敏感的
地方留一個水準跳動。重疊期 corr **0.986**、中位差 €1.41(拍賣 vs 期貨基差)。

⚠️ ICAP 匯出的**第一行是標題列,欄名在第二行**(`load_carbon()` 認不到 date 欄就 `skiprows=1`)。
⚠️ 候選價格欄要取**非空值最多**的,否則會選到恆為 1 的 `Exchange rate EUR/EUR` 欄。
⚠️ 碳價的交易日曆與 TTF 不同 → `build_fuel()` **先對齊 gas 格線 ffill 再 merge_asof**
(merge_asof 只挑最近一列,不會補洞)。

其他候選來源:Sandbag carbon price viewer(回溯到 2008)、EEA datahub(官方)、investing.com。

### TTF 歷史(驗證正確)

| 年    | 2019 | 2020 | 2021 | **2022**          | 2023 | 2024 |
| ----- | ---- | ---- | ---- | ----------------- | ---- | ---- |
| €/MWh | 14.6 | 9.6  | 47.7 | **133.3(峰 339)** | 41.3 | 34.6 |

---

## 4b. SØB25 與稅費參數(`new_data/soeb25_&_extra_params/`,2026-08-11)

使用者用 `build_external_params.py` 直接讀 xlsx 產生,**沒有任何手打數字,也沒有做貨幣換算
或平減**(那些是建模決定,屬於下游)。換下一版 SØB 只要改頂端的 XLSX 路徑重跑再 diff。

**拆成三個檔而不是一個**,因為三者「來源」性質不同,硬合併會產生大量空欄位。

| 檔                             | 列數             | 內容                                                                                    |
| ------------------------------ | ---------------- | --------------------------------------------------------------------------------------- |
| `soeb25_params.csv`            | 280(20 個 param) | 全部同一出處 → 來源寫在腳本頂端常數,列裡放 `source_table`+`source_cell` 可逐格覆核      |
| `dk_tax_and_tariff_params.csv` | 4                | **每列出處都不同** → 來源欄逐列保留                                                     |
| `gaps.csv`                     | 6                | **缺的東西沒有值** → 欄位是 `what_is_missing`/`where_to_look`/**`do_not_use`**/`blocks` |

出處:Energistyrelsen, _Samfundsøkonomiske beregningsforudsætninger 2025_ (soeB25),
webudgave marts 2026。https://ens.dk/analyser-og-statistik/samfundsoekonomiske-analysemetoder

**🔑 用得到的關鍵值**

| 參數                                | 值                                                                                                      | 出處                                                |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `el_transport_margin_over_70000MWh` | **189**(2025)/ **167**(2026)DKK2025/MWh_e                                                               | Tabel 10 H4/H5                                      |
| `heating_value_affald`              | **11.70 GJ/ton**                                                                                        | Tabel 1 B18                                         |
| `ef_co2_ledningsgas`                | **57.1 kg CO2/GJ**,適用 **2025–2031**(2032 起 soeB 改 0,邊際沼氣邏輯)                                   | Tabel 12                                            |
| `price_index_2025base`              | 2019 **0.8526** / 2020 0.8559 / 2021 0.8687 / 2022 **0.9349** / 2023 0.9730 / 2024 0.9818 / 2025 1.0000 | Tabel 1                                             |
| `elafgift_dh_producer_net`          | **0.4 øre/kWh**(2021 年起)                                                                              | ELAL §11 stk.1 與 §11c;法源 2020-12-29 第 2225 號法 |
| `gate_fee_arc_rest_erhverv`         | **635 DKK/ton**(未稅)                                                                                   | ARC 費率表 2025-11-01                               |

⚠️ `price_index_2025base` 是把不同年份版本的 soeB 放到同一價格基準的必要工具。

**🔴 為什麼 2019–2024 生質價補不了**:soeB25 的 Tabel 2 與 Tabel 5 **都從 2025 起算**
—— 它是**預測文件不是歷史統計**。更進一步:Tabel 5 Note 3 明載「計算進口價所用的 forward
價是 2025 年 1 月抓的」→ **連 2025 那格也是「2025 年初的遠期觀點」,不是實際結算價**。
`gaps.csv` 的 `biomass_price_2019_2024` 列了兩條可行路徑,以及一條明確的 `do_not_use`:
**不可拿 2025 那格當更早年份的代理**。

**六項缺口**(`gaps.csv`):`biomass_price_2019_2024`、`co2_afgift_affald`、
`gate_fee_vestforbraending`、`gate_fee_argo`、`elafgift_2019_2020`、`dk2_unit_capacities`。
⚠️ **`do_not_use` 欄務必讀** —— 這六項最可能的出錯方式是拿錯的東西替代
(例:拿 ARC 的費率當 Vestforbrænding 用、拿現在的 elafgift 套 2019 年)。

**兩個容易撿錯的陷阱**:

1. **elafgift**:法規明文說熱生產者**不能**用家戶的 elvarme 減免稅率。
   網路上「1 øre/kWh、4,000 kWh 門檻」那組數字全是家戶的,**不適用**。
2. **ARC 處理費**:該費率**已內含 ARC 自身應繳的垃圾稅費**。
   若同時把它當負燃料成本、又另外加一個 CO2 稅項,會**重複計入**。

---

## 5. 熱側專用資料(2026-08 新增)

### 8. `ElectricityBalanceNonv` — 分燃料逐時出力

`Biomass / Waste / FossilGas / FossilHardCoal / FossilOil / TotalLoad / 各聯絡線`。
DK1/DK2 各 81,080 列,2019-01 → 2026-01。

⚠️ **2025-10 後轉 15 分鐘制**。直接對 MW 欄位加總會把那段算 4 倍權重 →
**一定要先 `resample('1h').mean()`**(`heat/fuelmix.py` 已處理)。

DK1 2025 熱電發電量組成:生質 32.8% / 煤 27.8% / 氣 23.7% / 廢棄物 13.2% / 油 2.5%。
出力加權隱含排放因子 ≈ 0.149 tCO2/MWh_fuel。

### 9. varmelast.dk — DK2 實際逐時熱需求

端點 `https://www.varmelast.dk/api/v1/heatdata/historical?from=&to=`(公開,免 key)。
單位 MJ/s = MW_th,**2021-01 起**(2019/2020 無)。**48,887 列**。

🔴 **同一個端點同時回傳消費與生產兩類欄位,混用 = 循環論證**(2026-08-09 查證):

| 欄位                                                                                                                                              | 官方 title           | 類別             | 能不能當 LP 輸入                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ---------------- | ----------------------------------- |
| `BE-EO-CTR-EFF`                                                                                                                                   | CTR                  | **消費**         | ✅ 可以(均 709 MW_th)               |
| `DAP-VEKS-FORBRUG-EFF`                                                                                                                            | VEKS                 | **消費**         | ✅ 可以(均 287;key 裡 FORBRUG=消費) |
| `TOTAL`                                                                                                                                           | **Produktion i alt** | 生產             | ❌ 含蓄熱與調度結果                 |
| `BE-VL-KRAFTV-EF` 64.6% / `AFFALD` 27.7% / `SPIDS-GAS` 4.0% / `IO` 1.0% / `EVO`(電鍋爐)0.8% / `VP`(熱泵)0.6% / `BIO`·`SPIDS-OLIE`·`BG`·`OD`·`SOL` | 分來源               | 生產             | ❌ 僅供驗證排程行為                 |
| `BE-VL-TOTAL-FAK`                                                                                                                                 | **CO2 - Udledning**  | **排放,`Kg/GJ`** | ❌ **不是熱量欄**                   |
| `LOCAL`                                                                                                                                           | Lokal produktion     | 生產             | 全期恆為 0,無資料                   |

⚠️ 佔比是 2023–2025 完整年、排除 `BE-VL-TOTAL-FAK` 後重算。**舊記錄 64.4/27.3/4.5 是把
`BE-VL-TOTAL-FAK`(Kg/GJ)誤加進 MW_th 分母的結果**,已修正。

⚠️ **CTR+VEKS 是「傳輸層取用量」,不是終端消費總量** —— 官網說明有一部分熱由本地直接送進
配網、不經傳輸網。對本模型這正好是對的邊界(LP 調度的是接在傳輸網上的機組),但要標明口徑。

**生產 − 消費 = 蓄熱槽 + 損失**:dictionary 明寫 `Produktion i alt *eksklusive op- og
afladning på varmelagre`(總生產**不含**蓄熱充放)。實測 2023–25:gap 均 +21 MW、std 99、
**41% 小時為負**、日內有充放循環;月均約佔消費 **1.0–3.7%**(≈2%)= 傳輸網損失。
三座蓄熱槽(Amager 1,000 MWh/±300 MJ/s、Avedøre 2,200 MWh/±330 MJ/s、
Høje Taastrup 池儲 3,300 MWh/±30 MJ/s、年僅 25–30 循環)**沒有數值序列**。

**是事後實測不是事前計畫**:dictionary 寫延遲 90 分鐘、每 5 分鐘更新;CO2 說明寫熱電/焚化
排放是 `målte værdier`。官方定義(首頁):`Varmeplanen skal opfylde fjernvarmeselskabernes
daglige prognose for varmebehov` → **varmebehov = 熱網公司的需求預測;varmeplan = 調度**。

**其他端點**:`/api/v1/heatdata`(廠級即時值 + 業主與容量,例:Amagerværket 屬 HOFOR、810 MJ/s)、
`/api/v1/heatdata/dictionary`(**唯一的官方欄位定義**,快照存於 `new_data/heat/varmelast_dictionary.json`)、
`/api/v1/heatdata/revisionplan`(檢修計畫)。
**純需求預測在另一個 host**:`app-lasso-api-prod-001.azurewebsites.net/api/prognosis/overall`
(「14-døgns varmeprognose」,`totalDemand`+`forecastWaste`)—— 但只往未來 14 天、只有日均、
**無歷史** → 歷史逐時需求只能用 CTR+VEKS。

✅ **2026-08-11 已補齊**:當初 5 個季度(2021 Q1/Q3、2022 Q1/Q3/Q4)是**連線中斷抓取失敗,
不是沒有資料** —— `varmelast_heat.fill_gaps()` 補抓回 **10,944 列**,37,969 → **48,887 列**。
年涵蓋現在 **2021–2026 全部完整**(2021=8,759 / 2022=8,759 / 2023=8,759 / 2024=8,783 /
2025=8,759 / 2026-01~07=5,067)。**2022 能源危機年因此可用**。
⚠️ `fill_gaps()` 只新增舊檔沒有的時間戳,寫入前驗證舊資料逐格不變,先寫 .tmp 再 rename。
⚠️ 官方公告 2026-07-10~29 的歷史資料有誤(`heat/calibrate.py` 讀取時已排除)。
⚠️ 這是 **DK2**,不是 DK1 → 當校準/驗證用。**DK1 沒有任何逐時熱需求資料**。

🔑 **生產分項欄的正確用法(2026-08-12,`heat/validate.py`)**:它們**不能當 LP 輸入**,
但可以驗 LP 的**排程時點**,而且比驗水準有識別力得多。三件事要注意:

1. **一律先加日固定效果。** 原始資料上熱電「高價時出力更高」(高價四分位 +42 MW),
   加日 FE 後係數翻成 −0.125 —— 那是冬天同時有高需求與高價的**季節性假象**。
2. **再移除「月×時」平均日內形狀。** 電價與各熱源各有穩定日內形狀,直接相關等於在比
   兩條固定曲線對不對齊。移除後垃圾焚化從 −0.190 衰減到 −0.100(大半是形狀假象),
   電鍋爐 −0.409 → −0.261(是真的反應)。
3. **日總量與日內配置要分開問。** 實測電鍋爐的日總量主要由**熱需求**決定(ρ=+0.42),
   電價只決定**在哪幾小時開**(ρ=−0.25)。混在一起看會得到錯的結論。

🔑 **P2H 裝置容量:銘牌查不到,但出力上界給了下界**(這兩欄只有出力沒有銘牌):
**`BE-VL-EVO-EF`(電鍋爐)最大 98.0 MW_th、`BE-VL-VP-EF`(熱泵)最大 25.9 MW_th**
(2021–2026 全期)。出力達到過的值,容量至少有那麼大 —— **這不是猜,是下界**。
⚠️ 熱泵有**容量擴建**:2021–2022 最大恆為 6.0 MW 且開機率 100%(單一機組跑滿),
2024 起上界升到 24–26 MW → 跨年比較熱泵時要注意這個結構斷點。

### 10. 丹麥能源署 Technology Catalogue

`new_data/DEA_data/` 兩個 CSV(長格式 tidy):

- `DEA_electricity_and_district_heating.csv` — 15,581 列 / 74 個技術工作表
- `DEA_energy_storage.csv` — 3,181 列 / 17 個工作表(含 TTES、PTES 季節性儲熱)

欄位:`ws`(技術)、`par`(參數)、`est`(**ctrl/lower/upper** → 敏感度免費)、`year`、`val`、`unit`、`note_text`。

**⚠️ 兩個讀取陷阱(已在 `heat/dea.py` 處理):**

1. **年份格點隨技術與 est 而異** — ctrl 常有 2015/2020/2030/2050,lower/upper 常只有 2020/2050,
   有些技術 ctrl 從 2025 才開始 → 要取最接近的年份,不能硬性相等。
2. **`Cv = 1.0` 是哨兵值不是真值** — 註解寫明
   _"The Cv value does not exist for plants with a back pressure turbine"_。
   那些是**背壓式**機組(`P = Cb·Q` 一條線,熱電綁死);抽汽式才有可行域面積。
   目錄裡兩種都有(`09a Wood Chips, Large` 背壓 / `09a Wood Chips extract. plant` 抽汽)。

**⚠️ 目錄裡沒有 CO2 排放因子**(那是燃料屬性不是技術屬性)。

---

## 6. 合併規則與可訓練窗(`load_duckdb.py`)

- 5 源標準化成 `(timestamp_utc, area)`,**calendar 當 spine**,其餘 LEFT JOIN(零 fan-out,缺口留 NULL)。
- lag 在 spine 上用 window function 算:`price_lag24/168`、`load_lag24`、`residual_lag24`(只碰 ≥24h 舊值)。
- 燃料是日資料 → forward-fill 到每小時,且用 **≤ D-2 收盤**(`merge_asof` backward,cutoff = 交易日 −2 天,順便填週末假日)。
- **可訓練 ~103,150 列:2019-11-01 → 2025-09-30**。
- 取法:`SELECT * FROM training WHERE y_price_eur IS NOT NULL AND solar_da_mwh IS NOT NULL`。

### 日期邊界

| 邊界              | 卡在哪                        | 原因                                                 |
| ----------------- | ----------------------------- | ---------------------------------------------------- |
| 左 **2019-10-31** | Energinet Forecasts_Hour 起點 | 早於此沒有官方隔日出力預測                           |
| 右 **2025-09-30** | Elspotprices(hourly)止        | 歐洲 SDAC 改 15 分鐘 MTU;之後價格搬 `DayAheadPrices` |

### 涵蓋率備忘

殘差 ~100% / offered-cap 83.6%(2024-10 截止) / gas 100% / **co2 52%(2021-10 起)** / 煤 100%。

---

## 7. 資料層的關鍵發現(不是模型結果,是資料本身的性質)

### 為什麼「只看鄰居風光」不夠 —— 要的是**殘差**

```
鄰居殘差 = 隔日負載預測 − 隔日風光預測 = 需要多少可調度電源來補
```

殘差**負**(風光>用電)→ 電滿出來倒向丹麥 → DK 價崩/負電價。
殘差**高**(無風+高需求)→ 動用貴的天然氣 → DK 價高。
**同樣的風光量搭配不同用電,結果完全相反。**

### 火力為什麼沒有隔日預報

| 類型           | 例子           | 出力由誰決定           | 有隔日預報      |
| -------------- | -------------- | ---------------------- | --------------- |
| 靠天(must-run) | 風、光         | 老天                   | ✅ TSO 必須預報 |
| 可調度         | 煤、氣、核、水 | **市場**(價夠高才開機) | ❌ 沒有         |

火力出力是競價的**結果**(內生),去預報它 = 用答案猜答案。
改用兩個外生量捕捉:`殘差(量) × 燃料價(價)`。德國核能已於 2023-04 全部關閉。

### 不是每個鄰居都有效

| 鄰居           | 與 DK 價相關 | 殘差 std | 為什麼                                     |
| -------------- | ------------ | -------- | ------------------------------------------ |
| **德國 DE_LU** | **+0.451**   | 13,460   | 補殘差靠**火力**(貴又會變)→ 殘差一動價就動 |
| 瑞典 SE_4      | +0.232       | 725      | 水力/核 baseload 厚,殘差被壓住             |
| 瑞典 SE_3      | +0.118       | 2,134    | 同上,波動小 = 資訊少                       |

→ 德國殘差是主力;**瑞典管的是「地板」,該用水庫水位(water value)不是殘差**。

德國殘差切 10 等分 → DK1 均價 14.2 → 166.7 €/MWh **單調爬升,價差 12 倍**,
最低那格殘差**仍為正** → 殘差在全域都有用,負殘差(0.8% 時數)只是最戲劇的尾巴。

### NTC 端點的坑

`query_net_transfer_capacity_dayahead` **只對 DK↔德、DK↔荷發布**。
DK↔挪威/瑞典、DK1↔DK2 走**北歐 flow-based 隱式競價**,不在這端點 → 回空。
**解法**:改用 `query_offered_capacity(from,to,'A01')`(只到 2024-10-29)。

DK 完整拓撲:`DK1 ↔ 德/挪NO_2/瑞SE_3/荷NL(COBRA)/英GB(Viking 2023-12)/DK2`;
`DK2 ↔ 德/瑞SE_4/DK1`。GB 2023-12 才通,歷史大半空 → 跳過。
別信 entsoe-py 寫死的 `NEIGHBOURS` 靜態表(鄰居拓撲隨歷史變)。

### 其他踩過的雷

- ENTSO-E 每 request 最多 1 年(腳本已加年切分);start/end 要帶 tz;回傳型別 Series/DataFrame 不一。
- **不抓 DK_1/DK_2 的風光**:那份 ENTSO-E 資料本來就是 Energinet 報上去的,同源共線。
- Energinet API 有 rate limit(429),連續打會被暫時封,要隔幾分鐘。
- LightGBM 裝機:macOS 需 `brew install libomp`。
