"""外部參數的**單一收斂點** — 稅費、關稅、處理費,以及尚未查證的佔位符。

為什麼要這個檔:這些數字全部來自模型外部(法規、公告費率、能源署統計),
散在各模組裡會出現「同一個假設有兩個值」的漂移,而且**看不出哪些是真的、哪些是我編的**。
全部集中在這裡,並且把佔位符列進 `PLACEHOLDERS` → 每次跑模型都會印出來。

**兩類東西性質完全不同,不要混**:

  ① `PLACEHOLDERS` — **尚未查證,預設 0**。模型跑得動,但結果在這個維度上是「無此成本」
     的反事實,**論文必須註明**。歸零不是中性的:它系統性地讓相關選項看起來太便宜。
  ② 其餘常數 — **有來源、有出處**,寫在各自的註解裡。它們是假設,但不是虛構。

用法:python new_src/heat/assumptions.py   (印出全部假設 + 佔位符警告)
"""

# ── 佔位符:尚未查證,預設 0,論文須註明 ──────────────────────────────
# ⚠️ 這三個歸零的**方向**是一致的:全都讓 power-to-heat 看起來比實際便宜。
#    P2H 正是 C3 章的主題 → 這是目前模型最大的已知偏誤來源。

TAU_EL = 0.0
"""τ elafgift 電力稅 [EUR/MWh_e] —— **佔位符**。

制度叫 **elpatronordningen**,2008 年起存在,2019–2020 也適用,但當時是「降低稅率」
而非現行的「退到最低額 0.4 øre/kWh」。逐年稅率在 elafgiftsloven 的法定附表裡,
二手來源都不給數字(查兩次未果)。現行淨額量級僅約 **EUR 0.05/MWh_e**,小到不影響排序。

🚩 **但減免的資格條件可能很重要**(2026-08-11 查到):要拿到減免必須是
「有熱電容量的已登記營業稅熱生產者」,定義為**熱電機組能涵蓋一年至少 75% 的總供熱量**
→ **獨立的電鍋爐或熱泵不適用減免,只有掛在熱電廠底下的才行**。
DK2 實測那 1.4% 的 P2H 裡兩種可能都有 → 這是 P2H 之謎的候選解釋之一。
"""

KAPPA_NET = 0.0
"""κ nettarif 網路關稅 [EUR/MWh_e] —— **佔位符**,而且**這個才是大的**。

與 elafgift 不同,**網路關稅不可退**。soeB25 Tabel 10 的
`el_transport_margin_over_70000MWh` = 2025 年 **189 DKK2025/MWh_e**(2026 年 167)
→ 換算約 **EUR 25/MWh_e**,除以 COP 後對熱約 **EUR 9/MWh_th**。
而修完基準 bug 後 P2H 的總價值只剩約 EUR 1.8/MWh_th → **足以把 P2H 完全壓掉**。

⚠️ 這個數字在 `new_data/soeb25_&_extra_params/soeb25_params.csv` 裡已經有真值,
   之所以仍設 0,是因為**尚未決定它在模型裡的適用邊界**(哪些機組落在
   >70,000 MWh 級距、電鍋爐與熱泵是否同級距、是否含在 SØB 的其他項裡)。
   要測 P2H 假設就把它設成真值重跑 —— 見模組末的 `p2h_tariff_eur_mwh_e()`。

🔑 **這個 189 幾乎確定是上界,不是 DH 廠實付**(2026-08-13):大型 DH 電鍋爐接在
**高壓層**、透過自己的平衡責任方買電,不走配電網也沒有零售加成。
所以**反推值若真的收斂到 25.3 才該起疑** —— 那等於在說 DH 廠付的是配電級費率。
⚠️ 參數名 `over_70000MWh` 指的是**年用電 >70,000 MWh 的大用戶級距**(已對 CSV 確認),
   不是家戶均值;但 **Tabel 10 本身沒看過**,無法排除該級距仍內含配電成分。
"""

THETA_WASTE = 0.0
"""θ 垃圾焚化的 CO2 稅 [EUR/tCO2] —— **佔位符**。

丹麥對垃圾焚化的碳課稅與 EU ETS 的關係(是否雙重、生質佔比怎麼扣)尚未查證,
見 `new_data/soeb25_&_extra_params/gaps.csv` 的 `co2_afgift_affald`。

⚠️ **重複計入的陷阱**:`PHI_GATE` 那個處理費**已經內含 ARC 自己應繳的垃圾稅費**。
   若把處理費當負燃料成本、又另外加一個 CO2 稅項,同一筆錢會被算兩次。
"""

PLACEHOLDERS = ["TAU_EL", "KAPPA_NET", "THETA_WASTE"]


# ── 統一假設:有來源,套用範圍刻意放寬 ────────────────────────────────

