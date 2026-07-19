# DK 電價預測 × 多 agent 儲能競爭模擬器

丹麥 DK1/DK2 隔日電價預測,以及「預測拿去做電池套利值多少錢」的多 agent 市場模擬。

**先讀 [`SIMULATOR_OVERVIEW.md`](SIMULATOR_OVERVIEW.md)** — 那是全貌地圖(每個零件是什麼、
用什麼假設、跑出什麼)。其餘文件:

| 文件                                                                                        | 內容                                       |
| ------------------------------------------------------------------------------------------- | ------------------------------------------ |
| [`DATA_CATALOG.md`](DATA_CATALOG.md)                                                        | 資料字典:每個源哪來、留哪些欄、會不會 leak |
| [`MODEL_MATH.md`](MODEL_MATH.md)                                                            | 統計模型的算式                             |
| [`MULTI_AGENT_MARKET.md`](MULTI_AGENT_MARKET.md)                                            | 市場機制設計與完整結果                     |
| [`LITERATURE.md`](LITERATURE.md)                                                            | 文獻                                       |
| [`TIER2_SCHEMA.md`](TIER2_SCHEMA.md) / [`TIER2_TIER3_FINDINGS.md`](TIER2_TIER3_FINDINGS.md) | ENTSO-E Tier-2/3 特徵                      |

## 結構

```
new_src/
├── data/       資料抓取 → new_data/*.parquet → energy.duckdb
│               calendar_features(spine) / elspot_price(目標 y) / weather_forecast /
│               energinet_forecast / residual_demand / fuel_prices / entsoe_features /
│               load_duckdb(合併,最後跑)
├── models/     統計模型預測電價
│               forecast.py  建模唯一一份(特徵/切分/Ridge/Lasso/LightGBM)
│               baseline.py  準度報表(MAE/RMSE/rMAE)
├── agents/     儲能 agent,一版一檔,層層疊上去
│               v1_single.py   單顆電池 price-taker、無 λ。perfect(天花板)/naive(地板)
│                              LP + settle 是全部版本共用的地基
│               v2_multi.py    多 agent + λ 價格衝擊 + 輪流最佳反應(Nash)
│                              belief/br 可**每家一份** → agent 能在體量/資訊/策略上異質
│               v3_cournot.py  agent 內化自身衝擊(LP→QP)+ 卡特爾/競爭 benchmark
│               v4_wind.py     風電商情境:電池溢價與對純風商的外部性
│               fringe.py      **λ 的估計與診斷**(多變數偏導數,不是模擬器的一部分)
├── compare.py    統一比較 harness(綁 models + agents,同一批測試窗)
└── experiment.py **產出論文數字的地方**:v3/v4/三把尺/異質 agent,各跑三組體量
```

依賴方向單向:`v4 → v3 → v2 → v1`。v3 不改 v2——它只是把自己的最佳反應用
`solve_day(..., br=cournot_br)` 傳進去。

## 跑

全部指令都從**專案根目錄**執行(資料路徑是相對的):

```bash
python new_src/models/baseline.py     # 預測準度:rMAE 表
python new_src/compare.py W           # 錢:各策略佔單顆基準幾成(W=週窗, M=月窗)
python new_src/experiment.py all      # 論文結果:v3/v4/三把尺/異質,各三組體量
python new_src/agents/fringe.py DK1   # λ 怎麼估出來的 + 診斷圖(存 figs/)
```

**兩個關鍵結果**(細節見 `SIMULATOR_OVERVIEW.md` §3):

- **丹麥現況(10 MW)下多 agent 機制加了零**:10 家競爭 = 1 家獨佔 = 93% 單顆基準。
  `λ×總淨量 = 0.04 €/MWh`,在 €60 的價上撼動不了任何東西。要 GW 級才咬得動。
- **預測優勢在競爭下被放大 6 倍**:LightGBM 相對 naive-24h 的優勢,
  10 MW 時是 1.18×,10 GW 時是 **6.3×**。競爭把價差壓平後,只有看得準的人抓得到剩下的窗口。

每個 agent 檔都有 `demo()` self-check,直接跑該檔就會驗證(斷言掛掉表示邏輯被改壞)。

每個 agent 檔都有 `demo()` self-check,直接跑該檔就會驗證(斷言掛掉表示邏輯被改壞)。

## 資料

`new_data/` 不進 git(76M parquet + duckdb)。重建:

```bash
docker compose --profile ingest up    # 或逐一跑 new_src/data/*.py
```

ENTSO-E 的 Tier-2 特徵需要 token:到 https://transparency.entsoe.eu 註冊,再寄信給
transparency@entsoe.eu 要 "Restful API access"(人工核發),然後把 `ENTSOE_TOKEN=...`
放進 `.env` 並解開 `docker-compose.yml` 裡的 `env_file`。沒 token 其餘 5 源照樣跑。

可訓練範圍 **2019-11-01 → 2025-09-30**(左界卡 Energinet 隔日出力預測起點,
右界卡 Elspotprices 小時制轉 15 分鐘制)。
