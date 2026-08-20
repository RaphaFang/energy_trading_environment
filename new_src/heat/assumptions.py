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


# ══════════════════════════════════════════════════════════════════════
#  匯率 —— 所有稅費換算的基礎,所以放最前面
# ══════════════════════════════════════════════════════════════════════

DKK_PER_EUR = 7.46
"""丹麥克朗兌歐元。DKK 在 ERM II 下釘住歐元,中心匯率 7.46038、波動帶 ±2.25%
(實務上維持在 ±0.5% 內)→ 用固定值,不用逐日匯率。

⚠️ 與煤價的 `EURUSD=X` 不同:那個要逐日,因為 USD 是浮動的。DKK 不是。
"""


# ══════════════════════════════════════════════════════════════════════
#  ① 電力側稅費 τ / κ —— ✅ 2026-08-15 起是真值,不再是佔位符
#     兩者都只打在**買電**上:成本式的 (τ+κ)·P⁻,P⁻ = max(−P, 0)。
#     CHP 賣電走 P⁺,完全不碰。→ 它們**只影響 power-to-heat**,不是共同加項,
#     所以不會在 merit order 裡相消。
# ══════════════════════════════════════════════════════════════════════

ELPATRON_CAP_DKK_MWH = {
    2020: 221.0,
    2021: 8.0,
    2022: 8.0,
    2023: 8.0,
    2024: 8.0,
    2025: 8.0,
    2026: 8.0,
}
"""**elpatronordningen 的最高稅負上限** [DKK/MWh_e],逐年公布值。

來源:PwC《Forsyningsvirksomheder – overblik over afgiftssatser》各年版,表
「Maksimal afgiftsbelastning på fjernvarme ab værk (elpatronordningen)」的 **Elektricitet** 列。

🔑 **為什麼用上限而不是名目稅率**:一般工商用電的 elafgift 在窗口內是 **72–76 øre/kWh**
(720–760 DKK/MWh),但區域供熱產熱用電適用 elpatronordningen —— 一個**封頂退稅**機制,
超過上限的部分可退 → **廠實付的就是上限本身**。

🔴 **2020 → 2021 上限砍 96%(221.0 → 8.0)**。2020 年電鍋爐每 MWh_e 多付約 **EUR 28.6**,
足以讓它幾乎不可能進 merit order → **這是「窗口從 2021-01 起算」的第四個獨立理由**
(另三個:2019–2020 沒有生質燃料價、AMV3 燃煤 2020-03 退出、BIO4 2019-10 進場)。
**2019–2020 的 P2H 與 2021 之後不是同一個制度期** —— 有人要把窗口往前拉時拿這條出來。
"""

TAU_EL = ELPATRON_CAP_DKK_MWH[2021] / DKK_PER_EUR
"""τ elafgift 電力稅 [EUR/MWh_e] ≈ **1.07**。✅ **真值,不是佔位符**(2026-08-15)。

`8.0 DKK/MWh_e ÷ 7.46`。**窗口內 2021–2026 是常數 8.0** → 不需要逐年序列,也不需要指數化推算。
量級:對電價 €30–80/MWh 是 **1–3%**,填 0 與填真值對調度幾乎無差別 ——
但既然真值已知就填,**省掉論文裡「為何忽略」的辯護**。

⚠️ **τ 可退、κ 不可退**,兩者性質不同,不要類比。
"""

# Energinet 對用電只收兩種費(2025 年費率,øre/kWh)
NETTARIF_ORE_KWH = 6.1
"""nettarif:132/150 kV 與 400 kV 網及對外連接線的投資、折舊、營運(含網損)、維護。"""
SYSTEMTARIF_ORE_KWH = 7.4
"""systemtarif:供電安全與品質、系統服務(主要是備轉採購)、系統營運、DataHub。"""
NETTARIF_HV_REBATE_ORE_KWH = 0.5
"""**自有 132/150 kV 變壓器、在 132/150 kV 側結算**者的 nettarif 減免。"""
SYSTEMTARIF_LARGE_REBATE = 0.90
"""**年用電超過 100 GWh 的部分** systemtarif 減 90%。"""

