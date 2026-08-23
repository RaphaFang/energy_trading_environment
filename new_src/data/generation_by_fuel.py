"""逐時**分燃料出力**(Biomass / Waste / Fossil Gas …)—— 熱側驗證的命脈。

🔴 **為什麼會有這支:原本的來源死了。**
`production_by_fuel.py` 用的 Energinet `ElectricityBalanceNonv`
**在 2026-01-06 12:15 停止發布**(2026-08-21 直接問 API 確認,最新一筆就是那裡)。
🔴 **而且它是靜默停的** —— 檔名還寫著 2026-08-21,抓取腳本也不會報錯,
只是資料停在半年前。**是 `new_src/data/coverage.py` 的稽核抓到的。**

**Energinet 的替代 dataset `ProductionConsumptionSettlement`(活到今天)沒有燃料分項** ——
它給的是 CentralPower / LocalPower 這種聚合,不是 Biomass / Waste / FossilGas。
→ 所以燃料分項改用 **ENTSO-E `query_generation`(Actual Generation per Production Type)**,
   DK_2 實測有 `Biomass / Fossil Gas / Fossil Oil / Solar / Waste / Wind Offshore / Wind Onshore`。

━━━ ⚠️ 與舊檔的關係:互補,不是取代 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

`new_data/production/production_dk*.parquet`(Energinet)**留著,不要刪** ——
它有 ENTSO-E 這邊沒有的 **`TotalLoad`** 與 **逐邊界的 `Exchange*`**,
價格形成那條線(`new_src/eda_price/`)全靠它。**但它只到 2026-01-06。**
→ 需要 2026 年之後的負載與交換,用 `ProductionConsumptionSettlement`
  (欄位 `GrossConsumptionMWh`、`ExchangeSE_MWh` 等;`residual_demand.py` 已經在用)。

⚠️ **口徑不同,不要直接接起來當一條序列**:Energinet 的是結算後的丹麥口徑,
ENTSO-E 的是 TSO 申報的歐洲口徑。**重疊期(2019–2026-01)要先比對再決定怎麼用。**
⚠️ ENTSO-E 這邊 **2025-10 起是 15 分鐘制**,與電價那邊同一個轉換,聚合要用 mean 不是 sum。

用法:python new_src/data/generation_by_fuel.py
"""

import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from window import END, START, paths_for, retire_superseded  # noqa: E402

OUT = Path("new_data/generation")
ZONES = ("DK_1", "DK_2")


def _flatten(d: pd.DataFrame) -> pd.DataFrame:
    """把 MultiIndex 欄攤成單層,**並且統一欄名**。

    🔴 **這一步不做的話會出現最難察覺的錯誤**:ENTSO-E 有些年份回傳單層欄(`Biomass`),
    有些回傳兩層(`Biomass / Actual Aggregated` + `Actual Consumption`)。
    直接攤平會讓**同一個量在不同年份落在不同欄** —— 2026-08-21 實測 DK_2 的 2021 年
    整年跑到 `Biomass | Actual Aggregated`,而 `Biomass` 那欄該年全是空的。
    接起來看起來有 8 年,其實每一欄都缺一年。

    → `Actual Aggregated` **就是**出力,直接併回主欄名;
      `Actual Consumption` 是該機組群自己的耗電(抽蓄那類),另存 `<燃料> | consumption`。
    """
    if isinstance(d.columns, pd.MultiIndex):
        d = d.copy()
        d.columns = [" | ".join(str(x) for x in c).strip() for c in d.columns]
    ren = {}
    for c in d.columns:
        if c.endswith(" | Actual Aggregated"):
            ren[c] = c[: -len(" | Actual Aggregated")]
        elif c.endswith(" | Actual Consumption"):
            ren[c] = c[: -len(" | Actual Consumption")] + " | consumption"
    return d.rename(columns=ren)


def fetch(zone: str, client) -> pd.DataFrame:
    """ENTSO-E 每次請求上限一年 → 分年抓再接起來。"""
    frames, cur = [], pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    while cur < end:
        nxt = min(cur + pd.DateOffset(years=1), end)
        d = None
        for attempt in range(4):  # ⚠️ ENTSO-E 偶發 5xx/超時 → 退避重試,不要整年掉
            try:
                d = client.query_generation(zone, start=cur, end=nxt, psr_type=None)
                break
            except Exception as e:
                if attempt == 3:
                    print(f"    · {cur.date()} → {nxt.date()}: 🔴 四次都失敗 ({type(e).__name__})")
                    break
                wait = 20 * (attempt + 1)
                print(f"    · {cur.date()} → {nxt.date()}: {type(e).__name__},{wait}s 後重試")
                time.sleep(wait)
        try:
            if d is None:
                raise RuntimeError("no data")
            # 🔴 **一定要在 concat 之前攤平**:有些年份回傳 MultiIndex 欄
            #    (燃料 × Actual Aggregated/Consumption),有些是單層 —— 混在一起
            #    concat 會炸 `Can only union MultiIndex with MultiIndex`。
            d = _flatten(d)
            frames.append(d)
            print(f"    · {cur.date()} → {nxt.date()}: {len(d):,} 列 × {d.shape[1]} 欄")
        except Exception as e:
            print(f"    · {cur.date()} → {nxt.date()}: 跳過 ({type(e).__name__})")
        cur = nxt
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index().tz_convert("UTC")
    df.index.name = "timestamp_utc"
    return df


def main() -> None:
    from entsoe import EntsoePandasClient

    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        raise SystemExit("先 export ENTSOE_TOKEN(見 entsoe_features.py 的 docstring)")
    client = EntsoePandasClient(api_key=token)
    OUT.mkdir(parents=True, exist_ok=True)

    for z in ZONES:
        path, old = paths_for(OUT, f"generation_{z.lower()}")
        if path.exists():
            print(f"· {z}: 已存在,跳過")
            continue
        print(f"· {z}:")
        d = fetch(z, client)
        if d.empty:
            print(f"  ✗ {z}: 完全沒資料")
            continue
        d.to_parquet(path, engine="pyarrow", compression="snappy")
        retire_superseded(path, old, None)
        # 🔴 逐年檢查:少一年就吵出來,不要讓「總列數看起來很多」蓋掉中間的洞
        yrs = d.groupby(d.index.year)["Biomass"].count() if "Biomass" in d else None
        if yrs is not None:
            want = range(int(START[:4]), int(END[:4]) + 1)
            holes = [y for y in want if yrs.get(y, 0) == 0]
            if holes:
                print(f"  🔴 {z} 缺年:{holes} —— **這個檔不完整,用之前先補**")
        cols = [c for c in ("Biomass", "Waste", "Fossil Gas") if c in d.columns]
        print(f"  ✓ {z}: {len(d):,} 列  {d.index.min()} → {d.index.max()}")
        if cols:
            print("    平均 MW: " + ", ".join(f"{c}={d[c].mean():.0f}" for c in cols))


if __name__ == "__main__":
    main()
