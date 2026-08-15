"""電價 target(y)。**兩個 dataset 前後接力,接縫在 2025-09-30**。

  `Elspotprices`    逐時,2018-12-31 → **2025-09-30 21:00 UTC**(歐洲 SDAC 改 15 分鐘制後停止)
  `DayAheadPrices`  **15 分鐘**,**2025-09-30 22:00 UTC** → 至今

2026-08-11 驗證過:兩者**完美對接,沒有重疊也沒有缺口**(前者最後一筆涵蓋到 22:00 UTC,
後者從 22:00 UTC 開始)。DK2 在 2025-09-30 → 2026-07-31 有 **29,184 筆、100% 非空、
相鄰間隔全部剛好 15 分鐘(零缺口)**。

**儲存 raw**:15 分鐘的原始解析度存下來,**不在儲存層聚合成逐時**。要逐時就在分析時
`resample('1h').mean()` —— ⚠️ 價格是**強度量不是流量**,聚合要用 **mean 不是 sum**
(這與 production 那邊「先 resample 再加總」的坑是同一件事的兩面)。
"""

import pandas as pd
import requests

# Nord Pool day-ahead hourly spot price per bidding zone — the model TARGET (y).
# Actual settled prices; safe as the label. Can be negative (wind oversupply).
URL = "https://api.energidataservice.dk/dataset/Elspotprices"
URL_15MIN = "https://api.energidataservice.dk/dataset/DayAheadPrices"


def fetch(start: str, end: str, area: str) -> pd.DataFrame:
    r = requests.get(
        URL,
        params={
            "start": start,
            "end": end,
            "filter": f'{{"PriceArea":["{area}"]}}',
            "sort": "HourUTC ASC",
            "limit": 0,
        },
        timeout=120,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json()["records"])
    df["HourUTC"] = pd.to_datetime(df["HourUTC"], utc=True)
    return df.sort_values("HourUTC").reset_index(drop=True)


def fetch_15min(start: str, end: str, area: str) -> pd.DataFrame:
    """`DayAheadPrices` —— 2025-09-30 之後的 15 分鐘制電價。全欄位原樣存。"""
    r = requests.get(
        URL_15MIN,
        params={
            "start": start,
            "end": end,
            "filter": f'{{"PriceArea":["{area}"]}}',
            "sort": "TimeUTC ASC",
            "limit": 0,
        },
        timeout=180,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json()["records"])
    df["TimeUTC"] = pd.to_datetime(df["TimeUTC"], utc=True)
    return df.sort_values("TimeUTC").reset_index(drop=True)


if __name__ == "__main__":
    from pathlib import Path

    START, END = "2019-01-01", "2026-07-08"
    S15, E15 = "2025-09-30", "2026-08-01"
    out_dir = Path("new_data/price")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        path = out_dir / f"price_{area.lower()}_{START}_{END}.parquet"
        if path.exists():
            print(f"· {area} 逐時:已存在,跳過")
        else:
            d = fetch(START, END, area)
            assert d["SpotPriceEUR"].notna().any(), f"{area}: no price data"
            d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
            neg = (d["SpotPriceEUR"] < 0).mean()
            print(
                f"✓ {area}: {len(d)} rows  {d['HourUTC'].min()} → {d['HourUTC'].max()}"
                f"  neg-price={neg:.1%}  → {path}"
            )

        # 15 分鐘制(2025-10 起)。**單獨一個檔**,不與逐時檔混 —— 解析度不同,
        # 合併是分析時的決定(見模組 docstring 的 mean/sum 提醒)。
        p15 = out_dir / f"price15_{area.lower()}_{S15}_{E15}.parquet"
        if p15.exists():
            print(f"· {area} 15 分鐘:已存在,跳過")
            continue
        d = fetch_15min(S15, E15, area)
        assert d["DayAheadPriceEUR"].notna().any(), f"{area}: no 15-min price"
        d.to_parquet(p15, index=False, engine="pyarrow", compression="snappy")
        gaps = d["TimeUTC"].diff().dt.total_seconds().div(60).dropna()
        neg = (d["DayAheadPriceEUR"] < 0).mean()
        print(
            f"✓ {area} 15min: {len(d):,} rows  {d['TimeUTC'].min()} → {d['TimeUTC'].max()}"
            f"  間隔全為 15 分={bool((gaps == 15).all())}  neg-price={neg:.1%}  → {p15}"
        )