KAPPA_NET = (
    (
        (NETTARIF_ORE_KWH - NETTARIF_HV_REBATE_ORE_KWH)
        + SYSTEMTARIF_ORE_KWH * (1.0 - SYSTEMTARIF_LARGE_REBATE)
    )
    * 10.0
    / DKK_PER_EUR
)
"""κ nettarif 電網關稅 [EUR/MWh_e] ≈ **8.50**。✅ **真值,不是佔位符**(2026-08-15)。

    (6.1 − 0.5) + 7.4 × 0.10 = 6.34 øre/kWh = 63.4 DKK/MWh_e ÷ 7.46 = 8.50 EUR/MWh_e

兩項減免對哥本哈根的大型電鍋爐**幾乎確定成立**:接在高壓層、年用電量遠超 100 GWh。
窗口內變動很小(Energinet 合計 2024 = 12.5、2025 = 13.5、2026 = 11.5 øre/kWh)→ 用單一常數。
**不含不該含的**:只有 Energinet 的輸電與系統費;TSO 接入的機組不付配電費,也沒有零售加成。

🔴 **為什麼不用 SØB25 Tabel 10 的 €25.2(188 DKK/MWh,>70,000 MWh 級距)—— 論文要交代**:
  ① **種類錯誤**:SØB §4.1 明文該章是**社會經濟價格**(samfundsøkonomiske priser),
     **不得用於企業經濟計算**(selskabsøkonomiske beregninger)。而我們的 LP 算的正是
     機組自身成本與 merit order = 企業經濟計算。SØB 的數字經 sunk cost 扣除、abonnement
     修正,並以 5 個半年的實績外推 —— 是為公共投資評估構造的量,不是任何一家廠實付的錢。
  ② **內容錯誤**:SØB §4.4 說明該表的合計加項含 **avance(零售加成)+ 配電費 + 輸電費**。
     TSO 接入的電鍋爐**配電費與零售加成都不付**,只付輸電 → 真值只有它的約三分之一。

📌 **回頭看**:先前用行為反推 τ+κ 得到 **+€25.5**,看似與 SØB 的 €25.3 吻合 ——
   那是巧合,而且**吻合本身該視為警訊而非佐證**。現在這個判斷有量化依據了。

🔴 **κ 不可能解釋 P2H 的時點錯誤**:2025 年 nettarif 仍以能源費形式收取
(øre/kWh,所有度數相同)、**不隨小時變動** → 它只改水準不改時點。
   實測 P2H 日總量 ρ(需求)=+0.335 vs 模型 −0.74 的落差**不在這裡** → 調頻收入那條線更孤立。

⚠️ **系統訂閱費 182 DKK/年/計量點是固定費,與用電量無關,不進邊際成本** —— 不要加。
⚠️ **2026 起的結構斷點**:Energinet 預計自 2026 年起,TSO 接入系統用戶的 nettarif 改以
   **容量費(DKK/MW)**收取 → nettarif 從邊際成本整個消失,只剩 systemtarif 0.74 øre/kWh,
   κ 掉到 **EUR 1/MWh 量級**。窗口若涵蓋 2026,論文要註明這個斷點。
"""

KAPPA_SENSITIVITY = {
    "無任何減免": 13.50,
    "僅 132/150 kV": 13.00,
    "僅 >100 GWh": 6.84,
    "兩項都適用(採用值)": 6.34,
    "再加限制網路接取協議": 3.34,
}
"""κ 的敏感度情境 [øre/kWh]。要掃就掃 **EUR 4.5 → 18**。"""

# ⚠️ **對稱性缺口(已知,不擋工作)**:CHP 那側也有生產端費率 ——
#    indfødningstarif 0.5 + balancetarif 0.65 øre/kWh,2025 年合計約 **EUR 1.5/MWh_e**,
#    該打在 `P⁺` 上。**目前式子裡沒有。** 量級小,但要對稱處理時這是 κ 的對應物。

# ══════════════════════════════════════════════════════════════════════
#  ② 垃圾焚化熱側稅楔 θ_h —— 區間已定、待敏感度確認
# ══════════════════════════════════════════════════════════════════════

