"""用 EPT 全國主檔算出「機組級的量與異質性」— 產出 `figs/ept_fleet/` 的 CSV。

`dk2_fleet.py` 是手工查六台;這支是**全國 1,226 座廠**的機器版本。
兩者的關係:`dk2_fleet` 仍然是模型的錨(它有 varmelast 的熱容量真值),
EPT 提供 ①**全國母體**(參數掃描要抽樣的分布)②**實測電熱比**③ 補上 NOT_FOUND。

━━━ 🔴 三個一定要照做的處理 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **一律 groupby(selskab_navn, vaerk_postdistrikt)** —— 一座實體廠常有多個 vaerk_id
   (ARGO 兩條爐線分兩列、Vestforbrænding 兩條分兩列)。不合併會**低估一半**。
2. **價區用郵遞區號判**:`postnr < 5000` → DK2(西蘭島 + Lolland-Falster + Bornholm),
   `>= 5000` → DK1(Fyn + Jylland)。⚠️ 這是**代理**,不是官方對應表,但邊界乾淨
   (DK1/DK2 分屬不同同步電網,Storebælt 是唯一連結)。
3. **電熱比用實績算,不用銘牌**:`elprod_TJ / varmelev_TJ`。
   ✅ 驗證:ARC 0.256 vs 年報 0.259、Avedøre 0.892 vs 模型假設 0.93。

用法:python new_src/heat/ept_fleet.py
"""

from pathlib import Path

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import ept  # noqa: E402

OUT = Path("figs/ept_fleet")
YEAR = 2024  # 最後一個完整年(2025 報送裡 2025 仍在滾動)

BIO = ["halm_TJ", "skovflis_TJ", "trae- og biomasseaffald_TJ", "traepiller_TJ"]
FUELS = [
    "kul_TJ", "naturgas_TJ", "affald_TJ", "biogas_TJ", "halm_TJ", "skovflis_TJ",
    "trae- og biomasseaffald_TJ", "traepiller_TJ", "bio-olie_TJ", "gasolie_TJ",
    "fuelolie_TJ", "solenergi_TJ", "elektricitet_TJ", "omgivelsesvarme_TJ",
    "braendselsfrit_TJ",
]

# KL 2020-12「死亡名單」10 座。比對用的是 (公司名 or 郵遞區) 的關鍵字。
KL_LIST = ["ARGO", "Maabjerg", "Norfors", "Hjørring", "Slagelse",
           "Sønderborg", "Aars", "Svendborg", "HAMMEL", "Bornholms"]

CPH_NET = "Storkøbenhavns Fjernvarme"  # varmelast 調度的那張網 = 模型邊界


def _area(postnr) -> str:
    return "DK2" if pd.notna(postnr) and postnr < 5000 else "DK1"


def _fuel_cap(d: pd.DataFrame, fuel_cols: list, suffix: str) -> pd.DataFrame:
    """只算**燒該燃料的 vaerk 記錄**的容量。

    🔴 為什麼要分開:合併同址的 vaerk 會把**尖峰鍋爐**也算進來
    (Vestforbrænding Glostrup 熱容量會從 142 灌到 203 MW_th)。
    → 兩個容量都留:`*_alle` = 全廠、`*_<燃料>` = 只有燒那個燃料的機組。
    """
    m = d[d[fuel_cols].sum(axis=1) > 0]
    g = m.groupby(["selskab_navn", "vaerk_postdistrikt", "area"], as_index=False).agg(
        **{f"el_MW_{suffix}": ("elkapacitet_MW", "sum"),
           f"th_MW_{suffix}": ("varmekapacitet_MW", "sum"),
           f"indfyret_MW_{suffix}": ("indfyretkapacitet_MW", "sum")})
    return g