PHI_GATE = 635.0
"""φ 垃圾處理費 [DKK/ton,未稅]。

來源:**ARC 公告費率,2025-11-01 起,商業殘餘廢棄物(rest erhverv)**。
(同一份公告的「含處理」版本是 725;2022 年的市政 B-takst 是 487,已過期。)

**三家垃圾廠(ARC / Vestforbrænding / ARGO)共用這一個值**,不是因為查到它們收一樣的錢,
而是刻意的建模選擇:同地區、同法規、同為市政合作社 → 統一之後**三個 agent 的起跑點一致**,
之後觀察到的差異就來自容量與熱網位置,而不是來自我對費率的猜測。
Vestforbrænding 與 ARGO 的實際費率見 `gaps.csv`(仍缺)。

⚠️ 這筆錢在成本函數裡是**負的燃料價**:垃圾廠收錢燒垃圾,所以燃料成本為負。
"""

HEATING_VALUE_WASTE_GJ_PER_TON = 11.70
"""垃圾的熱值 [GJ/ton]。來源:soeB25 Tabel 1 儲存格 B18
(`new_data/soeb25_&_extra_params/soeb25_params.csv` 的 `heating_value_affald`)。"""

DKK_PER_EUR = 7.46
"""丹麥克朗兌歐元。DKK 在 ERM II 下釘住歐元,中心匯率 7.46038、波動帶 ±2.25%
(實務上維持在 ±0.5% 內)→ 用固定值,不用逐日匯率。

⚠️ 與煤價的 `EURUSD=X` 不同:那個要逐日,因為 USD 是浮動的。DKK 不是。
"""


def waste_fuel_price_eur_mwh(gate_fee_dkk_per_ton: float = PHI_GATE) -> float:
    """垃圾當燃料的價格 [EUR/MWh_fuel] —— **負值**(收錢燒垃圾)。

        −φ [DKK/ton] ÷ 熱值 [GJ/ton] × 3.6 [GJ/MWh] ÷ 匯率 [DKK/EUR]

    這是垃圾焚化廠在 merit order 裡永遠排最前面的原因:燃料成本為負,
    再貴的 O&M 都壓不過它。也是「prioriteret produktion」(優先生產)的經濟基礎。
    """
    dkk_per_gj = -gate_fee_dkk_per_ton / HEATING_VALUE_WASTE_GJ_PER_TON
    return dkk_per_gj * 3.6 / DKK_PER_EUR


def p2h_tariff_eur_mwh_e(dkk_per_mwh_e: float = 189.0) -> float:
    """把 soeB25 的網路關稅換成 EUR/MWh_e,方便直接餵給 `KAPPA_NET` 做敏感度。

    預設 189 DKK2025/MWh_e = soeB25 Tabel 10 的 2025 年
    `el_transport_margin_over_70000MWh`(2026 年是 167)。
    **這個函式不會改 KAPPA_NET** —— 要測就在呼叫端明確傳進 `solve()`。
    """
    return dkk_per_mwh_e / DKK_PER_EUR


SOEB25_CSV = "new_data/soeb25_&_extra_params/soeb25_params.csv"

BIOMASS_PARAMS = {
    "wood_chips": "fuel_price_traeflis_an_kraftvaerk",
    "wood_pellets": "fuel_price_traepiller_industri_an_kraftvaerk",
    "straw": "fuel_price_halm_an_kraftvaerk",
}
"""生質燃料價的 SØB25 參數名。**`an kraftvaerk` = 中央熱電廠**(對的那個),
`an vaerk` 是分散式/純熱廠 —— DK2 的 Amager/Avedøre 是中央熱電廠,不要拿錯。"""


def biomass_fuel_price_eur_mwh(year: int, kind: str = "wood_chips") -> float:
    """SØB25 的生質燃料價 [EUR/MWh_fuel]。**2025 以前直接拋錯,不回填。**

    🔴 **這個函式不解除生質價的阻塞**,只是讓 2025–2026 跑得動:
      ① **2021–2024 完全沒有** —— SØB25 的表從 2025 開始。這仍是主要窗口的阻塞。
      ② **連 2025 那格都不是結算價**,是「2025 年 1 月的遠期觀點」(Tabel 5 Note 3)。
      ③ 2022 能源危機時生質價暴漲,而那正是最值得研究策略行為的一年 ——
         **絕對不可以拿 2025 的價格鋪滿更早年份**(`gaps.csv` 的 `do_not_use` 明講)。

    刻意拋 `KeyError` 而不是回最近年份:預設值造成的災難見 [[no-fabrication-rule]]
    (`dea.get()` 舊版補的 gas_cc 中點讓成本正負號翻轉)。

    換算:DKK2025/GJ × 3.6 GJ/MWh ÷ 7.46 DKK/EUR。
    ⚠️ **faktorpris,不含稅費補貼與 VAT**(CSV 的 note 欄)。
    """
    import pandas as pd

    t = pd.read_csv(SOEB25_CSV)
    s = t[(t["param"] == BIOMASS_PARAMS[kind]) & (t["year"] == year)]
    if not len(s):
        yrs = sorted(t.loc[t["param"] == BIOMASS_PARAMS[kind], "year"].dropna())
        raise KeyError(
            f"SØB25 沒有 {kind} 在 {year} 年的燃料價(只有 {yrs[0]:.0f}–{yrs[-1]:.0f})。"
            "**不要拿別的年份代打** —— 2022 能源危機時生質價暴漲,用 2025 的值會把"
            "最值得研究的那一年抹平。見 gaps.csv 的 biomass_price_2019_2024。"
        )
    return float(s["value"].iloc[0]) * 3.6 / DKK_PER_EUR