WASTE_V_FORMEL = 1.20
"""v-formel:每 1 GJ_heat 歸屬 `1/1.20 = 0.833` GJ_fuel,其餘算在發電上(**發電免徵**)。"""
WASTE_EF_STATUTORY_T_PER_GJ = 0.0370
"""**配額涵蓋機組的法定備用排放係數 37.0 kg CO2/GJ_fuel**(2026-08-15 查證後改用)。

🔴 **稅法有三個級距,選錯級距比選錯數值嚴重**(Skat 法律指引 E.A.4.5.7.3):

| 情況                                   | 該用的係數              |
| -------------------------------------- | ----------------------- |
| **非**配額涵蓋機組                     | 28.34 kg/GJ(法定標準)  |
| **配額涵蓋**、知道自身實測係數         | **自身實測值**          |
| **配額涵蓋**、不知道自身實測係數       | **37.0 kg/GJ** ← 本模型 |
| 配額涵蓋、用煙囪法(skorstensmetoden)  | 直接量測                |

**ARC/ARGO 名目熱輸入遠超 20 MW → 2013-01-01 起就是配額涵蓋機組**
(Lov nr. 1353 af 21/12/2012)→ **28.34 那一列根本不適用於它們**。
舊值 0.02834 是套錯級距,2026-08-15 改為 0.0370。

🔴 **`STATUS.md` §9.2 引的「法定標準 0.070 tCO2/GJ」是抄錯的** —— 查證後那個 0.070
是 Skat **範例裡某座假想配額廠的「自身實測係數」**(原文 "verificeret emissionsfaktor
70 kg CO2/GJ"),**不是任何一個法定稅率**。§9.2b 那個衝突因此結案。

🔴 **仍不可用 `ef_affald = 42.5`** —— 那是能源署《Standardfaktorer for brændværdier
og CO2》的**物理**排放係數(總量 101.7 ton CO2/TJ × 非生物分解份額 41.79% = 42.50),
是排放清冊用的,與稅法的級距是**不同世界的數字**。
📌 順序值得記住:**稅法級距(28.34 / 37.0)都低於物理實測值(42.5)** —— 稅法的標準值
是協商出來的保守值,不是物理量。

⚠️ **理想值仍然是 ARC/ARGO 各自的實測係數,我們沒有。** 粗略交叉驗證:ARC 自己公布
煙囪年排 ≈ 560,000 t CO2、年處理量 ≈ 560,000–600,000 t 垃圾,套 DEA 的非生物份額
41.79% → 隱含化石係數約 **35 kg/GJ**,與 37.0 同量級(⚠️ 這是我用公開數字反推的,
不是 ARC 公布的係數,**不可引用**)。
⚠️ 配額涵蓋機組的供熱用 CO2 稅**可部分退還**(2025 為 10%)而這裡沒扣
→ **現行 θ_h 是上界**,方向對結論有利。
"""

WASTE_TAX_DKK_GJ = {
    #  年: (A 能源稅 affaldsvarmeafgift + tillægsafgift, B CO2 稅率 DKK/tCO2)
    2025: (28.8, 851.8),
    2026: (29.1, 860.3),
}
"""垃圾焚化熱側稅的**公布值**。A 直接按產出熱課(kr/GJ_heat,不用換算);
B 按每噸 CO2 課,要經 v-formel 與法定排放係數兩步換算到熱基準。

🔴 **2019–2024 沒有任何一個公布的垃圾熱稅率** —— PwC 是到 2025/2026 版才加上那幾列。
"""

WASTE_TAX_PROXY_DKK_GJ = {2021: 56.5, 2022: 56.7, 2024: 61.9}
"""⚠️ **代理值,非公布值,不可引用為稅率事實**(只能當量級參考)。

A 那一欄用 elpatronordningen 的**能源稅上限**當代理(它與垃圾熱稅在現行 kulafgiftsloven
稅率表裡共用同一個 2015 基準 24.1)。**這條代理線本身在 2020→2021 有對不上的斷點**
(回推基準 45.4 vs 49.8)。
"""


