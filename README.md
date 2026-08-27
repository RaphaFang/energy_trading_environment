# 丹麥能源市場模擬(碩論)

> ## 🔴 交接看 **[`HANDOVER.md`](HANDOVER.md)** —— 那是唯一入口,一頁講完現在在做什麼。
>
> **2026-08-27 起的主線是「交易 agent」**(單體、無對手模型、15 分鐘改制)。
> 熱側(CHP + 區域供熱)的成果沒有作廢,變成階段 2/3 的零件,完整記錄在
> [`MODEL_2035.md`](MODEL_2035.md)。電池線 2026-08-04 結案,見
> [`BATTERY_TRACK.md`](BATTERY_TRACK.md)。
>
> 📦 這份檔案原本有 922 行的歷史交接紀錄,**2026-08-27 移到
> [`archive/README_history_2026-08.md`](archive/README_history_2026-08.md)**。
> 下面只留還在生效的規矩。

## 工作慣例(這個專案的規矩)

- **所有指令從專案根目錄跑** — 路徑都是相對的。在子目錄跑會找不到 `new_data/`。
- **`new_data/` 是 gitignored** — 手機/雲端 Claude Code 看不到 ≠ 資料不存在。
- **原始資料存 raw**:不挑欄位、不換單位、不換幣別。
  清理與換算(USD→EUR、公噸→MWh、15分→逐時、丟 0 值、排除錯誤區間)一律在**分析時**做
  → 規則改了不用重抓。
- **抓取腳本要有 skip-if-exists**,絕不覆蓋已抓好的原始檔。
- **每個模組留一個可跑的 self-check**(`python <模組>` 就跑),不用測試框架。
  **self-check 要「重新推導」而不是「比對抄來的數字」** —— 例如 `dea.demo()` 是拿 16 張表
  重算 Cb 的基準,不是硬編一個 0.43。
- **標記不確定性**:佔位值要在程式碼註解裡寫明「這是我設的,未查證」。
  `STATUS.md` §4 是誠實的參數來源清單,四類 (A) 真實資料 / (B) 文獻官方 / (C) 佔位值 / (D) 校準值。
- **commit 訊息用英文**;程式註解與文件用中文。

## 已知的坑(踩過的,別再踩)

