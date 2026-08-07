# 丹麥能源市場多 agent 模擬(碩論)

現行主線:**CHP + 區域供熱(fjernvarme)的多 agent 模擬**。
電池線已於 2026-08-04 結案(park),結論與程式碼保留。

---

# 🔴 交接狀態(下一個 session 先讀這段)

**最後更新 2026-08-07。**

## ① 工作在分支 `feat/heat-chp-track`,已推遠端,**PR 尚未開**

`main` 仍停在 `c1ce3aa`。分支上有 4 個 commit(commit message 用英文):

```
18e5123 docs: consolidate 10 markdown files into 5, add handover section
dc77dd3 feat: heat track -- scheduling LP and data for CHP + district heating
50b897f feat: store fuel prices raw, add coal (API2) and EUR/USD rate
1ec6acd refactor: move agents/ to battery/, plus four foundation fixes for lambda
```

內容涵蓋:`agents/` → `battery/` 的搬移、整個新的 `new_src/heat/`(6 模組)、
`production_by_fuel.py` 與 `varmelast_heat.py`、燃料層改存 raw 並加煤價、
文件 10 份併成 5 份。

**開 PR 的連結**:https://github.com/RaphaFang/energy_trading_environment/pull/new/feat/heat-chp-track

## ② 三件「使用者要自己處理、不要幫他猜」的事

| 事項                                   | 為什麼不能猜                                                                                                                     |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **生質燃料價**                         | 無國際期貨。要丹麥能源署 `Samfundsøkonomiske beregningsforudsætninger` 或 Energipriser 統計。目前程式用天然氣價當代理,**已標記** |
| **elafgift(DH 電鍋爐/熱泵的電力稅費)** | 丹麥有專門規則且改過多次,是**一階遺漏**,直接改變 power-to-heat 的成本排序。使用者看得懂丹麥文,由他查證後給數字                   |
| **DK1 年產熱量**                       | `demand.ANNUAL_TWH_DK1 = 19.0` 是佔位值。使用者提過能源署的數字是 21–23 TWh,待確認出處                                           |

## ③ 兩個懸而未決的方向決策(問使用者,別自己定)

1. **研究區域要不要從 DK1 換成 DK2?**
   DK2 有 varmelast 的**實際逐時熱需求**與**廠級所有權資料**;DK1 兩者都沒有(熱需求只能用代理)。
   換過去能同時解掉最大的資料缺口與「agent 體量/集中度」的問題。
2. **「市場力」框架對 DH 是否成立?**
   丹麥區域供熱受成本回收原則(hvile-i-sig-selv)規範 → 非營利實體**沒有動機扣留產能抬價**。
   但電廠業主(Ørsted/Vattenfall)與熱網公司(市政)可能是不同法人。
   **這決定目標函數該是成本最小化還是利潤最大化**,必須在建多 agent 層之前定案。
   ⚠️ 我沒查證過原始法規,`STATUS.md` §7 第 1 點已標明。

## ④ 立即可做的下一步(依解鎖價值排序)

1. **把 `dea.plant_params()` 接成 `chp.Plant` 的來源** — 最大的解鎖。真值已能產出,
   但 `Plant` 的預設**仍是佔位值**。我沒擅自改,因為那會讓所有既有數字變動。
2. **重建 duckdb** 讓煤價進 `training` view(`python new_src/data/load_duckdb.py`)。
   ⚠️ 會 `CREATE OR REPLACE` 覆寫 32MB 倉庫,跑之前確認所有來源檔都在。
3. **用 varmelast `/api/v1/heatdata` 拿廠級所有權+容量** → 把「DK1 熱電 802 MW_e 車隊」
   拆成真實的 agent 體量與家數。這是外部批評裡唯一還沒解的一點。
4. **多 agent 層**(核心假說:相關的熱義務在稀缺時刻侵蝕整個 DH 車隊的彈性)。
   目前**只有一個 agent**,互動層完全不存在。

## ⑤ 絕對不要做的事

- **不要擅自刪 `new_data/` 裡的任何東西。** 使用者花很多心思整理,而且它是 gitignored、
  刪了無法從 repo 還原。`new_data/fuel/` 那兩個舊單欄檔雖被 `raw/` 取代,
  但 `load_duckdb._series()` 仍會 fallback 讀 → **等 duckdb 重建並驗證後再議**。
- **不要把 `chp.Plant` 跑出來的金額當結論引用。** 預設值仍是佔位值,
  且 `p_max=400 MW_e` 相對它服務的熱網過大(機組像純發電廠在跑)。
- **不要在儲存層做清理或單位換算。** 見下方工作慣例。

---

## 工作慣例(這個專案的規矩)

- **所有指令從專案根目錄跑** — 路徑都是相對的。在子目錄跑會找不到 `new_data/`。
- **`new_data/` 是 gitignored** — 手機/雲端 Claude Code 看不到 ≠ 資料不存在。
- **原始資料存 raw**:不挑欄位、不換單位、不換幣別。
  清理與換算(USD→EUR、公噸→MWh、丟 0 值、排除錯誤區間)一律在**分析時**做
  → 規則改了不用重抓。
- **抓取腳本要有 skip-if-exists**,絕不覆蓋已抓好的原始檔。
- **每個模組留一個可跑的 self-check**(`python <模組>` 就跑),不用測試框架。
- **標記不確定性**:佔位值要在程式碼註解裡寫明「這是我設的,未查證」。
  `STATUS.md` §4 是誠實的參數來源清單,四類 (A) 真實資料 / (B) 文獻官方 / (C) 佔位值 / (D) 校準值。

