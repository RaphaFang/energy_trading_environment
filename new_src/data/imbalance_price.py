"""不平衡價 —— **「沒照計畫走」的結算價**。兩個 dataset 前後接力,接縫在 2025-03。

  `RegulatingBalancePowerdata`  逐時,1999-06-30 → 約 2025-03(**已停更**)
  `ImbalancePrice`              **15 分鐘**,2025-03-04 → 至今

🔑 **為什麼接縫在 2025-03 而不是 2025-09-30**:北歐的**不平衡結算**比日前市場**早半年**
就切到 15 分鐘。所以這條線上有**兩個不同時點的制度改變**:

    2025-03-04  不平衡結算 → 15 分鐘
    2025-09-30  日前市場   → 15 分鐘(見 `elspot_price.py`)

⚠️ 這兩個日期不一樣是**制度事實**,不是抓錯。分析時不要對齊成同一天。

━━━ 不平衡價是什麼 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

你在日前賣了 100 MWh、實際只發 90 → 少的 10 要用不平衡價買回來;發了 110 → 多的
10 用不平衡價賣掉。**它是相對現貨價定義的**,取決於當下整個系統缺電還是電太多
(北歐單一價格模型):

    DominatingDirection =  0  系統不缺不多 → **不平衡價 == 現貨價**(實測完全相等)
    DominatingDirection = -1  系統電太多   → 不平衡價 ≤ 現貨價
    DominatingDirection = +1  系統缺電     → 不平衡價 ≥ 現貨價

→ **猜錯方向要付兩次錢**:系統缺電時你也缺,買回來特別貴。這個不對稱正是「預測錯誤
   要花多少錢」的來源,也是任何有實體部位的 agent 的目標函數裡的懲罰項。

**儲存 raw**:15 分鐘的原始解析度存下來,**不在儲存層聚合成逐時**。價格是強度量,
要逐時就在分析時 `resample('1h').mean()`(與 `elspot_price.py` 同一條紀律)。
"""

import pandas as pd

from _http import paged_json

# 逐時(舊制)。除了 ImbalancePriceEUR 還有上下調節價與 mFRR 啟動量 —— 全欄位原樣存,
# 特徵挑選是分析層的事。
URL_HOUR = "https://api.energidataservice.dk/dataset/RegulatingBalancePowerdata"
# 15 分鐘(2025-03-04 起)。含 SpotPriceEUR 與 DominatingDirection,可直接做上面那個
# 「方向 = 0 時是否恰等於現貨價」的 self-check。
URL_15MIN = "https://api.energidataservice.dk/dataset/ImbalancePrice"


def fetch_hour(start: str, end: str, area: str) -> pd.DataFrame:
    df = paged_json(
        URL_HOUR,
        {"filter": f'{{"PriceArea":["{area}"]}}', "sort": "HourUTC ASC", "limit": 0},
        start,
        end,
    )
    df["HourUTC"] = pd.to_datetime(df["HourUTC"], utc=True)
    return df.sort_values("HourUTC").reset_index(drop=True)


def fetch_15min(start: str, end: str, area: str) -> pd.DataFrame:
    df = paged_json(
        URL_15MIN,
        {"filter": f'{{"PriceArea":["{area}"]}}', "sort": "TimeUTC ASC", "limit": 0},
        start,
        end,
    )
    df["TimeUTC"] = pd.to_datetime(df["TimeUTC"], utc=True)
    return df.sort_values("TimeUTC").reset_index(drop=True)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from window import END, START, paths_for, retire_superseded

    S15, E15 = "2025-03-01", END  # 15 分鐘制的起點是**來源**的限制,不是設定
    out_dir = Path("new_data/imbalance")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        path, _old = paths_for(out_dir, f"imbalance_{area.lower()}")
        if path.exists():
            print(f"· {area} 逐時:已存在,跳過")
        else:
            print(f"抓 {area} 逐時 RegulatingBalancePowerdata …")
            d = fetch_hour(START, END, area)
            assert d["ImbalancePriceEUR"].notna().any(), f"{area}: no imbalance price"
            d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
            retire_superseded(path, _old, "HourUTC")
            ok = d[d["ImbalancePriceEUR"].notna()]
            print(
                f"✓ {area} 逐時: {len(d):,} 列  {d['HourUTC'].min()} → {d['HourUTC'].max()}"
                f"\n    非空 {len(ok):,} 列,最後一筆非空 = {ok['HourUTC'].max()}  ← 停更點"
            )

        p15 = out_dir / f"imbalance15_{area.lower()}_{S15}_{E15}.parquet"
        _old15 = sorted(
            q for q in out_dir.glob(f"imbalance15_{area.lower()}_*.parquet") if q != p15
        )
        if p15.exists():
            print(f"· {area} 15 分鐘:已存在,跳過")
            continue
        print(f"抓 {area} 15 分鐘 ImbalancePrice …")
        d = fetch_15min(S15, E15, area)
        assert d["ImbalancePriceEUR"].notna().any(), f"{area}: no 15-min imbalance"
        d.to_parquet(p15, index=False, engine="pyarrow", compression="snappy")
        retire_superseded(p15, _old15, "TimeUTC")

        # self-check:方向 = 0 的時候,不平衡價必須恰等於現貨價。這是制度規定,
        # 不是近似 —— 對不上就是欄位對錯了,寧願現在炸掉。
        z = d[(d["DominatingDirection"] == 0) & d["ImbalancePriceEUR"].notna()]
        if len(z):
            same = (z["ImbalancePriceEUR"] - z["SpotPriceEUR"]).abs().lt(1e-6).mean()
            assert same > 0.99, f"{area}: 方向=0 時只有 {same:.1%} 與現貨價相等"
        gaps = d["TimeUTC"].diff().dt.total_seconds().div(60).dropna()
        print(
            f"✓ {area} 15min: {len(d):,} 列  {d['TimeUTC'].min()} → {d['TimeUTC'].max()}"
            f"\n    間隔全為 15 分={bool((gaps == 15).all())}"
            f"  方向=0 時等於現貨價 ={same:.1%} (n={len(z):,})"
        )
