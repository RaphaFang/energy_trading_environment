"""CHP + 區域供熱系統的排程 LP — 熱側 agent 的地基(對應電池線的 v1_single.perfect)。

一個 DH 業者:熱電共生機組(CHP)+ 蓄熱槽 + 電鍋爐 + 熱泵 + 尖峰鍋爐。
**熱需求必須每小時滿足**(義務,無彈性);電價是外生訊號;業者選怎麼配置。

為什麼是 LP:抽汽式 CHP 的可行域是**多邊形**(背壓線 + 容量線),蓄熱槽是線性動態,
所以整個問題是線性的。機組啟停(最小負載、啟動成本)才需要整數 —— **第一版刻意不做**,
先把「熱約束 × 電價」的經濟學跑出來。

**兩種機組型式都支援**(2026-08-11):
  抽汽式  P ≥ Cb·Q 且 P + Cv·Q ≤ P_max   → 可行域是一塊**面積**,熱電可互換 = 有彈性
  背壓式  P = Cb·Q(等式)                 → 可行域退化成一條**線**,熱電綁死 = 零彈性
差別在 `Plant.back_pressure`,而它在約束矩陣裡只改**一個界的值**,不是另開一套矩陣
(見 solve() 裡背壓線上界的說明)。目錄 33 張 CHP 表有 24 張是背壓式,
DK2 的垃圾焚化(佔供熱 27.7%)全部是 → 這不是邊角案例。

決策(每小時):
  P_chp  CHP 發電 (MW_e)        Q_chp  CHP 產熱 (MW_th)
  Q_eb   電鍋爐產熱 (MW_th)      Q_hp   熱泵產熱 (MW_th)      ← 這兩個是 power-to-heat,吃電
  Q_pb   尖峰鍋爐產熱 (MW_th)    ch/dis 蓄熱槽充/放 (MW_th)   S 蓄熱量 (MWh_th)

技術關係(見 Technology Catalogue):
  燃料 F = (P_chp + Cv·Q_chp) / η_el      抽汽式:多產 1 MW_th 熱要少發 Cv MW_e 電
  背壓線 P_chp ≥ Cb·Q_chp                  給定熱量下的最低發電量
  容量線 P_chp + Cv·Q_chp ≤ P_max          等效凝汽容量
  電鍋爐 Q_eb = η_eb·買電                  熱泵 Q_hp = COP·買電(COP 隨氣溫變,見下)

**核心經濟學**:CHP 的電力邊際成本不是燃料成本,而是「燃料成本 − 熱的機會價值」。
熱反正要產,若不用 CHP 產就得用鍋爐燒錢 → CHP 發電的增量成本可能很低甚至為負。
蓄熱槽讓業者選**何時**產熱 → 等於把電力供給曲線在時間上搬移。
電價為負時,電鍋爐/熱泵反過來吃電產熱 → 這是 power-to-heat 吸收負電價的機制。

✅ **技術參數已是 DEA Technology Catalogue 真值**(2026-08-07,經 `heat/dea.py`)。
仍不是目錄值的兩類:①**排放因子**(目錄沒有,是燃料屬性,見 ARCHETYPES)②**容量與熱網
規模的對齊**(目錄給的是單一機組典型值)。

用法:python new_src/heat/chp.py    (self-check + 真實 DK1 電價的示範排程)
"""

import os
import sys
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

sys.path.insert(0, os.path.dirname(__file__))


@dataclass
class Plant:
    """一個 DH 系統的技術與成本參數。

    **預設值 = DEA Technology Catalogue 的木片抽汽式機組**
    (`09a Wood Chips extract. plant`, year=2020, est=ctrl),2026-08-07 從佔位值換掉。
    要別的燃料或敏感度區間用 `dea_plant()`,不要手改這裡。

    佔位值錯得最離譜的是 `cb`:原本猜 0.75,目錄真值 0.45(木片)/0.59(顆粒)/
    0.84(煤)/1.80(氣 CC)—— **不只高估一倍,而且真值隨技術差 4 倍**,不存在一個
    「通用 Cb」。cb 是背壓線斜率 → 直接決定給定熱量下機組能少發多少電 = 彈性大小。

    ⚠️ **容量欄位(p_max/eb_max/hp_max/pb_max/s_max/s_rate)是目錄的「單一機組典型值」**,
    不是熱網的實際裝置量。真實 DH 系統是多台機組併聯,而且機組尺寸要跟熱需求規模對齊。
    這些值與熱需求的匹配問題**尚未解決**(見 STATUS.md §7 第 5 點)。
    """

    p_max: float = 258.2  # [TC] CHP 等效凝汽容量 MW_e(單一機組)
    cb: float = 0.45  # [TC] 背壓係數(抽汽式=功熱比下界;背壓式=功熱比本身)
    cv: float = 0.14  # [TC] 抽汽損失係數:每產 1MW_th 熱少發 0.14MW_e 電
    # 🔑 **背壓式**:熱電綁死在 P = Cb·Q 一條線上,沒有可行域面積 → 完全沒有熱電彈性。
    # 目錄 33 張 CHP 表裡 **24 張是背壓式**,而 DK2 的垃圾焚化(佔供熱 27.7%)全部是。
    # 設 True 時 `solve()` 會把背壓線的上界從 p_max 收成 0(見約束區的說明),
    # 並且**必須同時 cv=0**(目錄的 Cv=1.0 是哨兵值不是物理量)—— `dea` 會一起設好。
    back_pressure: bool = False
    # [TC] 電效率(net, **name plate**)。2026-08-10 從 0.409(annual average)改過來:
    # 目錄的 Cb 是用 name plate 算的(16 張背壓表全中,見 dea.demo() 的基準 self-check),
    # 而 Cb/Cv/eta_el 同在一組可行域與燃料式裡 → 基準必須一致。舊值是既有 bug。
    # ⚠️ 代價:name plate 是設計點效率、LP 又沒建停機與最小負載 → **系統性樂觀**。
    #    可量化的補償見 dea.availability()(木片 0.914 / 氣 CC 0.927 / 煤 0.950),
    #    但**本模型目前沒有套用它**。
    eta_el: float = 0.430
    # [TC] 最小負載(佔滿載比例)。**預設不生效** —— 只有 `solve(committed=True)` 會用。
    # 目錄值:垃圾 0.20 / 木片 0.45 / 顆粒 0.15 / 氣 CC 0.40 / 煤 0.15 / 秸稈 0.40。
    # 🔴 為什麼是它而不是爬坡率:爬坡率換算到每小時全部 ≥1 倍滿載(見 dea.ramp_per_hour),
    #    逐時 LP 加爬坡是白做的。最小負載才是「機組降不下來」的真正來源。
    min_load: float = 0.45
    # 排放因子 tCO2/MWh_fuel,**熱電機組與尖峰鍋爐分開設**(2026-08-06 拆開)。
    # 原本共用一個 ef=0.20 → 對生質機組課了不存在的碳成本,系統性高估 CHP 成本、
    # 低估 CHP 競爭力,進而**高估 power-to-heat 的價值**。量級參考 heat/fuelmix.py:
    # DK1 2025 出力加權隱含 ef ≈ 0.149(生質 32.8% / 煤 27.8% / 氣 23.7% / 廢棄物 13.2%)。
    # 單一機組應該用**單一燃料**的值,不是隊伍平均——見 ARCHETYPES。
    ef_chp: float = 0.0  # 生質(EU ETS 零碳);目錄裡沒有排放因子,見 ARCHETYPES
    ef_pb: float = 0.20  # 尖峰鍋爐(丹麥常見天然氣或輕油)
    eb_max: float = 20.0  # [TC] 電鍋爐熱容量 MW_th(41 Electric boiler, large,單台)
    eta_eb: float = 0.99  # [TC] 電鍋爐效率
    hp_max: float = 10.0  # [TC] 熱泵熱容量 MW_th(40 Comp. hp, airsource 10 MW,單台)
    cop_ref: float = 2.8  # [TC] 熱泵 COP 參考值(@ 7°C);隨氣溫變,見 cop_from_temp
    # 尖峰鍋爐**刻意不用目錄值**:'44 Natural Gas DH Only' 的單台容量只有 5.25 MW_th,
    # 拿它當 pb_max 會讓 LP 在寒冬直接無解。這個變數在模型裡的角色是**可行性後備**
    # (真實熱網一定有足夠備援鍋爐,只是台數多),不是某一台機組的銘牌值。
    pb_max: float = 1e4
    eta_pb: float = 1.03  # [TC] 尖峰鍋爐效率(>1 是因為目錄以低位發熱值 LHV 計)
    # 變動 O&M。**目錄對 CHP 記在 EUR/MWh_e、對純熱機組記在 EUR/MWh_h**(不是我選的記帳方式)
    # → CHP 沒有「每 MWh_th」的項,`vom_th` 留 0。成本函數靠參數歸零吸收,不分支。
    vom_e: float = 2.765  # [TC] CHP 每 MWh_e 的變動 O&M
    vom_th: float = 0.0  # CHP 每 MWh_th 的變動 O&M —— 目錄不這樣記,固定 0
    vom_eb: float = 0.84  # [TC] 電鍋爐 每 MWh_th
    vom_hp: float = 0.86  # [TC] 熱泵 每 MWh_th
    vom_pb: float = 1.17  # [TC] 尖峰鍋爐 每 MWh_th
    s_max: float = 2880.0  # [TC] 蓄熱槽容量 MWh_th(141b Large TTES)
    s_rate: float = 288.0  # [TC] 蓄熱槽充/放速率 MW_th
    s_loss: float = 0.0025  # [TC] 每小時散熱損失比例(目錄給 %/day ÷ 24)