def waste_heat_tax_dkk_gj(year: int) -> float:
    """把公布的兩筆稅合成 θ_h [DKK/GJ_heat]。**重新推導,不抄結果。**

    A [kr/GJ_heat]  直接就是熱基準,不換算
    B [kr/GJ_heat] = 稅率[kr/tCO2] × 0.02834 [t/GJ_fuel] ÷ 1.20 [GJ_fuel/GJ_heat]
    """
    a, co2_rate = WASTE_TAX_DKK_GJ[year]
    return a + co2_rate * WASTE_EF_STATUTORY_T_PER_GJ / WASTE_V_FORMEL


def dkk_gj_to_eur_mwh_th(x: float) -> float:
    """DKK/GJ_heat → EUR/MWh_th(`× 3.6 GJ/MWh ÷ 匯率`)。"""
    return x * 3.6 / DKK_PER_EUR


THETA_HEAT_WASTE_LOW = dkk_gj_to_eur_mwh_th(waste_heat_tax_dkk_gj(2026))
"""θ_h **下界** ≈ **23.9** EUR/MWh_th(= 49.4 DKK/GJ_heat,2026 公布值)。"""

THETA_HEAT_WASTE_HIGH = 30.0
"""θ_h **上界** = 30.0 EUR/MWh_th(≈ 62 DKK/GJ_heat,2024 代理值,見 `WASTE_TAX_PROXY_DKK_GJ`)。"""

THETA_HEAT_WASTE = THETA_HEAT_WASTE_LOW
"""θ_h 垃圾焚化熱側稅楔 [EUR/MWh_th],掛在 **Qc** 上。**採用下界**,上界跑敏感度。

🔴 **為什麼不能只填 2026 的值**:綠色稅改(2025-01-01 生效)**同時動了兩筆、方向相反**:

    A 能源稅   2024 約 57  →  2025 = 28.8   (砍一半)
    B CO2 稅率 2024 = 196  →  2025 = 851.8  (四倍)

「CO2 稅四倍化」是真的,但 **A 原本比 B 大得多,砍半的絕對值蓋過四倍化的絕對值**
→ **淨效果向下**,所以 2025/2026 是全窗口的**最低點,不是代表值**。
⚠️ **不要把 2026 的值鋪滿 2021–2024**,那會系統性低估前四年。
"""

THETA_FUEL_GAS = 0.0
"""θ_f 燃料側國內碳稅 [EUR/tCO2],掛在 **F**(進 `ef` 括號內)。**維持 0,已由掃描排除。**

2026-08-14 的掃描結論(見 `STATUS.md` §9.4 測試 3):θ_f **不但沒把尖峰鍋爐的日內 ρ 推正**,
還讓它幾乎消失(佔熱 5.95% → 0.22%),**離實測的 5.21% 更遠**。
→ 查天然氣的逐年國內碳稅**不會修好時點問題**,這條分支已關閉。
⚠️ 副產品推論「實測 5.21% 本身是 DK2 尖峰鍋爐沒付大額國內碳稅的旁證」
   —— 建立在一個**時點已知是錯**的模型上,**不可引用**。

靠 `ef` 歸零自動切換,不需要 if:垃圾與生質 `ef_chp = 0` → 自動免疫;氣鍋爐 `ef_pb = 0.20` → 生效。
"""

PLACEHOLDERS: list[str] = []
"""✅ **2026-08-15 起清空**:τ / κ 已填真值,θ_h 有公布值與區間,θ_f 已由掃描排除。

仍然**不是「模型沒有假設」** —— 只是這四個外部參數不再是「我隨手設的 0」。
真正的不確定性移到別處了:θ_h 的 2021–2024 沒有公布值(用區間處理)、
`ef_chp` 對垃圾仍是量級值、`cop_from_temp` 的 70°C 供水溫仍是編的。
"""


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


def waste_fuel_price_eur_mwh(gate_fee_dkk_per_ton: float = PHI_GATE) -> float:
    """垃圾當燃料的價格 [EUR/MWh_fuel] —— **負值**(收錢燒垃圾)。

        −φ [DKK/ton] ÷ 熱值 [GJ/ton] × 3.6 [GJ/MWh] ÷ 匯率 [DKK/EUR]

    這是垃圾焚化廠在 merit order 裡永遠排最前面的原因:燃料成本為負,
    再貴的 O&M 都壓不過它。也是「prioriteret produktion」(優先生產)的經濟基礎。
    """
    dkk_per_gj = -gate_fee_dkk_per_ton / HEATING_VALUE_WASTE_GJ_PER_TON
    return dkk_per_gj * 3.6 / DKK_PER_EUR


