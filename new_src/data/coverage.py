"""稽核 `new_data/` 每個檔的**實際**時間涵蓋,並與檔名宣稱的窗口比對。

**為什麼需要**:檔名帶的是「當初**要求**的窗口」,不是「實際**拿到**的資料」。
兩者可以差很多,而且不會有人提醒你:

  🔴 `ntc_dk_2_de_lu_2019-10-01_2026-08-21`  → 實際只到 **2024-02-29**(差 30 個月)
  🔴 `oc_dk_2_se_4_2019-10-01_2026-08-21`    → 實際只到 **2024-10-29**(北歐 FBMC 上線後停發)

這不是抓漏,是**來源停止發布**。但檔名看起來完全正常 → 拿去算「最近一年的壅塞」會靜默得到空值。
→ **跑分析前先跑這支**,或至少在用某個序列之前查一下它到哪裡。

用法:python new_src/data/coverage.py           # 全部
      python new_src/data/coverage.py entsoe   # 只看某個子目錄
"""

import re
import sys
from pathlib import Path

import pandas as pd

DATA = Path("new_data")
WIN = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")


def _span(df: pd.DataFrame):
    """找出這個檔的時間軸 —— 可能在 index,也可能在某個欄位。"""
    if isinstance(df.index, pd.DatetimeIndex):
        return df.index.min(), df.index.max()
    for c in df.columns:
        if "time" in c.lower() or c.lower() in ("hourutc", "hour_utc", "timestamp", "date"):
            s = pd.to_datetime(df[c], errors="coerce", utc=True)
            if s.notna().any():
                return s.min(), s.max()
    if "aar" in df.columns:  # 年度資料
        return df.aar.min(), df.aar.max()
    return None, None


def main(sub: str | None = None) -> None:
    root = DATA / sub if sub else DATA
    rows = []
    for f in sorted(root.rglob("*.parquet")):
        try:
            df = pd.read_parquet(f)
        except Exception as e:
            rows.append((str(f.relative_to(DATA)), "", "", f"讀不了:{e}", ""))
            continue
        lo, hi = _span(df)
        m = WIN.search(f.name)
        claimed = m.group(2) if m else ""
        flag = ""
        if claimed and isinstance(hi, pd.Timestamp):
            # ⚠️ 有些檔的時間軸有時區有些沒有 → 一律轉成 tz-naive 再比
            h = hi.tz_localize(None) if hi.tzinfo else hi
            gap = (pd.Timestamp(claimed) - h).days
            if gap > 45:
                flag = f"🔴 落後檔名 {gap} 天"
        # 🔴 頭尾對了不代表中間沒洞 —— 2026-08-21 踩過:ENTSO-E 的分燃料出力
        #    DK_2 少了 2023 與 2024 整整兩年,但總列數看起來完全正常。
        if isinstance(lo, pd.Timestamp) and isinstance(hi, pd.Timestamp):
            t = df.index if isinstance(df.index, pd.DatetimeIndex) else None
            if t is None:
                for c in df.columns:
                    if "time" in c.lower() or c.lower() in ("hourutc", "hour_utc", "timestamp"):
                        t = pd.DatetimeIndex(pd.to_datetime(df[c], errors="coerce", utc=True))
                        break
            if t is not None:
                per = pd.Series(1, index=t).groupby(t.year).size()
                holes = [y for y in range(int(lo.year), int(hi.year) + 1) if per.get(y, 0) == 0]
                if holes:
                    flag = (flag + " " if flag else "") + f"🔴 缺年 {holes}"
        rows.append((str(f.relative_to(DATA)), f"{len(df):,}",
                     str(lo)[:16], str(hi)[:16], flag))

    w = max(len(r[0]) for r in rows) if rows else 40
    print(f"{'檔':{w}}  {'列數':>10}  {'起':16}  {'迄':16}  備註")
    for r in rows:
        print(f"{r[0]:{w}}  {r[1]:>10}  {r[2]:16}  {r[3]:16}  {r[4]}")
    bad = [r for r in rows if r[4]]
    print(f"\n共 {len(rows)} 個 parquet;🔴 實際涵蓋明顯落後檔名的:{len(bad)} 個")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
