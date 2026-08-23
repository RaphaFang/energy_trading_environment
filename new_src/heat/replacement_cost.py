"""`THESIS_DIRECTION.md` §5.4 的可重現版本 —— 「換成熱泵」每座機組差多少錢。

**2026-08-22 建立,同時推翻舊版的三個錯。** 舊版是臨時腳本算的、沒進 repo,
它的 `Amager +25.97 / Avedøre +0.55 / 差 15 倍` 現在**重現不出來**。

━━━ 🔴 舊版的三個獨立錯誤 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**① 電熱比被當成自由參數,但它跟熱效率是綁在一起的。**
舊表對每台套同一個供熱成本基準、只讓電熱比 `r` 變,於是得到
「Avedøre `r=0.93` → 賣電抵掉燃料 → 供熱成本只有 +0.55」。
🔑 **但多發的電是拿熱換的:總效率大致守恆。** AVV2 的實測 `η_th` 只有 **0.372** ——
燃料價除以它就爆掉。**高電熱比買不到便宜的熱。**
→ 所以這支一律用 EPT 的**成對** `(η_el, η_th)`,不接受單獨給 `r`。

**② 熱泵成本用簡單平均,但要比的是「這些熱」。**
`(p_el+τ+κ)/COP` 簡單平均 €27.73,**用熱需求加權是 €31.23**。
天冷時電價高**且** COP 低,兩個一起惡化 → 簡單平均**低估熱泵 €3.49/MWh_th**。
🔑 **比較「這些熱改由熱泵供」時,權重必須是熱量不是小時。**

**③ `0.20` 是容量比,而且兩個容量不同來源**(varmelast 的 810 MW_th ÷ Energinet
反推的 166 MW_e)。EPT 說 Amager 的容量是 **214/651 = 0.329**,運轉實績是 **0.282**
(= AMV1 0.217 + AMV4 0.305 的加總假象)。

━━━ ⚠️ 這支是解析法,不是 LP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    c_th = p_fuel/η_th + (vom_e − p̄_el)·r + vom_th + θ_h      r = η_el/η_th

用的是**年平均運轉點**(正是 EPT 量到的東西):沒有蓄熱、沒有調度最佳化、沒有尖峰鍋爐、
沒有最小負載。**LP 版會給更低的供熱成本**(調度自由度值錢)→ 這張表對「換熱泵」
是**偏保守**(偏向讓 CHP 看起來貴)。

🔴 **最重要的一件事:燃料價的不確定性比「關哪一座」大一個數量級。**
生質五台合計:海關端 €40.2 → 約 −€1.5M/年;瑞典端 €32.2 → 約 +€80M/年。
**€81M 的翻轉。→ 在木片到廠價查到真值之前,不能宣稱「該關哪一座」的排序。**

用法:python new_src/heat/replacement_cost.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assumptions as A  # noqa: E402
import chp  # noqa: E402
import fuel_calibration as FC  # noqa: E402

OUT = Path("figs/heat_baseline")
YEAR = 2024  # 最後一個完整年,且 EPT 與電價都涵蓋

# 機組 → EPT `anlaeg_navn` 的前綴。**背壓垃圾廠用公司名**(它們的機組名不統一)。
UNITS = [
    ("AMV1 (1971)", "unit", "AMV1", "bio"),
    ("AMV4 (2019)", "unit", "AMV4", "bio"),
    ("AVV1 (蒸汽)", "unit", "AVV1 Damp", "bio"),
    ("AVV2 (複循環)", "unit", "AVV2 Komb", "bio"),
    ("KKV 8 (Køge)", "unit", "KKV 8", "bio"),
    ("ARC", "plant", ("Amager Ressourcecenter", "København"), "waste"),
    ("ARGO", "plant", ("ARGO", "Roskilde"), "waste"),
    ("Vestforbrænding", "plant", ("VESTFORBR", "Glostrup"), "waste"),
]


def _one(pattern: str) -> str:
    fs = sorted(glob.glob(pattern))
    assert len(fs) == 1, f"{pattern} 匹配到 {len(fs)} 個檔:{fs}"
    return fs[0]


def hourly(year: int = YEAR) -> pd.DataFrame:
    """該年的 DK2 電價、氣溫、CTR/VEKS 熱需求,逐時對齊。"""
    import validate as V

    y = V.load_dk2(2021).set_index("timestamp")
    y = y.loc[str(year)].dropna(subset=["price", "tair", "dem"])
    y["cop"] = chp.cop_from_temp(y["tair"].to_numpy())
    y["hp_cost"] = (y["price"] + A.TAU_EL + A.KAPPA_NET) / y["cop"]
    return y


def efficiencies(year: int = YEAR) -> pd.DataFrame:
    """EPT 逐台/逐廠的實測 `η_el`、`η_th`、電熱比與年熱交付。

    ⚠️ **機組級與廠級混用要小心**:AMV/AVV/KKV 用 `anlaeg_navn`(機組級);
    三座垃圾廠用 `(selskab_navn, vaerk_postdistrikt)`(廠級,因為它們有多條爐線
    分成多個 `vaerk_id`,不合併會低估一半 —— 見 `figs/ept_fleet/FINDINGS.md`)。
    """
    e = pd.read_parquet(FC.EPT)
    e = e[e["aar"] == year]
    rows = []
    for name, kind, key, fuel in UNITS:
        if kind == "unit":
            d = e[e["anlaeg_navn"].astype(str).str.startswith(key)]
        else:
            sel, dist = key
            d = e[
                e["selskab_navn"].str.contains(sel, na=False)
                & e["vaerk_postdistrikt"].astype(str).str.contains(dist, na=False)
            ]
        d = d[d["brutto_TJ"] > 0]
        assert len(d), f"{name}: EPT {year} 找不到對應的列(`anlaeg_navn` 可能改名了)"
        f = d["brutto_TJ"].sum()
        rows.append(
            dict(
                機組=name,
                燃料=fuel,
                eta_el=d["elprod_TJ"].sum() / f,
                eta_th=d["varmeprod_TJ"].sum() / f,
                年熱GWh=d["varmelev_TJ"].sum() * (1000 / 3.6) / 1000,
                eta_tot=(d["elprod_TJ"].sum() + d["varmeprod_TJ"].sum()) / f,
            )
        )
    t = pd.DataFrame(rows)
    t["電熱比"] = t["eta_el"] / t["eta_th"]
    return t


def table(y: pd.DataFrame, eff: pd.DataFrame, p_fuel_bio: float) -> pd.DataFrame:
    """一組燃料價假設下的完整成本表。

    🔴 **熱泵基準與電價都用熱量加權** —— 見模組 docstring 的錯誤②。
    """
    w = y["dem"] / y["dem"].sum()
    p_el = float((y["price"] * w).sum())
    hp = float((y["hp_cost"] * w).sum())
    bio = chp.dea_plant("wood_chips", p_max=166.0)
    wst = chp.dea_plant("waste", p_max=63.0)

    out = []
    for _, u in eff.iterrows():
        is_w = u["燃料"] == "waste"
        pl = wst if is_w else bio
        # 垃圾:燃料價是**負的**(收處理費),而且熱側有 θ_h 稅楔(掛在 Qc 上)
        fp = A.waste_fuel_price_eur_mwh() if is_w else p_fuel_bio
        theta = A.THETA_HEAT_WASTE if is_w else 0.0
        c = fp / u["eta_th"] + (pl.vom_e - p_el) * u["電熱比"] + pl.vom_th + theta
        out.append(
            dict(
                機組=u["機組"],
                燃料=u["燃料"],
                eta_el=u["eta_el"],
                eta_th=u["eta_th"],
                電熱比=u["電熱比"],
                燃料價=fp,
                供熱成本=c,
                熱泵成本=hp,
                每MWh差=hp - c,
                年熱GWh=u["年熱GWh"],
                年成本差_EURm=(hp - c) * u["年熱GWh"] / 1000,
            )
        )
    return pd.DataFrame(out)


def main() -> None:
    pd.set_option("display.width", 250)
    OUT.mkdir(parents=True, exist_ok=True)
    y, eff = hourly(), efficiencies()
    w = y["dem"] / y["dem"].sum()

    print("=" * 100)
    print(f"§5.4 基準({YEAR} DK2,{len(y):,} 小時)")
    print("=" * 100)
    print(
        f"  電價:簡單平均 €{y.price.mean():.2f} | **熱量加權 €{(y.price * w).sum():.2f}**"
    )
    print(f"  COP :簡單平均 {y.cop.mean():.2f} | 熱量加權 {(y.cop * w).sum():.2f}")
    print(
        f"  熱泵供熱成本:簡單平均 €{y.hp_cost.mean():.2f}"
        f" | **熱量加權 €{(y.hp_cost * w).sum():.2f}**"
        f" | 最冷 10% 小時 €{y.hp_cost[y.tair <= y.tair.quantile(0.10)].mean():.2f}"
    )
    print(
        f"  🔑 簡單平均**低估熱泵 €{(y.hp_cost * w).sum() - y.hp_cost.mean():.2f}/MWh_th**"
        " —— 天冷時電價高且 COP 低,兩個一起惡化。"
    )

    print("\n=== EPT 實測效率(這張表是整支腳本的地基)===")
    print(eff.round(3).to_string(index=False))
    hi = eff[eff.eta_tot > 1]
    if len(hi):
        print(
            f"  ⚠️ `eta_tot > 1`:{list(hi['機組'])} —— 煙氣冷凝,LHV 基準下正常,"
            "但會讓它的熱看起來特別便宜,論文要註明。"
        )
    print(
        "  🔑 **注意 η_th 與電熱比反向**:AVV2 電熱比 0.97 但 η_th 只有 0.372。"
        "**高電熱比是拿熱換來的。**"
    )

    ends = A.BIOMASS_ASSUMED_EUR_MWH[YEAR]["wood_chips"]
    tabs = {}
    for lab, fp in zip(("丹麥海關", "瑞典熱廠"), ends):
        t = table(y, eff, fp)
        tabs[lab] = t
        print(f"\n=== 生質價 = €{fp}/MWh({lab}端)===")
        print(t.round(2).to_string(index=False))
        b = t[t.燃料 == "bio"]["年成本差_EURm"].sum()
        wt = t[t.燃料 == "waste"]["年成本差_EURm"].sum()
        print(
            f"  生質五台合計 **{b:+.1f} €M/年**(每 MWh 差落在 {t[t.燃料 == 'bio']['每MWh差'].min():.2f}"
            f" … {t[t.燃料 == 'bio']['每MWh差'].max():.2f});垃圾三廠合計 **{wt:+.1f} €M/年**"
        )

    lo = tabs["丹麥海關"]
    hi2 = tabs["瑞典熱廠"]
    swing = abs(
        hi2[hi2.燃料 == "bio"]["年成本差_EURm"].sum()
        - lo[lo.燃料 == "bio"]["年成本差_EURm"].sum()
    )
    spread = (
        lo[lo.燃料 == "bio"]["年成本差_EURm"].max()
        - lo[lo.燃料 == "bio"]["年成本差_EURm"].min()
    )
    print("\n" + "=" * 100)
    print(
        f"🔴 **燃料價兩端的差 = €{swing:.0f}M/年;而「關哪一座」的最大差 = €{spread:.0f}M/年。**"
    )
    print("   → **在木片到廠價查到真值之前,不能宣稱「該關哪一座」的排序。**")
    print("✅ **垃圾三廠換熱泵明確地貴,而且不受燃料價假設影響**(它們的燃料價是負的)。")
    am = lo[lo.機組.str.startswith("AMV")]
    print(
        f"⚠️ **廠內兩台可以反號**:Amager 整廠 {am['年成本差_EURm'].sum():+.1f} €M,"
        f"但那是 AMV1 {am.iloc[0]['年成本差_EURm']:+.1f} 與 AMV4 {am.iloc[1]['年成本差_EURm']:+.1f} 的加總。"
        "\n   **「一廠一 agent」在成本結論上會把方向抹掉。**"
    )

    out = pd.concat(
        [t.assign(燃料價假設=k) for k, t in tabs.items()], ignore_index=True
    )
    out.to_csv(OUT / "replacement_cost_2024.csv", index=False)
    print(f"\n已存:{OUT}/replacement_cost_2024.csv")
    A.warn_assumed() if hasattr(A, "warn_assumed") else None


if __name__ == "__main__":
    main()