| 坑                                 | 說明                                                                                                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Energinet API 429                  | rate limit 很嚴,連續打會被封幾分鐘。**大量查詢要先抓一次存快取**再本地分析                                                                                                           |
| `ElectricityBalanceNonv` 15 分鐘制 | 2025-10 後轉 15 分鐘一筆。**流量**(MW)加總會把那段算 4 倍權重 → 先 `resample('1h').mean()`                                                                                           |
| **電價也是 15 分鐘制**             | 但價格是**強度量**:聚合一樣用 `mean`,**絕不能 sum**(與上一列是同一件事的兩面)                                                                                                        |
| DEA 目錄 `Cv = 1.0`                | **背壓式的 N/A 哨兵值不是真值**。照抄會讓容量線多一條不存在的限制 → `dea` 已歸零                                                                                                     |
| DEA 沒有 ctrl 中央估計             | **不要自己取 lower/upper 中點**(舊版就是這樣造出 gas_cc 的 300)→ `NoCentralEstimate`                                                                                                 |
| DEA 年份格點                       | 隨技術與 est 而異 → 取最接近年份,不能硬性相等                                                                                                                                        |
| `BE-VL-TOTAL-FAK`                  | varmelast 的 **CO2 排放強度(Kg/GJ)**,**不是熱量欄**。加進 MW_th 分母會算錯佔比                                                                                                       |
| 煤價是 USD                         | `MTF=F` 是 **USD/公噸**;換算在 `load_duckdb.build_fuel()` 做。碳價(ICAP)本來就是 EUR                                                                                                 |
| `el_net` 為負是正常的              | 熱是**義務不是商品**(無熱收入)→ 看 `heat_cost_per_mwh` 才有意義                                                                                                                      |
| 驗證要挑有識別力的標的             | 曾用 CHP 發電量驗熱需求代理 —— 電價影響大得多,**驗不動**。改用 varmelast 真值才驗得出來                                                                                              |
| 比較要控制住其他變數               | 驗「背壓 vs 抽汽」時若同時改 `cv`,就不是純粹放寬,測試會(正確地)失敗                                                                                                                  |
| **年佔比對得上 ≠ 模型對**          | 尖峰鍋爐年佔比 5.95% vs 實測 5.12%,但**日內時點符號相反**(−0.50 vs +0.170)。水準的識別力太弱                                                                                         |
| **季節性陷阱會一再出現**           | 「高價時出力更高」在同一天內幾乎都是反的。任何價格反應的檢定**一律先加日固定效果**                                                                                                   |
| **`aFRRVWA*EUR` 的 0 是哨兵** | aFRR 沒啟動時那一欄是 **0 不是缺值**。直接拿去比大小,0 會偽裝成最低價,把不平衡價的下調側規則算歪 → 只有 `aFRRUpMW`/`aFRRDownMW` 非零時才准進候選 |
| **制度改變不要對齊成同一天** | 不平衡結算、不平衡**定價規則**、日前市場、定價缺陷修正是**四個不同日期**。合併成一個「15 分鐘改制」會把三件事混成一件 |
| **參數有真值後要追預設值流到哪**   | θ_h 一有預設值,`run_model` 那個「垃圾原型當系統代理」就開始繳垃圾稅 → 尖峰鍋爐從 5.80% 暴衝到 71.65%。看起來像發現,其實是接線錯                                                      |
| **代理模型的錯配不只被抓到那一個** | θ_h 會跳出來只因為它從 0 變非 0。同一個代理裡 `p_fuel`/`ef`/`Cv` **從一開始就錯配**(車隊 64.6% 其實是生質),只是沒有暴露時刻 → **車隊層級數字不可直接比對實測**(`STATUS.md` §9.4c)    |
| **同一個數字在不同文件要對得起來** | θ_h 一天內在 23.8/23.9/23.85/**26.84** 之間動過(先是四捨五入不一致,後是排放係數級距修正)。**引用一律寫 26.84 或 55.6 DKK/GJ_heat**,並註明日期                                        |
| **「兩端一樣」通常是錯的說法**     | θ_h 兩端非全開小時 0.5% → 3.0% 是 **6 倍**,說「無差異」會被咬。要宣稱的是**研究結論**不敏感,不是**數字**一樣                                                                         |
| **稅費要掛對變數**                 | 丹麥垃圾三稅按**熱**計徵,掛在燃料上是錯的。**位置錯了掃描救不回來**(誤差方向取決於內生的 `Q/F`),而且會偽裝成「模型對價格過度反應」                                                   |
| **背壓關係會掩護量綱錯誤**         | `Q = η_th·F` 讓「掛 F」與「掛 Q」在背壓機上恆成比例 → 調參數對得上數字,但抽汽或部分負載就壞                                                                                          |
| **不要用行為反推稅費**             | 電鍋爐開關反推的 τ+κ 在不同樣本間 **+€25.5 ↔ −€16.5**。剛好貼近 soeB25 的 €25.3 是巧合 —— 而且 189 DKK 是**大用戶級距的上界**,DH 廠接高壓層、實付更低,**反推值收斂到 25.3 才該起疑** |
| **水準的敏感度不能推論到時點**     | 「佔比對燃料價 654× 敏感」不代表 ρ 也敏感。燃料價決定 merit order = 決定誰在邊際上 = 正是 ρ 在量的。要另外掃                                                                         |
| **兩端夾要先看有沒有輸出**         | 用「垃圾費 vs 氣價」當兩端,低端尖峰鍋爐全年只有 6 天有出力 → ρ 是 6 天算的,不是估計值                                                                                                |
| **分母要與對照組同源**             | LP 佔比分母是熱需求(消費),實測若用生產分項加總會多 2.44%(蓄熱+網損);且 `Qpb` 對應**氣+油**不是氣單獨                                                                                 |

---

## 先讀哪一份

| 文件 | 內容 |
| --- | --- |
| **[`HANDOVER.md`](HANDOVER.md)** ← 🎯 **只讀這個就好** | 現在在做什麼、四階段、下一步、明確不做 |
| [`DATA.md`](DATA.md) | 資料手冊:每個源哪來、留哪些欄、會不會 leak、踩過的坑 |
| [`MODEL_2035.md`](MODEL_2035.md) | 熱側:8-agent 聯合 LP、驗證、2035 情境、限制 |
| [`THESIS_DIRECTION.md`](THESIS_DIRECTION.md) | 熱側:研究問題、政策背景、**§10 收回過的說法** |
| [`STATUS.md`](STATUS.md) | ⚠️ 只剩 **§4 參數清單 / §7 / §8 / §9** 算數,見該檔標頭 |
| [`BATTERY_TRACK.md`](BATTERY_TRACK.md) | 電池線結案記錄 + 預測管道 —— 交易線的前情提要 |
| `archive/` | 封存,不再維護 |

## 結構

```
new_src/
├── data/        抓資料 → new_data/*.parquet(23 支,窗口統一 window.py)
│                elspot_price 電價(逐時 + 15 分兩段接力)
│                imbalance_price ★ 不平衡價(逐時 + 15 分,接縫 2025-03-04)
│                energinet_forecast ★ 官方風光預測(含預測世代欄位)
│                ept 全國 1,226 廠 / varmelast_heat DK2 熱需求 /
│                entsoe_features / weather_forecast / fuel_prices / biomass_prices /
│                heating_consumption / plandata_varmeplan / load_duckdb(最後跑)
│                coverage.py ★ 跑分析前先跑,查檔名窗口 vs 實際涵蓋
│
├── heat/        熱側(現為交易線的階段 2/3 零件)
│                joint_dispatch ★ 8-agent 聯合 LP、λ_heat、逐 agent 利潤
│                scenarios ★ 2035 情境網格(120 格)
│                demand_trend 2035 熱需求 hindcast
│                waste_reallocation 垃圾軸(否定結果)
│                assumptions 外部參數單一收斂點 / chp 排程 LP / validate 時點診斷
│                ept_fleet 逐台實測效率 / plant_lifetimes 官方退場年
│                baseline_dk2 · replacement_cost · sector_coupling · fuel_calibration
│
├── trading/     ★ 現行主線(交易 agent):
│                imbalance_regimes 不平衡價的四個制度期 + 反推定價規則
│                oracle            階段 0 完美預知上界(15 分 vs 逐時)
│                agent             日前交易 agent + 特徵 ablation(用錢排序)
│
├── eda_price/   價格形成診斷(λ、耦合率、聯絡線)
├── battery/     ★ 只剩兩支,留作交易線的地基:
│                v1_single perfect vs naive 資訊階梯 → 階段 0 的 oracle
│                fringe    保序迴歸估殘餘需求曲線
└── models/      forecast.py 預測管道(LightGBM + rMAE + 無 leak 驗證)
```

## 怎麼跑

```bash
python new_src/data/coverage.py            # ★ 跑分析前先跑
python new_src/data/elspot_price.py        # 電價(逐時 + 15 分)
python new_src/data/imbalance_price.py     # 不平衡價(逐時 + 15 分)
python new_src/heat/joint_dispatch.py 2024 # 熱側聯合 LP + 對實測驗證(約 2 秒)
python new_src/heat/scenarios.py           # 2035 情境網格(約 4 分鐘)

python new_src/trading/imbalance_regimes.py  # ★ 不平衡價四個制度期(約 5 秒)
python new_src/trading/oracle.py             # ★ 階段 0 完美預知上界(約 5 秒)
python new_src/trading/agent.py              # ★ 日前 agent + ablation(約 10 分鐘)
```

🔴 **不平衡價不是一條序列,是四個制度期** —— 2025-03-04 / 03-18 / 09-30 / 12-08 各換一次規則。
**乾淨的估計窗口是 2025-12-08 起**,跨接縫比較量到的是市場改革不是 agent 績效。見 `DATA.md` §12。

⚠️ `load_duckdb.py` **尚未納入 15 分鐘電價** —— `training` view 右界仍停在 2025-09-30。
2025-10 之後要自己讀 `price15_*.parquet` 並 `resample('1h').mean()`(價格是強度量,用 mean)。
⚠️ Energinet 的 **429 是 IP 級冷卻**(30s–600s 退避),而且**先抓再探索**。