def p2h_tariff_eur_mwh_e(dkk_per_mwh_e: float = 189.0) -> float:
    """soeB25 Tabel 10 的運輸成本換算 [EUR/MWh_e]。

    🔴 **2026-08-15:這個值已被否決,不可當 κ 用。** 保留只為了①論文要交代為什麼不用
    ②舊結果的對照。兩個獨立理由見 `KAPPA_NET` 的 docstring:
    ①**種類錯誤** —— SØB §4.1 明文那是社會經濟價格,不得用於企業經濟計算;
    ②**內容錯誤** —— 含 avance(零售加成)與配電費,而 TSO 接入的電鍋爐兩者都不付。

    真值是 `KAPPA_NET` ≈ 8.50(約為這個數的三分之一)。
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


# ══════════════════════════════════════════════════════════════════════
#  🟡 生質價的**假定值** —— 2026-08-15 使用者授權,為了讓機組先活過來
# ══════════════════════════════════════════════════════════════════════

BIOMASS_ASSUMED_EUR_MWH = {
    #  年: {燃料: (丹麥海關進口單價, 瑞典熱廠到廠價)}  [EUR/MWh_fuel]
    2021: {"wood_chips": (23.3, 18.9), "wood_pellets": (29.6, 31.9)},
    2022: {"wood_chips": (30.6, 19.6), "wood_pellets": (44.3, 33.1)},
    2023: {"wood_chips": (37.7, 26.3), "wood_pellets": (50.3, 41.5)},
    2024: {"wood_chips": (40.2, 32.2), "wood_pellets": (67.9, 48.8)},
    2025: {"wood_chips": (38.8, 34.0), "wood_pellets": (42.1, 46.1)},
}
"""🟡 **假定值,不是公布的燃料價** —— 2021–2024 讓 Amager/Avedøre 先跑起來用的。

**兩個數字都是從 `new_data/fuel/` 的原始資料算出來的**(`biomass_prices.py` 的
`demo()` 每次重算),不是編的。但**兩者的口徑都不完全對**,壞的方式相反:

| | 國家 | 商品 | 價格類型 |
| --- | --- | --- | --- |
| 丹麥海關(第一個數) | ✅ 對 | 🔴 錯 —— 巴西尤加利佔 21.5% 混在裡面 | 進口 CIF |
| 瑞典熱廠(第二個數) | 🔴 錯 —— 瑞典只佔丹麥木片進口 4.5% | ✅ 對 —— 林地木片 | **到廠採購價** |

🔴 **所以這裡存的是「區間的兩端」,不是「一個對的值」。**
`biomass_fuel_price_assumed()` 預設回丹麥那端,但**論文結論一定要掃兩端**
—— 這是本專案 2026-08-13 已經用過的做法(燃料價掃描證明時點結論在整個區間都成立)。
⚠️ 木片兩端在 **2022 差 56%**,而 2022 是能源危機年。

📌 **口徑真正正確的來源存在但被鎖著**:Dansk Fjernvarme《Brændselsprisstatistik》
(會員熱廠實際採購價)。**待辦:寫信要研究用途的存取權。** 見 `DATA.md` §8.5。
"""

ASSUMED: list[str] = ["BIOMASS_ASSUMED_EUR_MWH"]
"""**有值、但值是假定的**假設 —— 與 `PLACEHOLDERS`(值是 0)性質不同,所以分開列。

