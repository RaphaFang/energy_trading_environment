# Tier-2 / Tier-3 Schema — 每個檔的完整欄位(para）

> 直接讀真實檔案掃出來的欄位表:**每個檔的 API 方法、原始欄位名、單位、頻率、涵蓋、非空**,
> 以及原始欄位 → 模型特徵名的對應。搭配 `TIER2_TIER3_FINDINGS.md`(發現)、`load_duckdb.py`(合併)。

**共通約定**

- 索引:`timestamp_utc`,型別 `TIMESTAMP WITH TIME ZONE`(UTC,tz-aware)。
- 值型別:全部 `float64`,單位 **MW**(容量/發電/負載)或 €(燃料)。
- 檔名帶日期後綴 `_2019-10-01_2025-10-01`,下表省略。

---

## A. 隔日負載預測 — `query_load_forecast`(process_type A01)

| 原始檔         | 原始欄位                | 頻率      | 涵蓋              | 非空/總       |
| -------------- | ----------------------- | --------- | ----------------- | ------------- |
| `loadfc_dk_1`  | `dk_1_Forecasted Load`  | 1h        | 2019-10 → 2025-09 | 52608/52608   |
| `loadfc_dk_2`  | `dk_2_Forecasted Load`  | 1h        | 2019-10 → 2025-09 | 52608/52608   |
| `loadfc_de_lu` | `de_lu_Forecasted Load` | **15min** | 2019-10 → 2025-09 | 210232/210232 |
| `loadfc_se_3`  | `se_3_Forecasted Load`  | 1h        | 2019-10 → 2025-09 | 52608/52608   |
| `loadfc_se_4`  | `se_4_Forecasted Load`  | 1h        | 2019-10 → 2025-09 | 52608/52608   |

⚠️ **DE_LU 是 15 分鐘制**(210k 列),其餘 hourly。

---

## B. 隔日風光發電預測 — `query_wind_and_solar_forecast`(A69;PSR B16 太陽/B18 離岸風/B19 陸風)

| 原始檔        | 原始欄位              | 頻率      | 非空/總         | 備註                 |
| ------------- | --------------------- | --------- | --------------- | -------------------- |
| `resfc_de_lu` | `de_lu_Solar`         | **15min** | 210424/210432   |                      |
| `resfc_de_lu` | `de_lu_Wind Offshore` | 15min     | 210432/210432   | 德國有離岸風         |
| `resfc_de_lu` | `de_lu_Wind Onshore`  | 15min     | 210424/210432   |                      |
| `resfc_se_3`  | `se_3_Wind Onshore`   | 1h        | 52536/52536     |                      |
| `resfc_se_3`  | `se_3_Solar`          | 1h        | **33505**/52536 | 瑞典太陽 2021 才發布 |
| `resfc_se_4`  | `se_4_Wind Onshore`   | 1h        | 52536/52536     |                      |
| `resfc_se_4`  | `se_4_Solar`          | 1h        | **33505**/52536 | 同上                 |

⚠️ 瑞典**無離岸風**欄位;太陽能非空只 33505(前期未發布 → 合併時當 0/NaN)。

---

## C. 隔日跨境容量 NTC — `query_net_transfer_capacity_dayahead`(僅 DK↔德/荷發布)

方向:`ntc_{from}_{to}` = 從 from 送到 to 的容量。

| 原始檔           | 原始欄位           | 方向         | 涵蓋                  | 非空/總 |
| ---------------- | ------------------ | ------------ | --------------------- | ------- |
| `ntc_de_lu_dk_1` | `ntc_de_lu_dk_1_0` | 德→DK1(進口) | 2019-10 → 2025-09     | 52614   |
| `ntc_dk_1_de_lu` | `ntc_dk_1_de_lu_0` | DK1→德(出口) | 2019-10 → 2025-09     | 52614   |
| `ntc_nl_dk_1`    | `ntc_nl_dk_1_0`    | 荷→DK1       | 2019-10 → 2025-09     | 52608   |
| `ntc_dk_1_nl`    | `ntc_dk_1_nl_0`    | DK1→荷       | 2019-10 → 2025-09     | 52608   |
| `ntc_de_lu_dk_2` | `ntc_de_lu_dk_2_0` | 德→DK2       | 2019-10 → **2024-02** | 38711   |
| `ntc_dk_2_de_lu` | `ntc_dk_2_de_lu_0` | DK2→德       | 2019-10 → **2024-02** | 38711   |

⚠️ DK2↔德 只到 **2024-02**(之後改制)。欄位名 `_0` = 原本無名單欄。

---

## D. 隔日 Offered Capacity — `query_offered_capacity(from, to, 'A01')`(補北歐/內部)

北歐 flow-based 邊界 NTC 端點不發布 → 改用這個。全部**雙向**,只到 **2024-10-29**。

