"""Energinet 分燃料出力的**水準校準** — 因為 `ElectricityBalanceNonv` 的燃料標籤是錯的。

━━━ 🔴 為什麼需要這支(2026-08-22 發現) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

拿 EPT(Energistyrelsen 的全國廠級普查,依法報送)對 `ElectricityBalanceNonv` 的**每一欄**:

    DK2 2024 熱電發電年均 MW      EPT 淨交付   Energinet    差
    Biomass                          359         263      +96
    Waste                             87          39      +48
    FossilGas                         17          66      −48
    煤                                 0         114     −114     ← 幽靈欄
    合計                             466         506     −7.8%

🔑 **總量只差 8%,標籤全錯。** DK2 從 **2020-03 AMV3 除役**後就沒有燒煤的機組
(EPT:2024/2025 的 `kul_TJ` = 0),Energinet 卻每年報 92–141 MW。
旁證:ENS 全國煤電 2024 = **199 MW**,而 Energinet **光 DK1 一區就報 258 MW**。

**所以規則是**:

| 要什麼 | 用什麼 |
| --- | --- |
| 水準、燃料別、機組別 | **EPT / ENS,一律** |
| 逐時形狀 | `ElectricityBalanceNonv`,但**只有「熱電總量」的形狀站得住** |
| 逐燃料的逐時序列 | **先乘這支算出來的校準因子**,並標明那是校準值 |
| 風、光、負載、聯絡線 | ✅ 不受影響 |

⚠️ **校準只動水準不動形狀。** EPT 是**逐年**的,給不了形狀 —— 這是這個方法的核心假設,
論文一定要寫出來:「我假設 Energinet 把某些機組的出力貼錯標籤,但貼錯的那些機組
**在小時之間的變化模式**與同燃料的其他機組相似。」

🔴 **不要只校準一欄。** 只校準 `Waste`,「生質/垃圾」倍數會算成 4.5×;兩欄都校準是 **6.2×**
—— **修一半的版本看起來很像修好了,而且錯的方向與原始錯誤相反。**

用法:python new_src/heat/fuel_calibration.py
"""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

EPT = "new_data/ept/ept_produktion_2023_2025.parquet"
ENS = "new_data/ept/ens_el_og_fjernvarmesektor_1972_2024__el.parquet"
OUT = Path("figs/ept_fleet")

# EPT 的燃料欄 → Energinet 的欄名。**兩邊都要列全**,漏一個會讓「佔全燃料投入」的分母錯。
EPT_FUEL = {
    "Biomass": [
        "halm_TJ",
        "skovflis_TJ",
        "trae- og biomasseaffald_TJ",
        "traepiller_TJ",
        "bio-olie_TJ",
        "biogas_TJ",
    ],
    "Waste": ["affald_TJ"],
    "FossilGas": ["naturgas_TJ"],
    "FossilHardCoal": ["kul_TJ"],
    "FossilOil": ["gasolie_TJ", "fuelolie_TJ"],
}
EPT_ALL = [
    "kul_TJ",
    "orimulsion_TJ",
    "petrokoks_TJ",
    "fuelolie_TJ",
    "spildolie_TJ",
    "gasolie_TJ",
    "raffinaderigas_TJ",
    "lpg_TJ",
    "naturgas_TJ",
    "affald_TJ",
    "biogas_TJ",
    "halm_TJ",
    "skovflis_TJ",
    "trae- og biomasseaffald_TJ",
    "traepiller_TJ",
    "bio-olie_TJ",
    "braendselsfrit_TJ",
    "solenergi_TJ",
    "vandkraft_TJ",
    "elektricitet_TJ",
    "omgivelsesvarme_TJ",
]