## 已知的坑(踩過的,別再踩)

| 坑                                 | 說明                                                                                                                                           |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Energinet API 429                  | 有 rate limit,連續打會被暫時封,兩區之間要隔幾分鐘                                                                                              |
| `ElectricityBalanceNonv` 15 分鐘制 | 2025-10 後轉 15 分鐘一筆。直接加總 MW 會把那段算 4 倍權重 → **先 `resample('1h').mean()`**                                                     |
| DEA 目錄 `Cv = 1.0`                | 是**背壓式的哨兵值不是真值**(註解寫明 Cv does not exist)。背壓式是 `P=Cb·Q` 一條線、無彈性;抽汽式才有可行域面積。`dea.is_back_pressure()` 會擋 |
| DEA 年份格點                       | 隨技術與 est 而異(ctrl 常有 2015/2020/2030/2050;lower/upper 常只有 2020/2050)→ 要取最接近年份,不能硬性相等                                     |
| 煤價是 USD                         | `MTF=F` 是 **USD/公噸**,不是 EUR。碳價 `CO2.L` 才是 EUR                                                                                        |
| `el_net` 為負是正常的              | 熱在模型裡是**義務不是商品**(無熱收入)→ 燒燃料是為了供熱,電只是副產品。看 `heat_cost_per_mwh` 才有意義                                         |
| 驗證要挑有識別力的標的             | 曾用 CHP 發電量驗證熱需求代理 —— 發電量由熱約束與電價共同決定,電價影響大得多,**驗不動**。改用 varmelast 真值才驗得出來                         |

---

## 先讀哪一份

| 文件                                    | 內容                                                              |
| --------------------------------------- | ----------------------------------------------------------------- |
| **[`STATUS.md`](STATUS.md)** ← **先讀** | 現況盤點:模型實際長什麼樣、每個參數哪來、哪些是佔位值、哪些還沒做 |
| [`DATA.md`](DATA.md)                    | 資料手冊:每個源哪來、留哪些欄、會不會 leak、踩過的坑              |
| [`BATTERY_TRACK.md`](BATTERY_TRACK.md)  | 電池線(已 park)+ 預測管道:設計、結果、結案理由                    |
| [`LITERATURE.md`](LITERATURE.md)        | 文獻庫                                                            |

> 2026-08-07 整理:原本 10 份併成 5 份。
> `DATA_CATALOG` + `TIER2_SCHEMA` + `TIER2_TIER3_FINDINGS` → `DATA.md`;
> `SIMULATOR_OVERVIEW` + `MULTI_AGENT_MARKET` + `MODEL_MATH` → `BATTERY_TRACK.md`;
> `RECAP_2026-07-20` 的觀念釐清併入 `BATTERY_TRACK.md` §5.5,其餘(已被推翻的結論)刪除;
> `sumup_0806.md` → `STATUS.md`(living document)。

## 結構

```
new_src/
├── data/       抓資料 → new_data/*.parquet → energy.duckdb
│               calendar_features(spine) / elspot_price(目標 y) / weather_forecast /
│               energinet_forecast / residual_demand / entsoe_features /
│               fuel_prices(氣/煤/碳/匯率,raw) / production_by_fuel(分燃料出力) /
│               varmelast_heat(DK2 實際熱需求) / load_duckdb(合併,最後跑)
│
├── heat/       ★ 現行主線:CHP + 區域供熱
│               chp.py         排程 LP(CHP 可行域 + 蓄熱槽 + 電鍋爐 + 熱泵 + 尖峰鍋爐)
│               demand.py      熱需求度日代理(參數已用 varmelast 校準)
│               calibrate.py   用 DK2 實際熱需求校準代理(R²=0.895)
│               dea.py         讀 Technology Catalogue → 真實機組參數(含 lower/upper)
│               fuelmix.py     DK1 燃料組成(決定原型機組該燒什麼)
│               flexibility.py 彈性價值拆解(逐一關掉選項看成本上升多少)
│
├── battery/    電池線(已 park,見 BATTERY_TRACK.md)
│               v1_single / v2_multi / v3_cournot / v4_wind / fringe(λ 估計)
│               compare.py / experiment.py
│
└── models/     統計電價預測(獨立資產,兩條線都能用)
                forecast.py(建模唯一一份)/ baseline.py(準度報表)
```

## 怎麼跑

```bash
# 熱側(現行主線)
python new_src/heat/chp.py          # 排程 LP + self-check
python new_src/heat/demand.py       # 熱需求代理 + self-check
python new_src/heat/calibrate.py    # 用 varmelast 真值校準
python new_src/heat/dea.py          # Technology Catalogue 參數
python new_src/heat/fuelmix.py      # DK1 燃料組成
python new_src/heat/flexibility.py 2024   # 彈性價值拆解

# 資料
python new_src/data/fuel_prices.py        # 氣/煤/碳/匯率(raw,skip-if-exists)
python new_src/data/production_by_fuel.py # 分燃料逐時出力
python new_src/data/varmelast_heat.py     # DK2 實際逐時熱需求
python new_src/data/load_duckdb.py        # 合併成 energy.duckdb(最後跑,會覆寫)

# 電池線(已 park)— 見 BATTERY_TRACK.md §7
```