# 依燃料別的**排放因子** tCO2/MWh_fuel。**目錄裡沒有這個**(排放是燃料屬性不是技術
# 屬性)→ 這三個仍是量級值,不是目錄真值。一台機組燒一種燃料,所以要用該燃料的值,
# 不能用 heat/fuelmix.py 的隊伍加權平均(那是虛構的「平均機組」)。
# ⚠️ 燃料**價格**不在這裡(它隨時間變,由 solve(fuel_price=) 傳入)。
ARCHETYPES = {
    "gas": dict(ef_chp=0.20, ef_pb=0.20),  # 天然氣熱電 + 天然氣尖峰鍋爐
    "biomass": dict(ef_chp=0.0, ef_pb=0.20),  # 生質熱電(EU ETS 零碳)+ 天然氣尖峰鍋爐
    "coal": dict(ef_chp=0.34, ef_pb=0.20),  # 燃煤熱電;DK1 2025 仍佔 27.8%
    # 垃圾焚化:**燃料價是負的**(收處理費),用 assumptions.waste_fuel_price_eur_mwh()。
    # ⚠️ 排放因子仍是量級值。✅ **與 φ 重複計入的疑慮 2026-08-14 起消失**:
    #    稅已拆成 θ_f(掛燃料)與 θ_h(掛熱),而 φ 掛燃料 → 不同變數,不會靜默抵消。
    #    🔴 `ef_chp=0` 讓垃圾**自動免除 θ_f**,稅全部由 θ_h 承擔 —— 這是刻意的,見 assumptions。
    # ✅ 2026-08-11 起可跑:目錄的 WtE 全是背壓式,而 `solve()` 已支援(back_pressure=True)。
    "waste": dict(ef_chp=0.0, ef_pb=0.20),
}

# DEA 技術原型 → 燃料別(決定排放因子)。鍵對應 dea.CHP_ARCHETYPES。
_ARCH_FUEL = {
    "wood_chips": "biomass",
    "wood_pellets": "biomass",
    "gas_cc": "gas",
    "coal": "coal",
    # 背壓式(2026-08-11 起支援)。垃圾的燃料價是**負的**,見 assumptions。
    "waste": "waste",
    "waste_medium": "waste",
    "straw": "biomass",
}


def dea_plant(arch: str = "wood_chips", est: str = "ctrl", **over) -> Plant:
    """直接從 Technology Catalogue 建一個 Plant(技術參數全是目錄真值)。

    `est='lower'/'upper'` 就是目錄自帶的區間 → **敏感度分析不用另外設計情境**。
    `**over` 覆寫個別欄位(例如把容量對齊到熱網規模)。

    `pb_max` 一律保留 Plant 的可行性後備值,不用目錄的單台 5.25 MW_th(理由見上)。
    排放因子來自 ARCHETYPES,不是目錄。
    """
    import dea  # 延後匯入:chp.py 不該因為缺 new_data/DEA_data 就 import 失敗

    ws = {**dea.CHP_ARCHETYPES, **dea.BP_ARCHETYPES}[arch]
    p = dea.plant_params(ws, est=est)
    p.pop("pb_max")  # 一律用 Plant 的可行性後備值,理由見 pb_max 的註解
    # 🔴 目錄沒有 ctrl 中央估計的欄位會是 None(2026-08-11 起,舊版偷填 lower/upper 中點)。
    #    **不沿用 Plant 的預設值**、也不自己編 —— 逼呼叫端明確給,因為這些幾乎都是容量,
    #    而容量是業主的設計選擇,直接決定這個 agent 在市場上有多大(= 本論文的主題)。
    missing = [k for k, v in p.items() if v is None and k not in over]
    if missing:
        raise dea.NoCentralEstimate(
            f"原型 {arch!r}({ws})的 {missing} 在目錄裡**沒有 ctrl "
            f"中央估計**,只有 lower/upper。請明確傳入,例如 dea_plant({arch!r}, "
            f"{missing[0]}=...),並在呼叫端註明依據(真實機組容量 > 目錄區間端點 > 猜)。"
        )
    p = {k: v for k, v in p.items() if v is not None}
    return Plant(**{**p, **ARCHETYPES[_ARCH_FUEL[arch]], **over})