# ENS 長序列(1972–2024,**只有全國**)的燃料名 → 同一組燃料群。
# 用途:①驗證 EPT 的加總 ②**EPT 只有 2023–2025,更早的年份靠 ENS 外插**。
ENS_FUEL = {
    "Biomass": [
        "Halm",
        "Skovflis",
        "Træaffald",
        "Træpiller",
        "Bioolie",
        "Biogas",
        "Bionaturgas",
    ],
    "Waste": ["Affald, bionedbrydeligt", "Affald, ikke bionedbrydeligt"],
    "FossilGas": ["Naturgas"],
    "FossilHardCoal": ["Elværkskul", "Anden stenkul", "Koks m.m.", "Petroleumskoks"],
    "FossilOil": [
        "Fuelolie",
        "Gas-/dieselolie",
        "Spildolie",
        "LPG",
        "Orimulsion",
        "Nafta (LVN)",
    ],
}

TJ_TO_MWH = 1000 / 3.6


def _hours(year: int) -> int:
    return 8784 if year % 4 == 0 else 8760


def _area(postnr) -> str:
    """價區用郵遞區號代理(`<5000` → DK2)。與 `ept_fleet.py` 同一個規則。

    ⚠️ Bornholm(3700 Rønne)被歸進 DK2,但它其實接的是瑞典、不在 DK2 同步電網裡。
    它的發電量小到不影響結論,但論文提到分區時要註明。
    """
    return "DK2" if pd.notna(postnr) and postnr < 5000 else "DK1"


def ept_by_fuel() -> pd.DataFrame:
    """EPT 逐年 × 價區 × 燃料的發電量(MW 年均)。

    🔴 **按「該燃料佔全燃料投入的比例」分攤**,不是「主燃料歸類」——
    ARC 的垃圾純度只有 0.82、Norfors 只有 0.44,用主燃料歸類會把它們整台算進垃圾。
    ⚠️ 這假設**同一台機組的各種燃料有相同的發電效率**。對混燒的機組是近似;
    對純度 >0.95 的(絕大多數)幾乎沒有影響。
    """
    d = pd.read_parquet(EPT)
    for c in EPT_ALL:
        d[c] = d[c].fillna(0.0) if c in d else 0.0
    d["area"] = d["vaerk_postnr"].map(_area)
    d["tot"] = d[EPT_ALL].sum(axis=1)
    rows = []
    for (yr, area), g in d.groupby(["aar", "area"]):
        h = _hours(int(yr))
        for fuel, cols in EPT_FUEL.items():
            share = (g[cols].sum(axis=1) / g["tot"].replace(0, np.nan)).fillna(0.0)
            rows.append(
                dict(
                    year=int(yr),
                    area=area,
                    fuel=fuel,
                    ept_gross_MW=(g["elprod_TJ"] * share).sum() * TJ_TO_MWH / h,
                    # `ellev_TJ` = 扣掉廠用電後**送進電網**的量 → 與 TSO 的口徑相符。
                    # 🔴 拿 `elprod_TJ`(毛)去比 Energinet 會把低估倍數灌大約 25%。
                    ept_net_MW=(g["ellev_TJ"] * share).sum() * TJ_TO_MWH / h,
                )
            )
    return pd.DataFrame(rows)


def ens_national() -> pd.DataFrame:
    """ENS 長序列(全國、1972–2024)的分燃料發電量,MW 年均。用來驗 EPT + 往前外插。"""
    d = pd.read_parquet(ENS)
    inv = {n: f for f, ns in ENS_FUEL.items() for n in ns}
    d = d[d["energivare_dk"].isin(inv)].copy()
    d["fuel"] = d["energivare_dk"].map(inv)
    g = d.groupby(["aar", "fuel"], as_index=False)["el_produktion_TJ"].sum()
    g["ens_MW"] = g["el_produktion_TJ"] * TJ_TO_MWH / g["aar"].map(_hours)
    return g.rename(columns={"aar": "year"})[["year", "fuel", "ens_MW"]]