_warned = False


def warn_placeholders(force: bool = False) -> list[str]:
    """把仍是佔位符的假設印出來。每個 process 印一次(`force=True` 可強制再印)。

    刻意**不是**寫進 log 或吞掉:模型每跑一次都應該有人看到哪些成本被歸零了。
    """
    global _warned
    g = globals()
    zeroed = [n for n in PLACEHOLDERS if g[n] == 0.0]
    if zeroed and (force or not _warned):
        _warned = True
        print(
            f"  ⚠️ 佔位符仍為 0(結果在這些維度上是「無此成本」的反事實):{', '.join(zeroed)}"
        )
        print(
            f"     其中 KAPPA_NET 有真值可用(soeB25 ≈ EUR {p2h_tariff_eur_mwh_e():.1f}/MWh_e),"
            "歸零會系統性高估 power-to-heat"
        )
    return zeroed


def demo() -> None:
    # 佔位符必須真的是 0 —— 若有人填了值卻忘了從清單移除,這行會抓到
    g = globals()
    for n in PLACEHOLDERS:
        assert n in g, f"PLACEHOLDERS 列了 {n} 但模組裡沒有這個常數"
    assert "PHI_GATE" not in PLACEHOLDERS, (
        "PHI_GATE 有真實來源,不是佔位符 —— 兩類性質不同,不要混"
    )

    # 垃圾燃料價必須是負的,而且量級要合理(處理費 635 DKK/t ≈ −EUR 26/MWh_fuel)
    w = waste_fuel_price_eur_mwh()
    assert w < 0, f"垃圾是收錢燒的,燃料價應為負,得 {w:.2f}"
    assert -40 < w < -10, f"垃圾燃料價量級不合理:{w:.2f} EUR/MWh_fuel"
    # 它必須比任何正的燃料價便宜 → merit order 最前面
    assert w < 0 < 10, "垃圾燃料價應該低於所有化石燃料"
    print(
        f"  垃圾燃料價 ok: φ={PHI_GATE:.0f} DKK/t ÷ {HEATING_VALUE_WASTE_GJ_PER_TON} GJ/t "
        f"× 3.6 ÷ {DKK_PER_EUR} = **{w:.2f} EUR/MWh_fuel**(負值 = 收錢燒垃圾)"
    )

    t = p2h_tariff_eur_mwh_e()
    assert 20 < t < 30, f"網路關稅換算量級不對:{t:.2f}"
    print(
        f"  網路關稅 ok: 189 DKK/MWh_e = EUR {t:.1f}/MWh_e"
        f"(除以 COP 2.8 → 對熱 EUR {t / 2.8:.1f}/MWh_th)"
    )
    # 生質價:2025 起有、2025 以前**必須拋錯**(這一條鎖住「不准回填」)
    import os

    if os.path.exists(SOEB25_CSV):
        b = biomass_fuel_price_eur_mwh(2025)
        assert 20 < b < 60, f"木片價量級不對:{b:.1f} EUR/MWh_fuel"
        for bad in (2022, 2024):
            try:
                biomass_fuel_price_eur_mwh(bad)
                raise AssertionError(f"{bad} 年不該有生質價,卻回了值 —— 有人偷偷回填了")
            except KeyError:
                pass
        print(
            f"  生質價 ok: 木片 2025 €{b:.1f}/MWh_fuel(SØB25 Tabel 2,faktorpris);"
            f"顆粒 €{biomass_fuel_price_eur_mwh(2025, 'wood_pellets'):.1f}、"
            f"秸稈 €{biomass_fuel_price_eur_mwh(2025, 'straw'):.1f}"
            "\n     🔴 **2021–2024 仍然沒有,阻塞未解**;2025 那格也只是遠期觀點不是結算價"
        )
    print(f"  佔位符 {len(PLACEHOLDERS)} 個:{', '.join(PLACEHOLDERS)}")


if __name__ == "__main__":
    print("=== 外部假設 ===")
    demo()
    print()
    warn_placeholders(force=True)
