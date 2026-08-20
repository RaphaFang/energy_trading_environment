"""鄰國日前電價 —— DK1/DK2 的價格是不是外部決定的,唯一能直接測量的量。

**為什麼要這個**:先前用「聯絡線滿載」當價格分離的代理,那是間接推論。
市場耦合的規則是:只要邊界沒塞滿,兩區的日前價格就會**完全相等**。
→ 「兩區價格一模一樣的小時佔幾成」是**測量**,不是推論。

抓哪幾區(只抓 DK 直接相鄰的,不是整個歐洲):
  SE_3  ← DK1 的鄰居(Konti-Skan)
  SE_4  ← DK2 的鄰居(Øresund)
  DE_LU ← DK1(Jylland-Tyskland)與 DK2(Kontek + Kriegers Flak)共同的鄰居
  NO_2  ← DK1 的鄰居(Skagerrak);DK2 不接挪威

慣例照 `entsoe_features.py`:存 `new_data/entsoe/`,檔名 `price_<zone>_<START>_<END>.parquet`,
索引 `timestamp_utc`,已存在就跳過絕不覆蓋。
"""
from __future__ import annotations
import glob, os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

RAW = Path("new_data/entsoe")
# 預設窗口 = 第一次抓的那段(逐時制)。2025-10 起歐洲日前市場轉 15 分鐘 MTU,
# 續抓要另開一個窗口,存成另一個檔(檔名帶起訖) —— 解析度不同,不要合併。
START = pd.Timestamp("2019-10-01", tz="UTC")
END = pd.Timestamp("2025-10-01", tz="UTC")
ZONES = ["SE_3", "SE_4", "DE_LU", "NO_2"]


def _have(name: str) -> bool:
    """這個窗口的檔抓過了嗎?比對完整檔名(含起訖),不同窗口視為不同檔。"""
    return (RAW / f"{name}_{START.date()}_{END.date()}.parquet").exists()


def _save(df: pd.DataFrame, name: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}_{START.date()}_{END.date()}.parquet"
    df.to_parquet(p, engine="pyarrow", compression="snappy")
    print(f"✓ {name}: {len(df)} rows  {df.index.min()} → {df.index.max()}  → {p}")


def _fetch_yearly(call, prefix: str) -> pd.DataFrame | None:
    frames, cur = [], START
    while cur < END:
        chunk_end = min(cur + pd.DateOffset(years=1), END)
        try:
            out = call(cur, chunk_end)
            frames.append(out.to_frame() if isinstance(out, pd.Series) else out)
        except Exception as e:
            print(f"  · {prefix} {cur.date()}→{chunk_end.date()}: skip ({type(e).__name__})")
        cur = chunk_end
    if not frames:
        print(f"  ✗ {prefix}: no data at all")
        return None
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index().tz_convert("UTC")
    df.index.name = "timestamp_utc"
    return df.add_prefix(f"{prefix}_")


def main() -> None:
    load_dotenv()
    token = os.getenv("ENTSOE_TOKEN")
    assert token, "ENTSOE_TOKEN 不在 .env 裡"
    client = EntsoePandasClient(api_key=token)
    for z in ZONES:
        name = f"price_{z.lower()}"
        if _have(name):
            print(f"· {name}: 已存在,跳過")
            continue
        df = _fetch_yearly(
            lambda s, e, z=z: client.query_day_ahead_prices(z, start=s, end=e), name
        )
        if df is not None:
            _save(df, name)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:  # 用法:python neighbour_prices.py 2025-10-01 2026-08-20
        START = pd.Timestamp(sys.argv[1], tz="UTC")
        END = pd.Timestamp(sys.argv[2], tz="UTC")
        print(f"窗口 {START.date()} → {END.date()}")
    main()