| 原始檔                          | 原始欄位 | 方向            | 涵蓋      | 非空  |
| ------------------------------- | -------- | --------------- | --------- | ----- |
| `oc_no_2_dk_1` / `oc_dk_1_no_2` | `..._0`  | 挪NO2 ↔ DK1     | → 2024-10 | 44089 |
| `oc_se_3_dk_1` / `oc_dk_1_se_3` | `..._0`  | 瑞SE3 ↔ DK1     | → 2024-10 | 44089 |
| `oc_se_4_dk_2` / `oc_dk_2_se_4` | `..._0`  | 瑞SE4 ↔ DK2     | → 2024-10 | 44089 |
| `oc_dk_2_dk_1` / `oc_dk_1_dk_2` | `..._0`  | DK2 ↔ DK1(內部) | → 2024-10 | 44089 |

---

## E. 衍生:鄰居殘差(`new_data/entsoe/derived/`,自己算)

`residual = 負載預測 − Σ(風光預測)`,15 分鐘先 resample 成 hourly 再相減。

| 原始檔           | 欄位                 | 頻率 | 非空/總     | 備註                          |
| ---------------- | -------------------- | ---- | ----------- | ----------------------------- |
| `residual_de_lu` | `de_lu_residual_mwh` | 1h   | 52558/52558 | 略少(15min→hourly + NaN 對齊) |
| `residual_se_3`  | `se_3_residual_mwh`  | 1h   | 52608/52608 |                               |
| `residual_se_4`  | `se_4_residual_mwh`  | 1h   | 52608/52608 |                               |

---

## F. Tier-3 燃料(`new_data/fuel/`)

| 原始檔            | 欄位              | 單位  | 頻率       | 涵蓋                            |
| ----------------- | ----------------- | ----- | ---------- | ------------------------------- |
| `ttf_gas_eur_mwh` | `ttf_gas_eur_mwh` | €/MWh | 日(交易日) | 2019-01 → 2025-09(1698天)       |
| `eua_co2_eur_t`   | `eua_co2_eur_t`   | €/噸  | 日(交易日) | **2021-10** → 2025-09(997天)    |
| `manual/`(空)     | —                 | —     | —          | 待補碳價 2019→2021-10(Barchart) |

---

## G. 原始欄位 → 模型特徵名(`build_entsoe` / `build_fuel` 產出)

合併時做的分區掛載與改名。**DK1 列**與 **DK2 列**各自拿到:

| 模型特徵                                          | 來源(DK1)                       | 來源(DK2)                       | 掛載           |
| ------------------------------------------------- | ------------------------------- | ------------------------------- | -------------- |
| `loadfc_mwh`                                      | loadfc_dk_1                     | loadfc_dk_2                     | 自己的         |
| `nbr_wind_on_mwh`                                 | resfc_se_3 Wind Onshore         | resfc_se_4 Wind Onshore         | 自己 SE 鄰居   |
| `nbr_solar_mwh`                                   | resfc_se_3 Solar                | resfc_se_4 Solar                | 自己 SE 鄰居   |
| `nbr_residual_mwh`                                | residual_se_3                   | residual_se_4                   | 自己 SE 鄰居   |
| `ntc_imp_de` / `ntc_exp_de`                       | ntc_de_lu_dk_1 / ntc_dk_1_de_lu | ntc_de_lu_dk_2 / ntc_dk_2_de_lu | 自己↔德        |
| `ntc_imp_nl` / `ntc_exp_nl`                       | ntc_nl_dk_1 / ntc_dk_1_nl       | —(NULL)                         | 僅 DK1         |
| `oc_imp_se` / `oc_exp_se`                         | oc_se_3_dk_1 / oc_dk_1_se_3     | oc_se_4_dk_2 / oc_dk_2_se_4     | 自己↔瑞        |
| `oc_imp_dk` / `oc_exp_dk`                         | oc_dk_2_dk_1 / oc_dk_1_dk_2     | oc_dk_1_dk_2 / oc_dk_2_dk_1     | DK1↔DK2 內部   |
| `oc_imp_no` / `oc_exp_no`                         | oc_no_2_dk_1 / oc_dk_1_no_2     | —(NULL)                         | 僅 DK1         |
| `de_solar_mwh` `de_wind_off_mwh` `de_wind_on_mwh` | resfc_de_lu(15min→hourly)       | 同左(**共用**)                  | broadcast 兩區 |
| `de_residual_mwh`                                 | residual_de_lu                  | 同左(**共用**)                  | broadcast 兩區 |
| `ttf_gas_eur_mwh` `eua_co2_eur_t`                 | fuel(shift −2 天 leak-safe)     | 同左(**共用**)                  | join on time   |

**共用 vs 分區**:德國風光/殘差 + 燃料 = 共用外部驅動(broadcast 兩區);其餘按 area 掛。
**Leak**:A–E 全 day-ahead 預報/容量(leak-free);F 燃料用 ≤ D-2 收盤(leak-safe)。
