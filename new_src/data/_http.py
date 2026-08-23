"""抓取腳本共用的 HTTP 取數 —— **重試 + 分年切塊**。

**為什麼需要**:2026-08-21 把窗口從 2026-07-08 延到「今天」之後,
Energinet 的 `Elspotprices` / `ElectricityBalanceNonv` 對「一次要 7 年」開始回
**429 Too Many Requests**。⚠️ 不是資料沒了,是單次請求太大。

→ `paged_json()` 按年切塊、逐塊重試(指數退避),再接起來。
   **切塊是抓取層的事,存下來的仍然是一個完整檔** —— 分析層不該知道有切過。
"""

from __future__ import annotations

import time

import pandas as pd
import requests

RETRY_STATUS = {429, 500, 502, 503, 504}


def get_json(url: str, params: dict, timeout: int = 180, tries: int = 9) -> list:
    """單次取數,對可重試的狀態碼做指數退避(30s 起跳,上限 10 分鐘)。

    ⚠️ **Energinet 的 429 是 IP 級冷卻,不是單次請求太大** —— 2026-08-21 實測:
    切成一年一塊仍然被擋,而且要等**數分鐘**才會放行。所以退避要長,不能用秒級。
    """
    for i in range(tries):
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code in RETRY_STATUS and i < tries - 1:
            wait = min(30 * 2**i, 600)
            print(f"    · HTTP {r.status_code},{wait}s 後重試({i + 1}/{tries - 1})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()["records"]
    raise RuntimeError(f"{url}: 重試 {tries} 次仍失敗")


def paged_json(
    url: str, params: dict, start: str, end: str, years: int = 1, months: int | None = None
) -> pd.DataFrame:
    """按年(或月)切塊抓完 [start, end),回傳接好的 DataFrame。

    ⚠️ 切點用**左閉右開**,所以塊與塊之間不會重複計一筆。

    `months` 覆蓋 `years`,給**每年上百萬列**的 dataset 用
    (例:`PrivateConsumptionHeatingHour` 是逐時 × 90 市 × 5 住宅 × 2 供暖 ≈ 900 列/小時,
    一年就 790 萬列 —— 一次要一年會逾時)。
    """
    out, cur, end_ts = [], pd.Timestamp(start), pd.Timestamp(end)
    step = pd.DateOffset(months=months) if months else pd.DateOffset(years=years)
    while cur < end_ts:
        nxt = min(cur + step, end_ts)
        rec = get_json(url, {**params, "start": cur.strftime("%Y-%m-%d"),
                             "end": nxt.strftime("%Y-%m-%d")})
        out.append(pd.DataFrame(rec))
        print(f"    · {cur.date()} → {nxt.date()}: {len(rec):,} 列")
        cur = nxt
    df = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    return df
