"""耦合率的時間軸 —— 到 2026-08,並且用逐月定位轉折點。

**為什麼要分兩段**:2025-10 起歐洲日前市場從逐時 MTU 轉成 **15 分鐘 MTU**。
🔴 **不能把 15 分鐘價聚合成逐時再比** —— 兩區可能在小時內不同、小時均值卻相同(或反之)。
→ **各自在原生解析度上比**:2019-10→2025-09 用逐時,2025-10→2026-08 用 15 分鐘。

容差 0.01 EUR/MWh(丹麥的歐元價由 DKK 換算,鄰國是原生歐元,見 DATA.md §9.5)。
"""
from __future__ import annotations
import glob
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "new_data", ROOT / "figs" / "price_formation"
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang HK", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"figure.dpi": 140, "font.size": 9, "axes.grid": True, "grid.alpha": .25,
                     "axes.spines.top": False, "axes.spines.right": False})
TOL = 0.01
NB2 = ["SE4", "DE", "DK1"]          # DK2 的鄰居
NB1 = ["SE3", "NO2", "DE", "DK2"]   # DK1 的鄰居(英國無 ENTSO-E 價,見下)
ZMAP = {"SE3": "se_3", "SE4": "se_4", "DE": "de_lu", "NO2": "no_2"}


def era_hourly() -> pd.DataFrame:
    d = {}
    for z in ("dk1", "dk2"):
        f = glob.glob(str(DATA/f"price/price_{z}_*.parquet"))[0]
        d[z.upper()] = pd.read_parquet(f).set_index("HourUTC")["SpotPriceEUR"]
    for lab, stem in ZMAP.items():
        f = glob.glob(str(DATA/f"entsoe/price_{stem}_2019-10-01_*.parquet"))[0]
        d[lab] = pd.read_parquet(f).iloc[:, 0]
    return pd.DataFrame(d).dropna()


def era_quarter() -> pd.DataFrame:
    d = {}
    for z in ("dk1", "dk2"):
        f = glob.glob(str(DATA/f"price/price15_{z}_*.parquet"))[0]
        d[z.upper()] = pd.read_parquet(f).set_index("TimeUTC")["DayAheadPriceEUR"]
    for lab, stem in ZMAP.items():
        f = glob.glob(str(DATA/f"entsoe/price_{stem}_2025-10-01_*.parquet"))[0]
        d[lab] = pd.read_parquet(f).iloc[:, 0]
    return pd.DataFrame(d).dropna()


def coupling(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for z, nbs in (("DK1", NB1), ("DK2", NB2)):
        eq = pd.DataFrame({n: (df[z] - df[n]).abs() <= TOL for n in nbs}, index=df.index)
        out[f"{z}_至少一個"] = eq.any(axis=1)
        for n in nbs:
            out[f"{z}={n}"] = eq[n]
    return pd.DataFrame(out, index=df.index)


def main():
    h, q = era_hourly(), era_quarter()
    ch, cq = coupling(h), coupling(q)
    print(f"逐時段 {str(h.index.min())[:10]} → {str(h.index.max())[:10]}  {len(h):,} 筆")
    print(f"15分段 {str(q.index.min())[:10]} → {str(q.index.max())[:10]}  {len(q):,} 筆\n")

    both = pd.concat([ch, cq])
    yr = both.groupby(both.index.year).mean()
    n = both.groupby(both.index.year).size().rename("樣本數")
    yr = yr[["DK2_至少一個", "DK2=SE4", "DK2=DE", "DK2=DK1",
             "DK1_至少一個", "DK1=SE3", "DK1=NO2", "DK1=DE"]].join(n)
    print("=== 逐年 ==="); print(yr.to_markdown(floatfmt=".3f"))

    mo = both.groupby(both.index.to_period("M")).mean()["DK2_至少一個"]
    mo1 = both.groupby(both.index.to_period("M")).mean()["DK1_至少一個"]
    print("\n=== 逐月(2024-06 起,定位轉折點)===")
    t = pd.DataFrame({"DK2": mo, "DK1": mo1}).loc["2024-06":]
    print(t.to_markdown(floatfmt=".3f"))

    fig, ax = plt.subplots(1, 2, figsize=(12, 3.6))
    for z, c in [("DK2", "#d62728"), ("DK1", "#1f77b4")]:
        s = both.groupby(both.index.to_period("M")).mean()[f"{z}_至少一個"] * 100
        ax[0].plot(s.index.to_timestamp(), s.values, color=c, lw=1.3, label=z)
    for x, lab in [("2024-10-01", "北歐 FBMC 上線"), ("2025-10-01", "15 分鐘 MTU")]:
        ax[0].axvline(pd.Timestamp(x), color="k", ls="--", lw=.9)
        ax[0].text(pd.Timestamp(x), 8, "  " + lab, fontsize=7, rotation=90, va="bottom")
    ax[0].set_title("與至少一個鄰國同價的比例(逐月)"); ax[0].set_ylabel("%")
    ax[0].legend(frameon=False); ax[0].set_ylim(0, 105)
    for n, c in [("SE4", "#4477aa"), ("DE", "#d62728"), ("DK1", "#44aa77")]:
        s = both.groupby(both.index.to_period("M")).mean()[f"DK2={n}"] * 100
        ax[1].plot(s.index.to_timestamp(), s.values, color=c, lw=1.2, label=f"DK2 = {n}")
    for x in ("2024-10-01", "2025-10-01"):
        ax[1].axvline(pd.Timestamp(x), color="k", ls="--", lw=.9)
    ax[1].set_title("DK2 逐對同價比例(逐月)"); ax[1].set_ylabel("%")
    ax[1].legend(frameon=False, fontsize=8); ax[1].set_ylim(0, 105)
    fig.tight_layout(); fig.savefig(OUT/"09_coupling_timeline.png"); plt.close(fig)

    yr.to_csv(OUT/"coupling_by_year_to2026.csv")
    pd.DataFrame({"DK2": mo, "DK1": mo1}).to_csv(OUT/"coupling_by_month.csv")
    print(f"\n已存 {OUT}/09_coupling_timeline.png、coupling_by_year_to2026.csv、coupling_by_month.csv")


if __name__ == "__main__":
    main()
