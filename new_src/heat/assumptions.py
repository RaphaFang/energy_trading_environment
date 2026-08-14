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

THETA_HEAT_WASTE = 0.0
"""θ_h 垃圾焚化的**熱側稅楔** [EUR/MWh_th] —— **佔位符**,掛在 **Q** 上。

🔴 **2026-08-14 從 `THETA_WASTE` 搬過來,而且換了變數(F → Q)。這是本次修正的重點。**

丹麥垃圾焚化的三項國內稅 —— **affaldsvarmeafgift**、**tillægsafgift**、**CO2-afgift**
—— 計徵基礎**全部是熱**(Skat 法律指引 E.A.4.2.1 / E.A.4.5.7.3;
kulafgiftsloven / kuldioxidafgiftsloven,2010-01-01 起從 affaldsafgiftsloven 移入):

  · affaldsvarmeafgift  對焚化廠**交付出去的熱量**課徵,kr/GJ_heat
  · tillægsafgift        按每 GJ **產出熱量**課徵,kr/GJ_heat
  · CO2-afgift           僅對不可生物分解部分。形式上是 kr/tCO2,但**應稅量由熱量導出**
                         (Skat 範例用 v-formel 1.20 從熱反推燃料:5 GJ 熱 ÷ 1.20 = 4.17 GJ
                          燃料,再乘法定標準 0.070 tCO2/GJ)→ 最終仍與 Q 成比例。
  · 持有 Energistyrelsen CO2 排放許可的熱電廠,**用於發電的燃料免徵**。
    v-formel 存在的唯一目的就是把熱切出來。

**為什麼掛錯變數不能靠掃描救**:θ 掛 F、真實世界掛 Q,誤差方向取決於 `Q/F`,
而那是模型的**內生輸出** → 沿著錯的方向掃,掃出來的區間是假的。而且這種誤差會
**偽裝成別的東西**,最可能偽裝成「模型對價格過度反應」—— 正是目前未解的那個問題。
⚠️ **背壓關係在掩護這個錯誤**:`Q = η_th·F` 讓兩種形狀在背壓機上恆成比例,
   所以「調 θ 去對數字」是調得出來的 —— 但它會在抽汽彈性或部分負載時壞掉。

**這是窗口內固定的純量,不做逐年**,地位與 `PHI_GATE` 相同。
🔑 **與 φ 不重複計入**:φ 掛 F(每收一噸垃圾的收入,噸數透過熱值與 F 成正比)、
   θ_h 掛 Q —— **不同變數,不可能靜默互相抵消**。兩者必須同時保留:
   費率是收入、稅是成本,ARC 訂價時把稅覆蓋進去 ≠ 那筆費率是稅後淨額。**漏掉 θ_h 才是錯的。**
"""

THETA_FUEL_GAS = 0.0
"""θ_f **燃料側**國內碳稅 [EUR/tCO2] —— **佔位符**,掛在 **F** 上(原 θ 的位置)。

按燃料碳含量課徵,所以進 `ef·(p_CO2 + θ_f)` 的括號裡。
**靠 `ef` 歸零自動切換,不需要 if**:垃圾與生質的 `ef_chp = 0` → 自動不課;
天然氣尖峰鍋爐 `ef_pb = 0.20` → 會課到。這是本次重構掉出來的副產品。

量級感:`ef_gas = 57.1` kg/GJ ⇒ θ_f = 100 EUR/tCO2 ≈ 5.71 EUR/GJ_fuel
≈ **20.6 EUR/MWh_fuel** —— 對尖峰鍋爐是可觀的成本增加。
上界參考:丹麥 2025 年 CO2 稅約 851.8 DKK/tCO2 ≈ **EUR 114**(綠色稅改 2025-01-01 生效,
rumvarme 無漸進過渡)。⚠️ 這個數字尚未一手查證,只用來定掃描上界。
"""

PLACEHOLDERS = ["TAU_EL", "KAPPA_NET", "THETA_HEAT_WASTE", "THETA_FUEL_GAS"]

# `THETA_WASTE` 已退役(2026-08-14):它掛在 F 上而三項稅全部隨 Q 走。
# 刻意**不留別名** —— 留了會讓舊呼叫端默默套用錯的變數,而這正是要修的東西。


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