def energinet_by_fuel() -> pd.DataFrame:
    """`ElectricityBalanceNonv` 逐年 × 價區 × 燃料的年均 MW。

    🔴 **必須先 `resample('1h')`** —— 2025-10 起是 15 分鐘制,直接對 MW 欄位取平均
    會把那段算成 4 倍權重(`DATA.md` §5.8)。
    """
    rows = []
    for area in ("DK1", "DK2"):
        fs = sorted(
            glob.glob(f"new_data/production/production_{area.lower()}_*.parquet")
        )
        assert len(fs) == 1, (
            f"production_{area.lower()}_*.parquet 匹配到 {len(fs)} 個檔:{fs}"
        )
        d = pd.read_parquet(fs[0])
        d = d.set_index(pd.to_datetime(d["HourUTC"], utc=True))
        cols = [c for c in EPT_FUEL if c in d]
        h = d[cols].resample("1h").mean()
        y = h.groupby(h.index.year).mean().stack().rename("energinet_MW").reset_index()
        y.columns = ["year", "fuel", "energinet_MW"]
        y["area"] = area
        rows.append(y)
    return pd.concat(rows, ignore_index=True)


def factors() -> pd.DataFrame:
    """逐年 × 價區 × 燃料的校準因子 `EPT 淨交付 ÷ Energinet`。

    EPT 只涵蓋 2023–2025。更早的年份用 **ENS 全國 × EPT 量到的分區佔比 × 淨/毛比**
    外插,`source` 欄會標明是實測還是外插。

    🔴 **煤在 DK2 是幽靈欄** —— 分母 >0 而分子 = 0,因子會是 0。
    **那不是「要乘 0」,是「這一欄不存在,整列刪掉」**;`usable` 欄標 False。
    """
    e, en, ens = ept_by_fuel(), energinet_by_fuel(), ens_national()
    m = e.merge(en, on=["year", "area", "fuel"], how="outer")

    # EPT 有涵蓋的年份 → 逐年逐區的分區佔比與淨/毛比,拿來往前外插
    cov = e[e["year"].isin(sorted(e["year"].unique()))]
    tot = cov.groupby(["year", "fuel"], as_index=False)[
        ["ept_gross_MW", "ept_net_MW"]
    ].sum()
    shr = cov.merge(tot, on=["year", "fuel"], suffixes=("", "_nat"))
    shr["area_share"] = shr["ept_gross_MW"] / shr["ept_gross_MW_nat"].replace(0, np.nan)
    shr["net_ratio"] = shr["ept_net_MW"] / shr["ept_gross_MW"].replace(0, np.nan)
    key = shr.groupby(["area", "fuel"], as_index=False)[
        ["area_share", "net_ratio"]
    ].mean()

    back = ens.merge(key, on="fuel", how="left")
    back["ept_net_MW_hat"] = back["ens_MW"] * back["area_share"] * back["net_ratio"]
    m = m.merge(
        back[["year", "area", "fuel", "ept_net_MW_hat"]],
        on=["year", "area", "fuel"],
        how="left",
    )
    m["source"] = np.where(m["ept_net_MW"].notna(), "EPT 實測", "ENS×EPT 分區佔比 外插")
    m["ept_net_MW"] = m["ept_net_MW"].fillna(m["ept_net_MW_hat"])
    m["factor"] = m["ept_net_MW"] / m["energinet_MW"].replace(0, np.nan)
    # 幽靈欄:EPT **確實量到**這個價區沒燒這種燃料,而 Energinet 報了非零出力。
    # ⚠️ `ept_net_MW` 是 NaN 只代表「那一年還沒有 EPT/ENS 資料」(例:2026),
    #    **不是幽靈欄** —— 兩者要分開,不然整個燃料會被誤判成不可用。
    known = m["ept_net_MW"].notna()
    ghost = known & (m["ept_net_MW"] < 1.0) & (m["energinet_MW"].fillna(0) > 10.0)
    m["usable"] = (~ghost).astype("boolean")  # nullable boolean 才存得下「未知」
    m.loc[~known, "usable"] = pd.NA  # 未知 ≠ 不可用
    return m.drop(columns="ept_net_MW_hat").sort_values(["area", "fuel", "year"])


def factor_map(area: str, fuel: str) -> dict[int, float]:
    """`{年: 校準因子}`,給 `calibrate()` 用。缺的年份補最近一個有值的年。"""
    f = factors()
    ok = f["usable"] == True  # noqa: E712  (三值欄:True / False / NA)
    f = f[(f["area"] == area) & (f["fuel"] == fuel) & ok & f["factor"].notna()]
    assert len(f), f"{area}/{fuel}: 沒有可用的校準因子(可能是幽靈欄)"
    return dict(zip(f["year"].astype(int), f["factor"]))