def dk2_plant(key: str, **over) -> Plant:
    """從 `dk2_fleet` 的真實機組建一個 `Plant`(2026-08-14 新增)。

    先前 ARC/ARGO 的結果都是臨時腳本跑的,沒有進 repo → 每次要重建、而且無法防迴歸。

    只支援 `dk2_fleet.runnable()` 裡的機組(目前 ARC / ARGO):
      · 熱容量 `mw_th` 用 varmelast 真值(熱網營運者自己講的,對 MW_th 是最高權威)
      · 電容量用 `dk2_fleet.derived_mw_e()` 從 `P_max = Cb·Q_max` 反推(**只對背壓式成立**)
      · 其餘技術參數走 DEA 的 `waste` 原型

    ⚠️ 這是**單機組**,不是整個熱網:餵它 DK2 全系統熱需求會讓尖峰鍋爐扛掉絕大部分。
    """
    import dk2_fleet as F

    v = F.FLEET[key]
    if v.get("blocked_by"):
        raise ValueError(f"{key} 目前跑不了:{v['blocked_by']}")
    assert v["fuel"] == "waste", (
        f"dk2_plant 目前只支援垃圾背壓機組,{key} 是 {v['fuel']}"
    )
    cb = dea_plant("waste", p_max=1.0).cb
    return dea_plant("waste", p_max=F.derived_mw_e(key, cb), **over)


def cop_from_temp(temp, cop_ref: float = None, t_ref: float = 7.0) -> np.ndarray:
    """熱泵 COP 隨外氣溫下降 —— **這是熱側的關鍵物理耦合**。

    天冷時熱需求最高,但熱泵效率最低 → 彈性在最需要的時候最貴。這正是
    [[heat-chp-track]] 核心假說「相關的熱義務侵蝕稀缺時的彈性」的物理來源之一。
    用簡化的 Carnot 比例式:COP ∝ T_hot/(T_hot − T_cold),供水溫固定 70°C。

    🔴 `cop_ref=None` → 取 `Plant.cop_ref`(目錄值 2.8),**故意不寫死數字**。
    2026-08-10 修:這裡原本硬寫預設 3.2,而 `Plant.cop_ref` 是目錄的 2.8;
    所有呼叫端都是裸呼叫 `cop_from_temp(temp)` → **實跑的 COP 全期比機組自己的
    目錄值高 14.3%、熱泵買電低估 12.5%**,而且方向正好**高估 power-to-heat**
    (C3 章的主題)。改成從 Plant 取值,基準就不可能再漂掉。
    ⚠️ `t_hot=70°C` 仍是我編的佔位值,不是 CTR/VEKS 的實際供水溫(見 README §⑤)。
    """
    if cop_ref is None:
        cop_ref = Plant.cop_ref  # 單一來源:dataclass 的欄位預設值
    t = np.asarray(temp, float)
    t_hot = 70.0 + 273.15
    carnot = t_hot / np.maximum(t_hot - (t + 273.15), 1.0)
    carnot_ref = t_hot / (t_hot - (t_ref + 273.15))
    return cop_ref * carnot / carnot_ref


def _cost_coeffs(
    pl, p, fp, fpb, cp, c_hp, tau=0.0, kappa=0.0, theta_f=0.0, theta_h=0.0
) -> dict:
    """**整個模型的成本函數就是這裡的一條式子**,涵蓋全部機組,靠參數歸零切換。

        c = (p_fuel + ef·(p_CO2 + θ_f))·F + θ_h·Q
            + vom_e·P⁺ + vom_th·Q  −  p_el·P  +  (τ+κ)·P⁻

    🔴 **2026-08-14:原本單一個 θ 拆成兩個,而且其中一個換了變數。**
    舊式是 `(p_fuel + ef·p_CO2 + θ)·F`(θ 未被 ef 乘,量綱其實是 EUR/MWh_fuel,
    與 `assumptions` 註記的 EUR/tCO2 不一致 —— 只因為值是 0 才沒炸)。現在:

      θ_f  EUR/tCO2   掛 **F**,進 ef 括號內   → 天然氣(靠 ef_pb=0.20 生效)
      θ_h  EUR/MWh_th 掛 **Q**(只掛 Qc)      → 垃圾焚化(三項丹麥國內稅全部按熱計徵)

    **θ_h 只掛 Qc,不掛 Qpb/Qe/Qh**:它是垃圾焚化機組自己的熱側稅,
    尖峰鍋爐與 power-to-heat 不適用(那些走 θ_f 或不課)。
    完整的法源與「為什麼掛錯變數不能靠掃描救」寫在 `assumptions.THETA_HEAT_WASTE`。

    回傳 {變數區塊: 逐時成本係數}。**刻意不為機組類型開分支** —— 生質/垃圾/電鍋爐/熱泵
    的差別全部表現成參數,而不是 if。

    P⁺/P⁻ 不需要在 LP 裡用 max():**賣電與買電本來就是不同的變數區塊**,每塊的電力方向
    是建模時已知的常數 `el`,所以 `max(−el, 0)` 在建矩陣時就算掉了,問題仍是線性的。

        區塊   fuel_per_out   el(正=賣/負=買)   vom       說明
        P      1/η_el         +1                vom_e     CHP 發電
        Qc     cv/η_el         0                vom_th    CHP 抽汽產熱(目錄不這樣記 → 0)
        Qe     0              −1/η_eb           vom_eb    電鍋爐:買電產熱
        Qh     0              −1/COP_t          vom_hp    熱泵:同上,但 el 隨氣溫變
        Qpb    1/η_pb          0                vom_pb    尖峰鍋爐:燒燃料不發電

    燃料別怎麼靠參數切換(不是靠 if):
      · 生質 CHP     ef_chp = 0 → θ_f 自動失效;θ_h = 0;P⁻ 恆為 0(沒有買電的區塊)
      · 垃圾 CHP     `fuel_price` 傳**負值**(= −φ 處理費換算);ef_chp = 0 → **θ_f 自動失效**;
                     稅由 **θ_h 掛在 Qc** 上
      · 尖峰燃氣鍋爐 ef_pb = 0.20 → **θ_f 自動生效**;θ_h 不適用
      · 電鍋爐/熱泵  fuel_per_out = 0 → 燃料項整條消失;el < 0 → (τ+κ) 才生效

    🔑 **θ_f 同時傳給 CHP 與尖峰鍋爐是對的,不需要分支** —— 它被 `ef` 乘,
       而 `ef_chp`/`ef_pb` 本來就分開設,所以「誰付這筆稅」由排放因子自己決定。
    """

    def coeff(fuel_price, ef, fuel_per_out, el, vom, th_heat=0.0):
        el = np.asarray(el, float)
        return (
            # 燃料 + (ETS 碳價 + 國內燃料碳稅 θ_f);θ_f 靠 ef 歸零自動切換
            (fuel_price + ef * (cp + theta_f)) * fuel_per_out
            + th_heat  # θ_h 熱側稅楔:掛在**熱出力**上,不是燃料
            + vom  # 變動 O&M
            - p * el  # 賣電收入(el<0 時自動變成買電支出)
            + (tau + kappa) * np.maximum(-el, 0.0)  # 只有買電才付的稅費與網費
        )

    one = np.ones_like(p)
    return {
        "P": coeff(fp, pl.ef_chp, 1.0 / pl.eta_el, one, pl.vom_e),
        # 🔴 θ_h 只掛這裡:垃圾焚化三稅按**交付/產出的熱**計徵
        "Qc": coeff(fp, pl.ef_chp, pl.cv / pl.eta_el, 0.0 * one, pl.vom_th, theta_h),
        "Qe": coeff(0.0, 0.0, 0.0, -one / pl.eta_eb, pl.vom_eb),
        "Qh": coeff(0.0, 0.0, 0.0, -one / c_hp, pl.vom_hp),
        "Qpb": coeff(fpb, pl.ef_pb, 1.0 / pl.eta_pb, 0.0 * one, pl.vom_pb),
    }


