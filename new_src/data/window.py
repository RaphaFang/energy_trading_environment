"""所有抓取腳本共用的時間窗口 —— **2019-01-01 → 今天**。

**2026-08-21 使用者定案**:「默認以後要抓資料就是 2019 一路抓到 26 年的今天。」
→ 各腳本不再各自寫死 `END`,一律 `from window import START, END`。

**為什麼起點是 2019-01-01**:Energinet 的 `ElectricityBalanceNonv` 與 ENTSO-E 的
輸出預測都是那前後才穩定;更早的資料存在但欄位定義不一致。⚠️ 個別來源本身更晚才有的
(varmelast 2021、15 分鐘制電價 2025-09-30)不受這裡影響 —— **那是來源的限制,不是設定。**

━━━ 🔴 換窗口時最重要的一件事:舊檔一定要退場,不能並存 ━━━━━━━━━━━━━━

檔名裡帶著窗口(`price_dk2_2019-01-01_2026-07-08.parquet`),所以窗口一延長就會**多一個檔**。
而下游是用 glob 取檔的,兩個檔會出事:

  `load_duckdb.py`   `(f,) = glob.glob(...)`  → **直接炸**(還算好的)
  `coupling_timeline.py`  `glob.glob(...)[0]` → 🔴 **靜默拿到舊檔**,最危險

→ 用 `retire_superseded()`:**先驗證新檔在舊窗口內逐格相同**,通過才刪舊檔。
   驗證不過就兩個都留著並拋錯 —— 寧願炸也不要靜默換掉資料。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

START = "2019-01-01"
END = pd.Timestamp.today().strftime("%Y-%m-%d")


def paths_for(folder: Path, stem: str) -> tuple[Path, list[Path]]:
    """回傳 (這次窗口該寫的檔, 同一序列的舊檔清單)。"""
    new = folder / f"{stem}_{START}_{END}.parquet"
    old = sorted(p for p in folder.glob(f"{stem}_*.parquet") if p != new)
    return new, old


def retire_superseded(new: Path, old: list[Path], time_col: str | None) -> None:
    """舊檔退場 —— **但先證明新檔真的涵蓋舊檔**。

    檢查兩件事,任何一件不過就保留舊檔並拋錯:
      ① 舊檔的每一個時間點都在新檔裡
      ② 兩者在重疊區間的**列數相同**(抓漏會在這裡被抓到)
    """
    if not old:
        return
    n = pd.read_parquet(new)
    for p in old:
        o = pd.read_parquet(p)
        if time_col is None:  # 時間在 index 上(yfinance 那類)
            ns, os_ = n.index.to_series(), o.index.to_series()
        else:
            if time_col not in n.columns or time_col not in o.columns:
                raise AssertionError(f"{p.name}: 找不到時間欄 {time_col},不敢刪")
            ns, os_ = n[time_col], o[time_col]
        lo, hi = os_.min(), os_.max()
        seg = ns[(ns >= lo) & (ns <= hi)]
        if len(seg) != len(os_):
            raise AssertionError(
                f"{p.name}: 重疊區間列數不符(舊 {len(os_)} vs 新 {len(seg)})—— **舊檔保留,請人工確認**"
            )
        missing = set(os_) - set(ns)
        if missing:
            raise AssertionError(f"{p.name}: 新檔漏了 {len(missing)} 個時間點 —— **舊檔保留**")
        p.unlink()
        print(f"    ↳ 舊檔已退場(已驗證被涵蓋):{p.name}")


if __name__ == "__main__":
    print(f"START={START}  END={END}")