`warn_placeholders()` 每次跑都會把這串印出來。**這串不空,就代表模型的某個維度
是靠假定撐著的,結果不可以當真值引用。**
"""


def biomass_fuel_price_assumed(
    year: int, kind: str = "wood_chips", end: str = "dk"
) -> float:
    """🟡 生質燃料價,**2021–2024 回假定值**(而不是像下面那支一樣拋錯)。

    `end="dk"` 回丹麥海關那端、`end="se"` 回瑞典熱廠那端 —— **掃描時兩端都要跑**。
    2025 以後直接走 SØB25 的公布值(`biomass_fuel_price_eur_mwh`)。

    🔴 **這支存在的唯一理由是「先讓機組活過來」**(2026-08-15 使用者授權)。
    ⚠️ **要引用絕對水準的結論時不可以用它** —— 用它的結果一律要標明是假定值,
    而且要報兩端。真值的路徑見 `BIOMASS_ASSUMED_EUR_MWH` 的 docstring。

    ⚠️ **刻意跟 `biomass_fuel_price_eur_mwh()` 分開命名**:那支對 <2025 拋 `KeyError`
    的行為**保留不動**,因為它擋的是「有人偷偷用單一值回填」。呼叫端要用假定值,
    就得明確寫出這個函式名 —— **不會有人不小心拿到假定值**。
    """
    if year in BIOMASS_ASSUMED_EUR_MWH and kind in BIOMASS_ASSUMED_EUR_MWH[year]:
        dk, se = BIOMASS_ASSUMED_EUR_MWH[year][kind]
        return dk if end == "dk" else se
    return biomass_fuel_price_eur_mwh(year, kind)  # 落回公布值(或它的 KeyError)


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
    first = force or not _warned
    if zeroed and first:
        print(
            f"  ⚠️ 佔位符仍為 0(結果在這些維度上是「無此成本」的反事實):{', '.join(zeroed)}"
        )
    # 🟡 **有值但值是假定的** —— 與「值是 0」性質不同,一樣要每次叫出來
    if ASSUMED and first:
        print(
            f"  🟡 **假定值**(有值但不是公布真值,結果不可當水準引用):{', '.join(ASSUMED)}"
            "\n     生質價 2021–2024 用的是進口單價/瑞典到廠價當兩端 —— **結論要掃兩端**,"
            "真值待 Dansk Fjernvarme(見 DATA.md §8.5)"
        )
    if first:
        _warned = True
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

    # ── τ / κ:必須從公布費率**重新推導**,不是抄一個結果 ──────────────
    assert abs(TAU_EL - 8.0 / DKK_PER_EUR) < 1e-9, (
        "τ 必須等於 elpatronordningen 2021 上限換算"
    )
    assert (
        abs(ELPATRON_CAP_DKK_MWH[2020] / ELPATRON_CAP_DKK_MWH[2021] - 27.625) < 1e-6
    ), "2020/2021 的上限比例變了 —— 那是『窗口從 2021 起算』的理由之一,要重新確認"
    d2020 = (ELPATRON_CAP_DKK_MWH[2020] - ELPATRON_CAP_DKK_MWH[2021]) / DKK_PER_EUR
    print(
        f"  τ ok: elpatronordningen 上限 {ELPATRON_CAP_DKK_MWH[2021]:.1f} DKK/MWh_e ÷ {DKK_PER_EUR}"
        f" = **{TAU_EL:.2f} EUR/MWh_e**(2021–2026 常數)"
        f"\n     🔴 2020 年上限是 {ELPATRON_CAP_DKK_MWH[2020]:.0f} → 電鍋爐每 MWh_e 多付 EUR {d2020:.1f}"
        "  = 窗口從 2021 起算的第四個獨立理由"
    )
    want_k = ((6.1 - 0.5) + 7.4 * 0.10) * 10.0 / DKK_PER_EUR
    assert abs(KAPPA_NET - want_k) < 1e-9, (
        "κ 必須從 Energinet 的兩筆費率 + 兩項減免重算"
    )
    assert 4.4 < KAPPA_NET < 18.2, f"κ 應落在敏感度區間內:{KAPPA_NET:.2f}"
    assert KAPPA_NET < p2h_tariff_eur_mwh_e() / 2, (
        "κ 真值應該遠低於 SØB25 Tabel 10 的 25.2 —— 後者含配電費與零售加成"
    )
    print(
        f"  κ ok: (6.1−0.5) + 7.4×0.10 = 6.34 øre/kWh = **{KAPPA_NET:.2f} EUR/MWh_e**"
        f"\n     🔴 **不用** SØB25 Tabel 10 的 {p2h_tariff_eur_mwh_e():.1f}:那是社會經濟價格"
        "(SØB §4.1 明文不得用於企業經濟計算),且含配電費與零售加成"
    )
    # ── θ_h:兩筆稅要能從公布值合成,而且 2025/2026 必須是窗口低點 ────────
    for yr in WASTE_TAX_DKK_GJ:
        a, c = WASTE_TAX_DKK_GJ[yr]
        assert (
            abs(
                waste_heat_tax_dkk_gj(yr)
                - (a + c * WASTE_EF_STATUTORY_T_PER_GJ / WASTE_V_FORMEL)
            )
            < 1e-9
        )
    lo, hi = THETA_HEAT_WASTE_LOW, THETA_HEAT_WASTE_HIGH
    assert lo < hi, f"θ_h 下界應小於上界:{lo:.1f} vs {hi:.1f}"
    assert all(dkk_gj_to_eur_mwh_th(v) > lo for v in WASTE_TAX_PROXY_DKK_GJ.values()), (
        "2021–2024 的代理值應**全部高於** 2026 公布值 —— 綠色稅改的淨效果是稅負下降,"
        "所以 2025/2026 是窗口低點不是代表值"
    )
    # 🔴 排放係數的臨界值 —— 由「垃圾機組不再全開」的穿越點反推回 t/GJ_fuel。
    #    這一條是「重新推導不抄結果」:它把 §9.2b 那個衝突量化成一個會叫的數字。
    #    ⚠️ 穿越點是 **62–70 DKK/GJ 的區間**,不是單一的 73 ——
    #       73 是舊格點(30 與 35 之間空著)造成的假象,見 STATUS.md §9.4。
    #       這裡取**區間下緣 62**,assert 才是保守的。
    a26, c26 = WASTE_TAX_DKK_GJ[2026]
    ef_critical = (62.0 - a26) * WASTE_V_FORMEL / c26
    assert WASTE_EF_STATUTORY_T_PER_GJ < ef_critical, (
        f"採用的排放係數 {WASTE_EF_STATUTORY_T_PER_GJ} 已越過臨界值 {ef_critical:.4f}"
        " —— θ_h 會落在穿越點之上,STATUS.md §9.4 整節結論要重寫"
    )
    assert 0.02834 < ef_critical, (
        "非配額級距的 0.02834 也必須在臨界值之下,否則『級距選擇不影響結論』那句話要拿掉"
    )
    print(
        f"  θ_h ok: 2025 {waste_heat_tax_dkk_gj(2025):.1f} / 2026 {waste_heat_tax_dkk_gj(2026):.1f}"
        f" DKK/GJ_heat(A 能源稅 + B CO2稅×{WASTE_EF_STATUTORY_T_PER_GJ}÷{WASTE_V_FORMEL})"
        f"\n     → 採用 **{lo:.2f}** EUR/MWh_th(上界 {hi:.1f} 跑敏感度,已壓力測到 34)"
        f";2021–2024 只有代理值"
        f"({', '.join(f'{k}:{dkk_gj_to_eur_mwh_th(v):.1f}' for k, v in WASTE_TAX_PROXY_DKK_GJ.items())})"
        "\n     ⚠️ 代理值不可引用為稅率事實;**不要把 2026 的值鋪滿 2021–2024**"
        f"\n     ✅ 排放係數已結案(2026-08-15):用 **{WASTE_EF_STATUTORY_T_PER_GJ}**"
        " = 配額涵蓋機組的法定備用值(ARC/ARGO 是配額機組,28.34 那列不適用);"
        f"臨界值 **{ef_critical:.4f}**(穿越點下緣 62 反推)"
        "\n        §9.2 那個 0.070 查證為 Skat 範例裡某假想廠的自身實測值,**不是稅率**"
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
    assert not PLACEHOLDERS, (
        f"PLACEHOLDERS 應已清空(τ/κ 有真值、θ_h 有區間、θ_f 已排除),實得 {PLACEHOLDERS}"
    )
    print(
        "  佔位符 **0 個** —— 但這不等於「模型沒有假設」:θ_h 的 2021–2024 沒有公布值"
        "(用區間處理)、`ef_chp` 對垃圾仍是量級值、`cop_from_temp` 的 70°C 供水溫仍是編的"
    )


if __name__ == "__main__":
    print("=== 外部假設 ===")
    demo()
    print()
    warn_placeholders(force=True)
