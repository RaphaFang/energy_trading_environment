# 丹麥能源市場多 agent 模擬(碩論)

現行主線:**CHP + 區域供熱(fjernvarme)的多 agent 模擬**。
電池線已於 2026-08-04 結案(park),結論與程式碼保留。

---

# 🔴 交接狀態(下一個 session 先讀這段)

**最後更新 2026-08-09。**

## ⓪ 研究範圍已縮到 **只做 DK2**(2026-08-08 使用者決定)

DK2(大哥本哈根)有 `varmelast.dk` 的**實際逐時熱需求真值**與**廠級所有權**;DK1 兩者都沒有。
DK1 的程式碼與佔位值**先留著不刪**(哪天回頭做再撿)。細節與退休清單見 `STATUS.md` §0。

**直接不必解的**:`ANNUAL_TWH_DK1=19.0`、`SYSTEM_SHARE=0.08`、「DK2 形狀能否移轉 DK1」。
**新換來的問題**:DK2 是單一大型都會系統,「多業者相關熱需求」的核心假說要改用
CTR / VEKS / 廠級業主(HOFOR、Vestforbrænding、ARC…)來切 agent,**切分方式未定案**。

## ① 工作在分支 `feat/heat-chp-track`,**PR 尚未開**

`main` 仍停在 `c1ce3aa`。分支上 5 個 commit(訊息用英文),最新一個:

```
28be300 feat: real EUA carbon (ICAP, 100% coverage) + DEA catalogue params in chp.Plant
370af88 docs: update handover section -- work is now committed and pushed
18e5123 docs: consolidate 10 markdown files into 5, add handover section
dc77dd3 feat: heat track -- scheduling LP and data for CHP + district heating
50b897f feat: store fuel prices raw, add coal (API2) and EUR/USD rate
```

⚠️ **`28be300` 尚未推遠端。**
開 PR:https://github.com/RaphaFang/energy_trading_environment/pull/new/feat/heat-chp-track

## ② 🔴 已知未修的 bug(下一個 session 第一件事)

**`chp.Plant.eta_el` 用錯基準。** 2026-08-08 對 CSV 驗證:目錄的 **`Cb` 是用 name plate
效率算的**(η_el/η_th 比值 5 張表 5 中,annual average 全部對不上)。但 `Plant` 取的是
annual average → **同一組可行域裡混了兩種基準**。

| 原型 | 現在(annual,錯) | 應為(name plate) |
| ---- | ---------------- | ----------------- |
| `wood_chips` | 0.409 | **0.43** |
| `wood_pellets` | 0.425 | **0.447** |
| `gas_cc` | 0.56 | **0.59** |
| `coal` | 0.485 | 0.485(該表只有 name plate,誤打誤撞已正確) |

⚠️ 代價要一起處理:name plate 是設計點效率,而 LP **沒有建強迫停機或最小負載**
→ 系統性樂觀。目錄有 `Availability` / `Forced outage` / `Minimum load` 三欄
(木片抽汽:forced 0.03、min load 0.45),用 availability 當**容量折減**就補得回來,不必動整數。

## ③ 🔴 結構性阻塞:LP 表達不了背壓機組,而 DK2 有 27% 的熱靠它們

目錄的抽汽表**完全沒有熱效率欄**(查 8 張全部 0 列)—— 兩個家族的燃料式**不同源**,
不是同一個類別加一個開關:

```
背壓  F = P/η_el ;  Q = P·η_th/η_el        ← 熱電綁死在 P = Cb·Q 一條線
抽汽  F = (P+Cv·Q)/η_el ; P ≥ Cb·Q ; P+Cv·Q ≤ P_max   ← 有可行域面積
```

`Cv = 1.0` 是背壓表的 **N/A 哨兵值**,不是物理量(`dea.is_back_pressure()` 已擋,
但目前只做到「擋下」,沒做到「支援」)。

**規模**:目錄 33 張 CHP 表,**24 張背壓、只有 9 張抽汽**。
**DK2 實測**(varmelast 2021–2026 供熱來源):熱電 64.4% / **垃圾焚化 27.3%(目錄裡全是背壓)** / 尖峰氣 4.5%。
→ **四分之一的 DK2 熱量現在結構上表達不了。** 這不是以後再說,是現在就擋路。

