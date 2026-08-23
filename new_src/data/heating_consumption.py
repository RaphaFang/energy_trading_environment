"""家戶用電,按**住宅型態 × 供暖方式**拆分 — Energi Data Service,逐時,全國 + 逐市。

**這不是熱需求。** 它是**電**。但它是丹麥唯一一條**全國逐時、且與天氣直接耦合**的
公開供暖相關序列,而 `HeatingCategory = "Elvarme eller varmepumpe"` 正是
**「CHP 換成熱泵之後多出來的那條負載」的實測形狀**。

🔴 **掃過 EDS 全部 100 個 dataset(`/meta/dataset`),只有這三個跟供熱沾邊,而且都是電。
全國逐時熱需求不存在。** 逐時熱需求只有 varmelast 的哥本哈根那張網(= 全國供熱 26.0%)。
完整的替代來源清單見 `DATA.md` §11。

━━━ 🔴 抓之前一定要知道的三件事 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **來源本身從 `2021-01-01`(DK 時)才有,拿不到 2019。**
   → 檔名用 `SOURCE_START` 而**不是** `window.START`,不然 `coverage.py` 會把
   「檔名說 2019、實際 2021」報成抓漏。**這是來源的限制,不是設定。**
   ✅ 好處:它與 varmelast(也是 2021-01 起)**窗口完全對齊**,兩條序列可以逐時直接併。
2. **`HeatingCategory` 只有兩類**:`Elvarme eller varmepumpe` / `Andet`。
   🔴 **「電暖」與「熱泵」合併,拆不開**;`Andet` 含區域供熱、天然氣、油。
   → 想量「熱泵有多少」這份資料**答不了**,只能量「電力式供暖合計」。
3. **429 是 IP 級冷卻**(與 Energinet 同一個池),實測要退避 **100–250 秒**。
   `_http.get_json()` 的指數退避(30s→600s)已經涵蓋。**不要平行抓。**

用法:python new_src/data/heating_consumption.py
"""

from __future__ import annotations

import pandas as pd

from _http import paged_json

BASE = "https://api.energidataservice.dk/dataset/"

SOURCE_START = "2021-01-01"
"""這個來源自己的起點(DK 時)。**不要改成 `window.START`** —— 見模組 docstring 第 1 點。
2026-08-22 實測:`sort=TimeUTC ASC&limit=1` 的第一筆是 `2020-12-31T23:00 UTC`
= `2021-01-01T00:00` DK。逐時版與逐月版都一樣。"""

DATASETS = {
    # 全國版:10 列/小時(5 住宅型態 × 2 供暖方式)→ 全期約 49 萬列。先抓這個。
    "heating_el_national": dict(
        name="PrivateConsumptionHeatingNationalHour", sort="TimeUTC ASC", months=12
    ),
    # 逐市版:多了 MunicipalityCode / Municipality / RegionName,約 900 列/小時
    # (90 個市 × 5 × 2)→ 全期約 4,400 萬列。**必須按月切**,一次要一年會逾時。
    "heating_el_municipality": dict(
        name="PrivateConsumptionHeatingHour", sort="TimeUTC ASC", months=1
    ),
}

# 🅿️ 刻意不抓 `PrivateConsumptionHeatingMonth`:它是逐時版的月加總,
#    從 `heating_el_municipality` groupby 就得到,存兩份只會多一個會漂掉的來源。


def fetch(dataset: str, start: str, end: str, sort: str, months: int) -> pd.DataFrame:
    """原樣取回,只做時間欄轉型與數值轉型 —— **不挑欄位、不換單位**(見 README 工作慣例)。

    ⚠️ `ConsumptionkWh` 是**該小時的耗電量 kWh**,不是 MW。要 MW 就 `/1000`,
    但**那是分析時的事**,存下來的保持原單位。
    """
    df = paged_json(
        BASE + dataset, {"sort": sort, "limit": 0}, start, end, months=months
    )
    assert len(df), f"{dataset}: 沒有任何列"
    for c in ("TimeUTC", "TimeDK", "Month"):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=(c == "TimeUTC"))
    if "ConsumptionkWh" in df:
        df["ConsumptionkWh"] = pd.to_numeric(df["ConsumptionkWh"], errors="coerce")
    tcol = "TimeUTC" if "TimeUTC" in df else "Month"
    return df.sort_values(tcol).reset_index(drop=True)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from window import END, retire_superseded

    out_dir = Path("new_data/heating_consumption")
    out_dir.mkdir(parents=True, exist_ok=True)

    for stem, cfg in DATASETS.items():
        path = out_dir / f"{stem}_{SOURCE_START}_{END}.parquet"
        old = sorted(p for p in out_dir.glob(f"{stem}_*.parquet") if p != path)
        if path.exists():  # skip-if-exists:絕不覆蓋已抓好的原始檔
            print(f"· {stem}: 已存在,跳過 → {path}")
            continue
        print(f"· {stem} ← {cfg['name']}(每 {cfg['months']} 個月一塊)")
        d = fetch(cfg["name"], SOURCE_START, END, cfg["sort"], cfg["months"])
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        retire_superseded(path, old, "TimeUTC" if "TimeUTC" in d else "Month")

        tcol = "TimeUTC" if "TimeUTC" in d else "Month"
        hp = d[d["HeatingCategory"] == "Elvarme eller varmepumpe"][
            "ConsumptionkWh"
        ].sum()
        tot = d["ConsumptionkWh"].sum()
        geo = f"{d['Municipality'].nunique()} 個市" if "Municipality" in d else "全國"
        print(
            f"✓ {stem}: {len(d):,} 列  {d[tcol].min()} → {d[tcol].max()}  ({geo})\n"
            f"   HeatingCategory: {sorted(d['HeatingCategory'].unique())}\n"
            f"   HousingCategory: {sorted(d['HousingCategory'].unique())}\n"
            f"   電暖/熱泵佔家戶用電 {hp / tot:.1%}  → {path}"
            f"  [{path.stat().st_size / 1e6:.1f} MB]"
        )