def solve(
    price,
    heat_demand,
    plant: Plant = None,
    fuel_price=30.0,
    co2_price=70.0,
    fuel_price_pb=None,
    cop=None,
    s_init: float = 0.0,
    tau: float = None,
    kappa: float = None,
    theta_f: float = None,
    theta_h: float = None,
    committed: bool = False,
):
    """解一段期間的最適排程。回傳 dict:各項出力陣列 + 利潤(€)。

    price        逐時電價 €/MWh_e
    heat_demand  逐時熱需求 MW_th(必須滿足,等式約束)
    fuel_price   CHP 燃料價 €/MWh_fuel(純量或逐時);fuel_price_pb 預設同 CHP
    cop          熱泵 COP(純量或逐時);None → 用 plant.cop_ref

    tau/kappa        電力稅、網路關稅 [EUR/MWh_e],掛在**買電**上。
    theta_f          燃料側國內碳稅 [EUR/tCO2],掛在 **F**(進 ef 括號內)。
    theta_h          垃圾焚化熱側稅楔 [EUR/MWh_th],掛在 **Qc**。
                     四個都是 None → 用 assumptions.py 的佔位值(全 0)。
                     要測「網路關稅是不是 P2H 之謎的答案」就傳
                     `kappa=assumptions.p2h_tariff_eur_mwh_e()`。
    ⚠️ 2026-08-14 起舊的單一 `theta=` 參數已移除(它掛在 F 上,而垃圾三稅按熱計徵)。
       **刻意不留相容別名** —— 留了會讓舊呼叫端默默套用錯的變數。

    committed    機組**持續併聯運轉**(供熱季的常態)→ 啟用最小負載下界。
                 🔑 嚴格的最小負載是「不是關機,就是 ≥ min_load」= 需要整數變數。
                 但**在機組不關機的前提下它是純線性的一條下界**,問題仍是 LP:

                     P + Cv·Qc ≥ min_load · P_max        (與容量線同一個「負載」定義)

                 為什麼要有它:`validate.py`(2026-08-12)量到 LP 在**每一個維度**
                 都對價格過度反應(電鍋爐日總量 ρ 實測 −0.25 vs LP −0.79),
                 而缺最小負載正是最可能的來源 —— 沒有下界的機組可以在便宜的小時
                 完全讓位給電鍋爐,真實機組降不下來。
                 ⚠️ **只在供熱季成立**:夏天機組會真的停機,強制下界會讓熱平衡無解
                 (熱需求是等式,沒有棄熱)。`solve()` 會在無解時把這件事講清楚。

    蓄熱槽預設從空的開始(s_init=0)且不加期末條件:因為 S≥0 與動態式已保證
    「放出來的必定先充進去」,不會憑空生熱,所以不需要期末歸零(對照電池線的週窗歸零)。
    """
    import assumptions as A

    A.warn_placeholders()  # 每個 process 印一次:哪些成本被歸零了
    tau = A.TAU_EL if tau is None else tau
    kappa = A.KAPPA_NET if kappa is None else kappa
    theta_f = A.THETA_FUEL_GAS if theta_f is None else theta_f
    theta_h = A.THETA_HEAT_WASTE if theta_h is None else theta_h
    pl = plant or Plant()
    p = np.asarray(price, float)
    d = np.asarray(heat_demand, float)
    T = len(p)
    assert len(d) == T, f"價格 {T} 與熱需求 {len(d)} 長度不一致"
    fp = (
        np.full(T, fuel_price, float)
        if np.isscalar(fuel_price)
        else np.asarray(fuel_price, float)
    )
    fpb = (
        fp
        if fuel_price_pb is None
        else (
            np.full(T, fuel_price_pb, float)
            if np.isscalar(fuel_price_pb)
            else np.asarray(fuel_price_pb, float)
        )
    )
    c_hp = np.full(T, pl.cop_ref, float) if cop is None else np.asarray(cop, float)
    # 碳價可以是純量或逐時陣列(接真實 EUA 價用)
    cp = (
        np.full(T, co2_price, float)
        if np.isscalar(co2_price)
        else np.asarray(co2_price, float)
    )

    # 變數區塊:P, Qc, Qe, Qh, Qpb, ch, dis, S  → 8 個長度 T 的區塊
    nb = 8
    n = nb * T
    sl = {
        k: slice(i * T, (i + 1) * T)
        for i, k in enumerate(["P", "Qc", "Qe", "Qh", "Qpb", "ch", "dis", "S"])
    }

    c = np.zeros(n)
    coeffs = _cost_coeffs(pl, p, fp, fpb, cp, c_hp, tau, kappa, theta_f, theta_h)
    for k, v in coeffs.items():
        c[sl[k]] = v

    I = sp.eye(T, format="csr")  # noqa: E741 — 單位矩陣,數學慣例就叫 I
    Z = sp.csr_matrix((T, T))

    # 等式①熱平衡:Qc + Qe + Qh + Qpb + dis − ch = 熱需求
    heat = sp.hstack([Z, I, I, I, I, -I, I, Z], format="csr")
    # 等式②蓄熱槽動態:S_t − (1−loss)·S_{t−1} − ch_t + dis_t = 0(t=0 用 s_init)
    shift = sp.diags([np.ones(T - 1)], [-1], shape=(T, T), format="csr")
    D = I - (1 - pl.s_loss) * shift
    stor = sp.hstack([Z, Z, Z, Z, Z, -I, I, D], format="csr")
    b_stor = np.zeros(T)
    b_stor[0] = (1 - pl.s_loss) * s_init
    A_eq = sp.vstack([heat, stor], format="csr")
    b_eq = np.concatenate([d, b_stor])

    # 不等式①背壓線下界:Cb·Qc − P ≤ 0    ②容量線:P + Cv·Qc ≤ P_max
    #           ③背壓線**上界**:P − Cb·Qc ≤ slack   ← 這一條決定機組是哪一種
    #
    # 🔑 **背壓式 vs 抽汽式在這裡是一個「界」不是一個 if**:
    #   抽汽式  slack = p_max → ③ 恆成立(因為 P ≤ p_max 且 Cb·Qc ≥ 0)= 不綁,
    #           剩下 ① 與 ②,可行域是一塊**面積**(P 可以高於背壓線,多餘蒸汽去凝汽發電)
    #   背壓式  slack = 0     → ③ 變成 P ≤ Cb·Qc,與 ① 的 P ≥ Cb·Qc 夾成
    #           **等式 P = Cb·Qc**,可行域退化成**一條線**,熱電完全綁死
    # 這樣約束矩陣的**結構完全相同**,只有 b 向量的一個值不同 → 不必為機組類型分支。
    # ⚠️ 背壓式還必須 `cv=0`:目錄的 Cv=1.0 是「此欄不適用」的哨兵值不是物理量,
    #    照抄會讓容量線變成 P + Qc ≤ p_max(憑空多出一條不存在的限制)。dea 已處理。
    bp_lo = sp.hstack([-I, pl.cb * I, Z, Z, Z, Z, Z, Z], format="csr")
    cap = sp.hstack([I, pl.cv * I, Z, Z, Z, Z, Z, Z], format="csr")
    bp_hi = sp.hstack([I, -pl.cb * I, Z, Z, Z, Z, Z, Z], format="csr")
    slack = 0.0 if pl.back_pressure else pl.p_max
    blocks, rhs = (
        [bp_lo, cap, bp_hi],
        [
            np.zeros(T),
            np.full(T, pl.p_max),
            np.full(T, slack),
        ],
    )
    # ④ 最小負載下界(只有 committed=True):−(P + Cv·Qc) ≤ −min_load·P_max。
    #    刻意用**容量線的同一個「負載」定義** P + Cv·Qc,而不是只綁 P ——
    #    那樣抽汽機組只要多抽汽就能規避下界,等於沒綁。背壓式 Cv=0 時它自動退化成
    #    P ≥ min_load·P_max,而 P = Cb·Qc 又把熱一起綁住 → **同一條式子,不分支**。
    if committed:
        blocks.append(sp.hstack([-I, -pl.cv * I, Z, Z, Z, Z, Z, Z], format="csr"))
        rhs.append(np.full(T, -pl.min_load * pl.p_max))
    A_ub = sp.vstack(blocks, format="csr")
    b_ub = np.concatenate(rhs)

    hi = {
        "P": pl.p_max,
        "Qc": None,
        "Qe": pl.eb_max,
        "Qh": pl.hp_max,
        "Qpb": pl.pb_max,
        "ch": pl.s_rate,
        "dis": pl.s_rate,
        "S": pl.s_max,
    }
    bounds = [(0.0, hi[k]) for k in sl for _ in range(T)]

    r = linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs"
    )
    # 無解時最常見的原因是 committed=True 撞上夏天的低熱需求 → 明講,不要讓人猜
    assert r.status == 0, f"LP 失敗:{r.message}" + (
        f"\n  🔴 committed=True 時最小負載下界是 {pl.min_load:.2f}×{pl.p_max:.0f} = "
        f"{pl.min_load * pl.p_max:.0f} MW_e,對應的熱出力可能已經超過這段期間的"
        f"最低熱需求({d.min():.0f} MW_th)—— **夏天機組是真的會停機的**,"
        "那時候這個線性近似不成立,請只在供熱季用 committed=True。"
        if committed
        else ""
    )
    x = r.x
    out = {k: x[s] for k, s in sl.items()}
    out["p_buy"] = out["Qe"] / pl.eta_eb + out["Qh"] / c_hp  # power-to-heat 的買電量
    out["p_net"] = out["P"] - out["p_buy"]  # 對電網的淨部位(正=賣)
    out["fuel"] = (out["P"] + pl.cv * out["Qc"]) / pl.eta_el
    # ⚠️ 這是**電力市場淨收益,未計熱收入**(賣電 − 燃料 − 買電)。熱在本模型是義務不是商品。
    # 通常為負:業者燒燃料是為了供熱,電只是副產品 → 負值不是模型錯。
    out["el_net"] = float(-r.fun)
    # 這才是可比、可解讀的指標:單位供熱的淨成本(扣掉賣電收入後)。
    # DH 業者實際追蹤的就是它,也是熱費率的基礎。熱需求外生固定 → 熱收入是常數,
    # 不影響最適排程,所以把它排除在最佳化外是對的。
    out["heat_cost_per_mwh"] = float(-out["el_net"] / max(d.sum(), 1e-9))
    out["cop"] = c_hp
    return out