def _plants(d: pd.DataFrame) -> pd.DataFrame:
    """把 vaerk_id 合併成「實體廠」,並算實測電熱比。

    ⚠️ 產出(TJ)合併是對的 —— 那是這座廠真的生產的量。
    ⚠️ **但容量合併會混進尖峰鍋爐** → 見 `_fuel_cap`,容量請用 `*_affald` / `*_bio`。
    """
    g = d.groupby(["selskab_navn", "vaerk_postdistrikt", "area"], as_index=False).agg(
        varmelev_TJ=("varmelev_TJ", "sum"),
        elprod_TJ=("elprod_TJ", "sum"),
        el_MW_alle=("elkapacitet_MW", "sum"),
        th_MW_alle=("varmekapacitet_MW", "sum"),
        indfyret_MW_alle=("indfyretkapacitet_MW", "sum"),
        n_vaerk=("vaerk_id", "nunique"),
        **{f: (f, "sum") for f in FUELS},
    )
    g["e_h_maalt"] = (g.elprod_TJ / g.varmelev_TJ).round(4)
    return g


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = ept.load("produktion")
    a = ept.load("anlaeg")
    p["area"] = p.vaerk_postnr.apply(_area)
    a["area"] = a.vaerk_postnr.apply(_area)
    d = p[p.aar == YEAR].copy()
    g = _plants(d)
    key = ["selskab_navn", "vaerk_postdistrikt", "area"]
    g = g.merge(_fuel_cap(d, ["affald_TJ"], "affald"), on=key, how="left")
    g = g.merge(_fuel_cap(d, BIO, "bio"), on=key, how="left")
    g["bio_TJ"] = g[BIO].sum(axis=1)
    g["braendsel_TJ"] = g[FUELS].sum(axis=1)
    # 🔴 純度欄位:合併同一郵遞區的 vaerk 時,別的燃料的**電**會被算進來。
    #    `*_andel` < 1 表示這個電熱比是混合的,不能當單一機組的技術參數用。
    g["bio_andel"] = (g.bio_TJ / g.braendsel_TJ).round(3)
    g["affald_andel"] = (g.affald_TJ / g.braendsel_TJ).round(3)

    # ① 全國垃圾焚化廠
    w = g[g.affald_TJ > 0].copy()
    w["ton_kt_ved_11GJ"] = (w.affald_TJ / 11).round(0)
    w = w.sort_values("varmelev_TJ", ascending=False)
    cols = ["selskab_navn", "vaerk_postdistrikt", "area", "affald_TJ", "affald_andel",
            "ton_kt_ved_11GJ", "varmelev_TJ", "elprod_TJ",
            "el_MW_affald", "th_MW_affald", "indfyret_MW_affald",
            "el_MW_alle", "th_MW_alle", "e_h_maalt", "n_vaerk"]
    w[cols].to_csv(OUT / "waste_plants_2024.csv", index=False)  # 純度欄位在 ⑧ 補

    # ② 全國生質廠(有發電的才是 CHP)
    b = g[g.bio_TJ > 0].sort_values("varmelev_TJ", ascending=False)
    b[["selskab_navn", "vaerk_postdistrikt", "area", "bio_TJ", "bio_andel", "varmelev_TJ",
       "elprod_TJ", "el_MW_bio", "th_MW_bio", "el_MW_alle", "th_MW_alle",
       "e_h_maalt", "n_vaerk"]].to_csv(
        OUT / "biomass_plants_2024.csv", index=False)
    # 「乾淨的」生質 CHP:生質佔投入 >80% 且有發電 → 電熱比可當技術參數
    bio_chp = b[(b.bio_andel > 0.8) & (b.elprod_TJ > 0)]

    # ③ 熱網規模 —— 「等比例體量」的分母
    n = d.groupby("fv_net_navn", as_index=False).agg(
        varmelev_TJ=("varmelev_TJ", "sum"), n_vaerk=("vaerk_id", "nunique"))
    n["pct_DK"] = (100 * n.varmelev_TJ / d.varmelev_TJ.sum()).round(3)
    n.sort_values("varmelev_TJ", ascending=False).to_csv(
        OUT / "dh_networks_2024.csv", index=False)

    # ④ 全國燃料結構
    fm = d.groupby("area")[FUELS].sum().T
    fm["DK_total"] = fm.sum(axis=1)
    fm["pct"] = (100 * fm.DK_total / fm.DK_total.sum()).round(2)
    fm.sort_values("DK_total", ascending=False).to_csv(OUT / "national_fuelmix_2024.csv")

    # ⑤ 死亡名單執行狀況 2023–2025
    wall = p[p.affald_TJ.fillna(0) > 0].copy()
    piv = wall.pivot_table(index=["selskab_navn", "vaerk_postdistrikt", "area"],
                           columns="aar", values="affald_TJ", aggfunc="sum").reset_index()
    piv["paa_KL_listen"] = piv.apply(
        lambda r: any(k.lower() in f"{r.selskab_navn} {r.vaerk_postdistrikt}".lower()
                      for k in KL_LIST), axis=1)
    piv.to_csv(OUT / "deathlist_status_2023_2025.csv", index=False)

    # ⑥ 模型邊界內的**所有機組**(含目前匿名的尖峰鍋爐與電鍋爐)
    cph = a[a.fv_net_navn == CPH_NET].copy()
    cph[["selskab_navn", "vaerk_postdistrikt", "anlaeg_navn", "anlaegstype_navn",
         "elkapacitet_MW", "varmekapacitet_MW", "Hovedbrændsel", "idriftdato",
         "skrotdato"]].sort_values("varmekapacitet_MW", ascending=False).to_csv(
        OUT / "copenhagen_units.csv", index=False)

    # ⑦ dk2_fleet 六台的機組級明細 —— 直接拿來對照/更新 dk2_fleet.py
    keys = ["Amager Ressource", "HOFOR ENERGIPRODUKTION", "VESTFORBRÆNDING",
            "ARGO", "VEKS I/S", "Ørsted Bioenergy"]
    m = a[a.selskab_navn.fillna("").str.contains("|".join(keys), case=False, regex=True)]
    m = m[m.varmekapacitet_MW.fillna(0) + m.elkapacitet_MW.fillna(0) > 0]
    m[["selskab_navn", "vaerk_postdistrikt", "area", "anlaeg_navn", "anlaegstype_navn",
       "elkapacitet_MW", "varmekapacitet_MW", "Hovedbrændsel", "idriftdato"]].to_csv(
        OUT / "dk2_fleet_units.csv", index=False)

    # ⑧ 🔑 **機組級實測效率** —— 生產檔是**機組級**(每年約 2,900 列 = 每台一列),
    #    而且有燃料投入 `brutto_TJ` → 每台的 eta_el / eta_th 是**量出來的**,不是目錄值。
    u = p[(p.brutto_TJ.fillna(0) > 0)].copy()
    u = u.merge(a[["vrkanl_ny", "anlaegstype_navn", "elkapacitet_MW", "varmekapacitet_MW",
                   "idriftdato"]], on="vrkanl_ny", how="left", suffixes=("", "_stam"))
    u["eta_el"] = (u.elprod_TJ / u.brutto_TJ).round(4)
    u["eta_th"] = (u.varmeprod_TJ / u.brutto_TJ).round(4)
    u["eta_tot"] = ((u.elprod_TJ + u.varmeprod_TJ) / u.brutto_TJ).round(4)
    u["e_h_maalt"] = (u.elprod_TJ / u.varmelev_TJ).round(4)
    u["area"] = u.vaerk_postnr.apply(_area)
    ucols = ["aar", "selskab_navn", "vaerk_postdistrikt", "area", "anlaeg_navn",
             "anlaegstype_navn", "idriftdato", "elkapacitet_MW_stam", "varmekapacitet_MW_stam",
             "brutto_TJ", "elprod_TJ", "varmeprod_TJ", "varmelev_TJ",
             "eta_el", "eta_th", "eta_tot", "e_h_maalt", "Hovedbrændsel"]
    ucols = [c for c in ucols if c in u.columns]
    u.sort_values(["aar", "brutto_TJ"], ascending=[True, False])[ucols].to_csv(
        OUT / "unit_efficiency_2023_2025.csv", index=False)

    tot = d.varmelev_TJ.sum()
    print(f"✓ {OUT}/  ({YEAR} 年基準)")
    print(f"  全國熱交付 {tot:,.0f} TJ = {tot / 3600:,.1f} TWh")
    print(f"  垃圾廠 {len(w)} 座(DK1 {(w.area == 'DK1').sum()} / DK2 {(w.area == 'DK2').sum()})")
    print(f"  燒生質的廠 {len(b)} 座;其中**生質佔投入>80% 且有發電**的 {len(bio_chp)} 座"
          f" ← 電熱比可當技術參數的母體")
    q = bio_chp.e_h_maalt.describe()
    print(f"    生質 CHP 電熱比:min {q['min']:.3f} / 中位 {q['50%']:.3f} / max {q['max']:.3f}")
    qw = w[w.affald_andel > 0.8].e_h_maalt.describe()
    print(f"    垃圾 CHP 電熱比({int(qw['count'])} 座):min {qw['min']:.3f} / 中位 {qw['50%']:.3f} / max {qw['max']:.3f}")
    print(f"  熱網 {n.fv_net_navn.nunique()} 個;{CPH_NET} 佔全國 "
          f"{n.loc[n.fv_net_navn == CPH_NET, 'pct_DK'].iloc[0]:.1f}%")
    ue = u[(u.aar == YEAR) & (u.brutto_TJ > 500) & (u.elprod_TJ > 0)]
    print(f"  機組級實測效率:{len(u):,} 列(3 年);{YEAR} 年燃料>500TJ 且有發電的 {len(ue)} 台,"
          f"eta_el 中位 {ue.eta_el.median():.3f}(範圍 {ue.eta_el.min():.3f}–{ue.eta_el.max():.3f})")
    print(f"  ⚠️ eta_tot > 1 的有 {(u[u.aar == YEAR].eta_tot > 1).sum()} 台 —— 煙氣冷凝(低熱值基準下正常)")
    print(f"  死亡名單 10 座中,2024 起停止投入垃圾的:"
          f"{[r.selskab_navn for _, r in piv[piv.paa_KL_listen].iterrows() if pd.isna(r.get(2025)) or r.get(2025) == 0]}")


if __name__ == "__main__":
    main()