⚠️ 還有第三個溫度基準陷阱:Medium 機組是 `Cb (40°C/80°C)`,大型是 `(50°C/100°C)`。
CTR 是高溫傳輸網 → DK2 只能用 50/100 那批,混進 Medium 等於偷改熱網溫度。

## ④ 已同意的 `plant.py` 重構方向(還沒動手)

```
Fuel                  燃料價 + ef + 熱值
Unit(ABC)             共同:P_max, min_load, vom, availability
 ├ BackPressure       η_el, η_th
 └ Extraction         η_el, Cb, Cv, P_max
P2H                   Q_t = k_t·P_buy_t(**一個類別吃 k 向量就好**)
Store                 141b Large TTES
每個 Param 帶 source=("TC", ws, Technology, year, est) 五元組
```

- **`source` 五元組是最高價值的部分** — 它把 `STATUS.md` §4 那張手維護的來源表
  變成機器可查、可重跑驗證的東西,成本只是一個 dataclass 欄位。
- **刻意不開 `P2H(ABC)` + 兩個子類**:在 LP 裡電鍋爐與熱泵是同一條式子,
  只差 k 是常數 0.99 還是逐時 COP(T)。零行為差異不值得開介面。
- `min_load` / `forced_outage` 放進去當**資料**可以,但要標明 **LP 目前沒有用它們**。

## ⑤ 三件「使用者要自己處理、不要幫他猜」的事

| 事項 | 為什麼不能猜 |
| ---- | ------------ |
| **elafgift(DH 電鍋爐/熱泵的電力稅費與網費)** | 模型現在假設買電**零稅費** → **系統性高估 power-to-heat**,而 P2H 正是 C3 章主題。丹麥規則改過多次,使用者看得懂丹麥文 |
| **生質燃料價** | 無國際期貨。要能源署 `Samfundsøkonomiske beregningsforudsætninger` 或 Energipriser。**現在不再用天然氣價代打**(會跑出負成本),而是直接不跑生質原型 |
| **DK2 熱網供水/回水溫度** | `cop_from_temp` 裡寫死 70°C 是我編的,直接決定熱泵 COP。CTR/VEKS 年報應該有 |

## ⑥ 待定案的方向決策(問使用者,別自己定)

**「市場力」框架對 DH 是否成立?** 丹麥區域供熱受成本回收原則(hvile-i-sig-selv)規範
→ 非營利實體**沒有動機扣留產能抬價**。但電廠業主(Ørsted/Vattenfall)與熱網公司(市政)
可能是不同法人。**這決定目標函數該是成本最小化還是利潤最大化**,必須在建多 agent 層之前定案。
⚠️ 未查證原始法規,`STATUS.md` §7 第 1 點已標明。

## ⑦ 立即可做的下一步(依順序)

1. **修 `eta_el` 基準**(見 ②)—— 四個數字 + 一個基準一致性 self-check。既有 bug,獨立於重構。
2. **加背壓類別**(見 ③)—— 要動 `solve()` 的約束矩陣。DK2 的 27% 卡在這。
3. **`source` 五元組 + `Fuel` 拆出來**(見 ④)。
4. 抓 varmelast `/api/v1/heatdata` 廠級所有權+容量 → 解掉機組尺寸與 agent 切分。
5. 用 varmelast 的分類產熱直接驗 `chp.py` 的排程行為(不只驗需求)。

## ⑧ 絕對不要做的事

- **不要擅自刪 `new_data/` 裡的任何東西。** 使用者花很多心思整理,而且它是 gitignored、
  刪了無法從 repo 還原。`new_data/fuel/` 那兩個舊單欄檔雖被 `raw/` 取代,
  但 `load_duckdb._series()` 仍會 fallback 讀 → **等 duckdb 重建並驗證後再議**。
- **不要把 `chp.Plant` 跑出來的金額當結論引用。** 技術參數雖已是目錄真值,但
  ①`eta_el` 基準還沒修 ②機組容量與熱網規模沒對齊(目錄是單一機組典型值,
  試算比值 1.7×–2.9×,多出來的容量當純凝汽電廠賣電、利潤被記進「供熱成本」
  → 煤原型跑出 −€16/MWh_th)③`chp._real_demo` 的熱需求仍建立在 DK1 佔位值
  `19.0 × 0.08` 上。**方向可引用,水準不可引用。**
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