def demo() -> None:
    pl = Plant()
    T = 48
    # 兩天:每天前 12 小時便宜(含負價)、後 12 小時貴
    p = np.tile(np.r_[np.full(12, -20.0), np.full(12, 120.0)], 2)
    d = np.full(T, 200.0)  # 固定熱需求 200 MW_th

    r = solve(p, d, pl)
    # ① 熱平衡必須完全滿足(這是義務,不是目標)
    bal = r["Qc"] + r["Qe"] + r["Qh"] + r["Qpb"] + r["dis"] - r["ch"]
    assert np.allclose(bal, d, atol=1e-6), "熱平衡未滿足"
    # ② 可行域:背壓線與容量線都不得違反
    assert (r["P"] + 1e-6 >= pl.cb * r["Qc"]).all(), "違反背壓線"
    assert (r["P"] + pl.cv * r["Qc"] <= pl.p_max + 1e-6).all(), "違反容量線"
    assert (r["S"] >= -1e-6).all() and (r["S"] <= pl.s_max + 1e-6).all(), "蓄熱量超界"
    # ③ 負電價時段應該用 power-to-heat 吃電(這是 C3 的機制)
    cheap, exp = p < 0, p > 0
    assert r["p_buy"][cheap].sum() > 10 * r["p_buy"][exp].sum() + 1, (
        f"負電價時應大量 power-to-heat,得便宜時段買 {r['p_buy'][cheap].sum():.0f} MWh"
    )
    # ④ 高電價時段 CHP 應該發電、便宜時段應該少發
    assert r["P"][exp].mean() > r["P"][cheap].mean(), "高價時段應多發電"
    print(
        f"  CHP LP ok: 熱平衡滿足、可行域守住;負價時買電 {r['p_buy'][cheap].sum():,.0f} MWh_e"
        f"、高價時 CHP 均 {r['P'][exp].mean():.0f} MW_e(低價 {r['P'][cheap].mean():.0f})"
    )

    # ⑤ 蓄熱槽是**彈性**:容量越大利潤不可能變差(單調性,守住模型沒寫反)
    small = solve(p, d, Plant(s_max=0.0, s_rate=0.0))["el_net"]
    big = solve(p, d, Plant(s_max=6000.0, s_rate=600.0))["el_net"]
    assert big >= r["el_net"] - 1e-6 >= small - 1e-6, (
        f"蓄熱槽越大淨收益應不減:0槽 {small:.0f} / 預設 {r['el_net']:.0f} / 大槽 {big:.0f}"
    )
    print(
        f"  蓄熱槽 ok: 無槽 €{small:,.0f} ≤ 預設 €{r['el_net']:,.0f} ≤ 大槽 €{big:,.0f}(彈性有價)"
    )

    # ⑥ 熱泵 COP 隨氣溫下降(冷天彈性更貴 —— 核心假說的物理來源)
    cold, mild = cop_from_temp(-10.0), cop_from_temp(10.0)
    assert cold < mild, f"冷天 COP 應較低,得 {cold:.2f} vs {mild:.2f}"
    # **基準一致性**:參考溫度下的 COP 必須等於機組自己的 cop_ref,否則 LP 的熱泵
    # 用的是 A 機組的效率、成本卻按 B 機組算(2026-08-10 修掉的 3.2 vs 2.8 就是這個)。
    assert abs(float(cop_from_temp(7.0)) - pl.cop_ref) < 1e-9, (
        f"COP 基準漂掉:cop_from_temp(t_ref) = {float(cop_from_temp(7.0)):.3f} "
        f"≠ Plant.cop_ref = {pl.cop_ref}"
    )
    print(
        f"  COP ok: −10°C {cold:.2f} < +10°C {mild:.2f}(冷天熱泵最不划算,而那時熱需求最高);"
        f"參考點 == 目錄 cop_ref {pl.cop_ref}"
    )

    # ⑥a **背壓式**:熱電必須綁死成一條線,而且不能因此變得更好賺
    bp = dea_plant("waste", p_max=70.0) if os.path.exists("new_data/DEA_data") else None
    if bp is not None:
        import assumptions as A

        wfuel = A.waste_fuel_price_eur_mwh()  # 負值:收處理費燒垃圾
        rb = solve(p, d, bp, fuel_price=wfuel, fuel_price_pb=30.0, co2_price=70.0)
        # (i) P = Cb·Q 逐時成立(不只是 ≥)—— 這就是背壓式的定義
        assert np.allclose(rb["P"], bp.cb * rb["Qc"], atol=1e-6), (
            f"背壓式必須 P = Cb·Q,最大偏差 {np.abs(rb['P'] - bp.cb * rb['Qc']).max():.4f}"
        )
        # (ii) 熱電比恆定 → **零熱電彈性**:不管電價高低,想多發電只能多產熱
        act = rb["Qc"] > 1e-6
        ratio = rb["P"][act] / rb["Qc"][act]
        assert ratio.std() < 1e-9, f"背壓式的功熱比應為常數,得 std={ratio.std():.2e}"
        # (iii) **只**放寬背壓線上界(cv 保持 0,成本係數完全不變)→ 可行域是嚴格超集
        #       → 淨收益不可能變差。這一條驗的是「背壓 = 少一個自由度」而不是別的副作用。
        #       ⚠️ 不要同時改 cv:那會一起改動成本與容量線,就不是純粹的放寬了。
        ext = solve(
            p,
            d,
            dea_plant("waste", p_max=70.0, back_pressure=False),
            fuel_price=wfuel,
            fuel_price_pb=30.0,
            co2_price=70.0,
        )
        assert ext["el_net"] >= rb["el_net"] - 1e-6, (
            f"放寬成抽汽式後淨收益不該變差:背壓 {rb['el_net']:.0f} vs 抽汽 {ext['el_net']:.0f}"
        )
        print(
            f"  背壓式 ok: P=Cb·Q 逐時成立、功熱比恆為 {ratio.mean():.3f}(零熱電彈性);"
            f"放寬成抽汽式淨收益 €{rb['el_net']:,.0f} → €{ext['el_net']:,.0f}"
            f"(+€{ext['el_net'] - rb['el_net']:,.0f} = 抽汽彈性的價值)"
        )

    # ⑥c **最小負載**:committed=True 是**純粹收緊可行域**(只改一個旗標,別的都不動)
    #     → 淨收益不可能變好,而且下界必須真的綁住(否則這個約束等於沒加)。
    rc = solve(p, d, pl, committed=True)
    load = rc["P"] + pl.cv * rc["Qc"]
    floor = pl.min_load * pl.p_max
    assert (load >= floor - 1e-6).all(), (
        f"最小負載下界沒守住:最低負載 {load.min():.2f} < {floor:.2f} MW_e"
    )
    assert rc["el_net"] <= r["el_net"] + 1e-6, (
        f"收緊可行域後淨收益不該變好:自由 {r['el_net']:.0f} vs 最小負載 {rc['el_net']:.0f}"
    )
    # 而且它要真的綁到 —— 若從沒觸底,這條約束在這個情境下是裝飾品
    assert (load <= floor + 1e-3).any(), (
        f"最小負載從未綁住(最低負載 {load.min():.2f} vs 下界 {floor:.2f})"
        " —— 這個 self-check 就沒有在驗任何東西了"
    )
    print(
        f"  最小負載 ok: 下界 {pl.min_load:.2f}×{pl.p_max:.0f}={floor:.0f} MW_e 逐時守住且"
        f"有 {(load <= floor + 1e-3).mean():.0%} 的小時綁在底部;"
        f"淨收益 €{r['el_net']:,.0f} → €{rc['el_net']:,.0f}(收緊可行域的代價)"
    )
    # 爬坡率在逐時解析度下不綁 —— 重新推導一次,免得日後有人白做一個爬坡約束
    if os.path.exists("new_data/DEA_data"):
        import dea

        rp = {a: dea.ramp_per_hour(ws) for a, ws in dea.BP_ARCHETYPES.items()}
        rp |= {a: dea.ramp_per_hour(ws) for a, ws in dea.CHP_ARCHETYPES.items()}
        assert min(rp.values()) >= 1.0, (
            f"若有原型的每小時爬坡 <1 倍滿載就要重新考慮:{rp}"
        )
        print(
            f"  爬坡 ok: 每小時爬坡全部 ≥1 倍滿載({min(rp.values()):.1f}–{max(rp.values()):.1f})"
            " → **逐時 LP 加爬坡約束是白做的**,真正綁的是最小負載"
        )

    # ⑥b **重構等價性**:新的單一式子在「vom 全 0 + 三個佔位符全 0」時,必須逐項還原
    #     2026-08-11 之前那五行手寫的成本係數。這鎖住的是「合併成一條式子」沒有改到經濟學,
    #     之後的水準變化就只能來自 vom 與稅費,不會是重構的副作用。
    T2 = 24
    p2 = np.linspace(-30.0, 150.0, T2)
    fp2, cp2, cop2 = 28.0, 65.0, np.linspace(2.0, 3.5, T2)
    z = Plant(vom_e=0.0, vom_th=0.0, vom_eb=0.0, vom_hp=0.0, vom_pb=0.0)
    cf = fp2 + cp2 * z.ef_chp
    legacy = {
        "P": -p2 + cf / z.eta_el,
        "Qc": np.full(T2, cf * z.cv / z.eta_el),
        "Qe": p2 / z.eta_eb,
        "Qh": p2 / cop2,
        "Qpb": np.full(T2, (fp2 + cp2 * z.ef_pb) / z.eta_pb),
    }
    got = _cost_coeffs(
        z, p2, np.full(T2, fp2), np.full(T2, fp2), np.full(T2, cp2), cop2
    )
    for k, want_v in legacy.items():
        assert np.allclose(got[k], want_v, atol=1e-9), (
            f"成本函數重構改變了 {k} 的係數:{got[k][:3]} vs 舊 {want_v[:3]}"
        )
    print("  成本函數 ok: 單一式子在 vom=0、稅費=0 時逐項還原重構前的五行係數")

    # ⑥d 🔴 **θ 拆成 θ_f / θ_h 的接線檢查**(2026-08-14)。三件事要鎖住:
    #     ① 兩個都 0 時逐格等同(零變更 —— 這是「測試 1」)
    #     ② θ_f 掛 F 且**被 ef 乘** → 垃圾/生質(ef_chp=0)自動免疫,氣鍋爐(ef_pb>0)會被課
    #     ③ θ_h 掛 **Qc**,只影響 Qc,而且**不隨 ef 變**(它不是碳稅是熱側稅楔)
    base = _cost_coeffs(
        z, p2, np.full(T2, fp2), np.full(T2, fp2), np.full(T2, cp2), cop2
    )
    zero = _cost_coeffs(
        z,
        p2,
        np.full(T2, fp2),
        np.full(T2, fp2),
        np.full(T2, cp2),
        cop2,
        theta_f=0.0,
        theta_h=0.0,
    )
    for k in base:
        assert np.allclose(base[k], zero[k], atol=1e-12), f"θ 全 0 時 {k} 應逐格不變"
    # θ_h:只動 Qc,而且剛好加上去(量綱 EUR/MWh_th,不經過任何效率或 ef)
    th = _cost_coeffs(
        z, p2, np.full(T2, fp2), np.full(T2, fp2), np.full(T2, cp2), cop2, theta_h=7.0
    )
    assert np.allclose(th["Qc"] - base["Qc"], 7.0, atol=1e-12), (
        f"θ_h 應原樣加在 Qc 上:實得 {(th['Qc'] - base['Qc'])[:3]}"
    )
    for k in ("P", "Qe", "Qh", "Qpb"):
        assert np.allclose(th[k], base[k], atol=1e-12), (
            f"θ_h 不該碰 {k} —— 垃圾熱側稅只對焚化機組的熱出力課徵"
        )
    # θ_f:靠 ef 歸零切換。z 是木片(ef_chp=0)→ P/Qc 必須完全不動;ef_pb=0.20 → Qpb 必須動
    tf = _cost_coeffs(
        z, p2, np.full(T2, fp2), np.full(T2, fp2), np.full(T2, cp2), cop2, theta_f=100.0
    )
    assert z.ef_chp == 0.0 and z.ef_pb > 0.0, (
        "這個 self-check 預設 z 是生質 CHP + 氣鍋爐"
    )
    for k in ("P", "Qc"):
        assert np.allclose(tf[k], base[k], atol=1e-12), (
            f"ef_chp=0 的機組不該被 θ_f 課到({k}) —— 若動了表示 θ_f 沒進 ef 括號內"
        )
    want_pb = 100.0 * z.ef_pb / z.eta_pb
    assert np.allclose(tf["Qpb"] - base["Qpb"], want_pb, atol=1e-9), (
        f"θ_f 對氣鍋爐應是 θ_f·ef_pb/η_pb = {want_pb:.3f},實得 {(tf['Qpb'] - base['Qpb'])[0]:.3f}"
    )
    print(
        f"  θ 接線 ok: θ_f 掛 F 且被 ef 乘(ef=0 的機組自動免疫、氣鍋爐 +{want_pb:.2f} EUR/MWh_th)、"
        "θ_h 原樣掛 Qc 且不碰其他區塊;兩者皆 0 時逐格等同重構前"
    )

    # ⑦ Plant 的預設值必須真的等於目錄值 —— 上面那些數字是手抄的,這行防止它們默默漂掉。
    #    用**相對**容差 1e-3:上面的字面值是為了可讀性四捨五入過的(例如 vom_e 2.765
    #    對目錄的 2.76476…),但真正要抓的漂移都遠大於這個量級(eta_el 那次是 5%)。
    if os.path.exists("new_data/DEA_data"):
        want = dea_plant("wood_chips", p_max=Plant.p_max)
        drift = {
            f: (getattr(pl, f), getattr(want, f))
            for f in pl.__dataclass_fields__
            if not np.isclose(getattr(pl, f), getattr(want, f), rtol=1e-3, atol=1e-9)
        }
        assert not drift, f"Plant 預設值與 DEA 目錄不一致(手抄漂掉了):{drift}"
        # 背壓係數隨技術差 4 倍 → 不存在「通用 Cb」,原本猜 0.75 高估木片近一倍
        # ⚠️ gas_cc 目錄沒有 ctrl 容量 → 必須明確給,否則 dea_plant 會擋(見 dea.get)
        cbs = {a: dea_plant(a, p_max=1.0).cb for a in _ARCH_FUEL}
        assert max(cbs.values()) / min(cbs.values()) > 3, f"Cb 應隨技術大幅變動:{cbs}"
        print(
            "  DEA ok: Plant 預設 == 目錄木片抽汽值;各原型 Cb = "
            + ", ".join(f"{a} {v:.2f}" for a, v in cbs.items())
        )