def calibrate(s: pd.Series, area: str, fuel: str) -> pd.Series:
    """把逐時序列 `s` 乘上逐年校準因子。索引必須是 tz-aware 的時間索引。

    ⚠️ 超出校準因子涵蓋年份的部分,用**最近一年**的因子(而不是 1.0)——
    因為「沒有因子」的原因是 EPT 還沒報送,不是「那一年剛好沒問題」。
    """
    k = factor_map(area, fuel)
    lo, hi = min(k), max(k)
    yr = pd.Series(s.index.year, index=s.index).clip(lo, hi)
    return s * yr.map(k)


def main() -> None:
    pd.set_option("display.width", 220)
    OUT.mkdir(parents=True, exist_ok=True)
    f = factors()

    print("=== ① 驗證:EPT 的全國加總 vs ENS 長序列(毛發電,MW 年均)===")
    nat = (
        ept_by_fuel()
        .groupby(["year", "fuel"], as_index=False)["ept_gross_MW"]
        .sum()
        .merge(ens_national(), on=["year", "fuel"], how="inner")
    )
    nat["比值"] = nat["ept_gross_MW"] / nat["ens_MW"]
    print(nat.round(2).to_string(index=False))
    w = nat[(nat.fuel == "Waste") & (nat.year == 2024)]
    assert not len(w) or abs(w["比值"].iloc[0] - 1) < 0.01, (
        "EPT 與 ENS 的垃圾電力 2024 對不上 —— 分攤邏輯或燃料對照表壞了"
    )
    print("  ✅ 垃圾 2024 兩個獨立來源完全相等 → 分攤邏輯正確")

    print("\n=== ② 校準因子 EPT淨 ÷ Energinet ===")
    print(f.round(3).to_string(index=False))

    print("\n=== ③ 🔴 幽靈欄(EPT **量到**沒燒,Energinet 卻報了出力)===")
    g = f[f["usable"] == False]  # noqa: E712
    if len(g):
        print(
            g[["year", "area", "fuel", "ept_net_MW", "energinet_MW"]]
            .round(1)
            .to_string(index=False)
        )
        print("  → **這些欄位不是「要乘一個因子」,是整欄刪掉。**")

    print("\n=== ④ 只修一半有多危險(DK2,生質÷垃圾)===")
    import glob as _g

    fs = sorted(_g.glob("new_data/production/production_dk2_*.parquet"))
    d = pd.read_parquet(fs[0])
    d = d.set_index(pd.to_datetime(d["HourUTC"], utc=True))[
        ["Biomass", "Waste", "TotalLoad"]
    ]
    d = d.resample("1h").mean()
    d.loc[d.TotalLoad > 1.2 * d.TotalLoad.quantile(0.999), "TotalLoad"] = np.nan
    d = d.dropna(subset=["TotalLoad"])
    d = d[d.index.year.isin(range(2021, 2026))]
    bc, wc = calibrate(d.Biomass, "DK2", "Biomass"), calibrate(d.Waste, "DK2", "Waste")
    top = d.TotalLoad >= d.TotalLoad.nlargest(100).min()
    rows = []
    for lab, msk in [("全年", slice(None)), ("負載最高 100h", top)]:
        b, w2, bcc, wcc = d.Biomass[msk], d.Waste[msk], bc[msk], wc[msk]
        rows.append(
            dict(
                樣本=lab,
                兩欄原值=b.mean() / w2.mean(),
                只校準Waste=b.mean() / wcc.mean(),
                兩欄都校準=bcc.mean() / wcc.mean(),
            )
        )
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    print("  🔑 **只修被指出來的那一欄,會把倍數低估三成,而且錯的方向與原始錯誤相反。**")

    f.to_csv(OUT / "fuel_calibration.csv", index=False)
    print(f"\n已存:{OUT}/fuel_calibration.csv")


if __name__ == "__main__":
    main()