def _real_demo() -> None:
    """用真實 DK1 電價 + 度日熱需求跑一個月,看行為合不合理。

    **原型與燃料價必須配對**:燒天然氣的機組要配 TTF、燒煤的要配 API2。
    生質(木片/顆粒)**沒有燃料價來源**(無國際期貨,需丹麥能源署統計)→ 目前無法跑,
    硬拿天然氣價代打會讓成本水準完全失真(曾跑出負的單位供熱成本)。
    """
    import duckdb
    from demand import heat_demand

    if not os.path.exists("new_data/energy.duckdb"):
        print("  (跳過:找不到 energy.duckdb)")
        return
    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, temperature_2m AS temp, "
        "ttf_gas_eur_mwh AS gas, api2_coal_eur_mwh AS coal, eua_co2_eur_t AS co2 "
        "FROM training WHERE area='DK1' "
        "AND y_price_eur IS NOT NULL AND temperature_2m IS NOT NULL "
        "AND timestamp_utc >= TIMESTAMP '2024-01-01' AND timestamp_utc < TIMESTAMP '2024-02-01' "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    # 熱需求:用全期校準的度日代理,取這個月;再縮到單一 DH 系統的規模(佔 DK1 的 8%)
    q = heat_demand(d["temp"].to_numpy()) * 0.08
    # cop_ref 不傳 → 取 Plant.cop_ref(目錄值,唯一來源;demo() 的 ⑥ 會擋住漂移)
    cop = cop_from_temp(d["temp"].to_numpy())
    gas = d["gas"].ffill().bfill().to_numpy()
    co2 = d["co2"].ffill().bfill().to_numpy()  # 真實 EUA(2026-08-07 起全期覆蓋)
    # 原型 → (燃料價, 要跑的 p_max)。
    # 🔴 **氣 CC 目錄沒有 ctrl 容量**(只有 lower=100 / upper=500,5 倍區間)→ 舊版偷填中點
    #    300 並被當成「目錄真值」引用。現在**兩端都跑**,讓讀者看到結論有多依賴這個選擇。
    #    煤有 ctrl 容量(500),只跑一個。
    fuels = {
        "gas_cc": (gas, [100.0, 500.0]),
        "coal": (d["coal"].ffill().bfill().to_numpy(), [500.0]),
    }
    r = solve(
        d["price"].to_numpy(),
        q,
        dea_plant("gas_cc", p_max=100.0),  # 下界;上界的結果見下方表格
        fuel_price=gas,
        co2_price=co2,
        cop=cop,
    )

    p = d["price"].to_numpy()
    neg = p < 0
    print(f"\n=== 真實 DK1 2024-01(單一 DH 系統,{len(d)} 小時)===")
    print(
        f"  熱需求 {q.mean():.0f} MW_th 均值(尖峰 {q.max():.0f}),氣溫 {d['temp'].mean():.1f}°C"
    )
    print(
        f"  CHP 發電均 {r['P'].mean():.0f} MW_e,尖峰鍋爐佔熱量 {r['Qpb'].sum() / q.sum():.0%}"
    )
    print(
        f"  power-to-heat 買電 {r['p_buy'].sum():,.0f} MWh_e"
        f"(其中負電價時段 {r['p_buy'][neg].sum():,.0f},佔 {r['p_buy'][neg].sum() / max(r['p_buy'].sum(), 1e-9):.0%})"
    )
    print(
        f"  負電價時數 {neg.mean():.1%};蓄熱槽平均 {r['S'].mean():.0f}/{Plant().s_max:.0f} MWh_th"
    )
    print(
        f"  電力市場淨收益 €{r['el_net']:,.0f}(未計熱收入 → 負值正常:燒燃料是為了供熱)"
    )
    hi, lo = p > np.percentile(p, 75), p < np.percentile(p, 25)
    print(
        f"  CHP 發電:高價四分位 {r['P'][hi].mean():.0f} MW_e vs 低價四分位 {r['P'][lo].mean():.0f} MW_e"
        "  ← 熱約束下仍跟著價格走 = 蓄熱槽在搬移熱的生產時點"
    )
    # 燃料價有真值的兩個原型並排(碳價已是真實 EUA)。生質缺價,故意不列。
    print("\n  單位供熱淨成本(原型 × 對應燃料價 × 真實 EUA):")
    for a, (fp, pmaxes) in fuels.items():
        for pm in pmaxes:
            # 尖峰鍋爐一律燒天然氣(見 ARCHETYPES 的 ef_pb)→ 煤機組也要用氣價當 pb 燃料
            pl = dea_plant(a, p_max=pm)
            rr = solve(
                d["price"].to_numpy(),
                q,
                pl,
                fuel_price=fp,
                fuel_price_pb=gas,
                co2_price=co2,
                cop=cop,
            )
            src = "目錄無 ctrl" if len(pmaxes) > 1 else "目錄 ctrl"
            print(
                f"    {a:8} p_max={pm:5.0f} MW_e ({src:11}) 燃料均 €{fp.mean():5.1f} → "
                f"**€{rr['heat_cost_per_mwh']:7.1f}/MWh_th**"
                f"(CHP 均 {rr['P'].mean():5.0f} MW_e,機組/熱網 = {pm / q.mean():.1f}×)"
            )
    print("    biomass  ✗ 無燃料價來源(木片/顆粒無國際期貨)→ 目前跑不了,不是模型問題")


if __name__ == "__main__":
    demo()
    _real_demo()
