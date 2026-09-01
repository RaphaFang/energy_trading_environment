"""階段 1–3 的 agent 規格 —— **HOFOR Amagerværket(AMV1 + AMV4)**。

━━━ 這一支存在的理由 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

交易線從階段 1 起需要一個**具體的實體**。2026-08-30 定案:**鎖定哥本哈根**,
agent = HOFOR 的 Amagerværket。這一支把它的參數從既有來源**組裝**起來並驗證,
**不新抓任何資料** —— 每一格都指得出來源,分成 [實測]/[官方]/[目錄]/[假定]/[缺]。

━━━ 為什麼是 AMV(選擇準則,不是一眼挑的)━━━━━━━━━━━━━━━━━━━━━━━━

Storkøbenhavns Fjernvarme 上「有電也有熱」的機組群組共 15 個,同時滿足
①可調度 CHP ②**有蓄熱槽** ③在 varmelast 涵蓋的熱網上 的**只有三個**:

    Ørsted Avedøre   805.6 MW_e / 936.5 MW_th   蓄熱 44,000 m³
    HOFOR Amager     214.0 MW_e / 651.0 MW_th   蓄熱 20,000 m³   ← 選這個
    VEKS Solrød        3.0 MW_e /   3.7 MW_th   蓄熱    500 m³   (太小,排除)

🔑 **選 AMV 而不是 Avedøre 的理由不是規模,是階 5/6**:那兩階需要**同一個業者**同時有
CHP 與 P2H(電>熱),HOFOR 有(300 MW 熱泵在規劃中),**Ørsted 沒有** —— 走到階 5 就得換
業者,「同一個 agent 一路走到底」的乾淨歸因會斷掉。
📌 而且使用者先前已拍板「階段 3 用泛稱、參數取自 HOFOR」,這是延續那個決定。

━━━ 🔴 一個還沒解決的建模問題(這支只負責標出來,不替使用者決定)━━━━━━━

**varmelast 沒有 AMV 自己的逐時熱交付序列** —— 生產側只有 `BE-VL-KRAFTV-EF`
(全部熱電機組合計),拆不到廠。所以「agent 的熱義務」必須從兩種問法擇一:

    (甲) 熱是**義務**:給 agent 一條逐時熱交付曲線,它只能沿 PQ 可行域選運轉點
    (乙) 熱有**外生價格** λ_heat:agent 對熱也是 price taker,自己決定發多少熱

⚪ (乙) 看起來跟論文框架一致(price taker、無對手模型),λ_heat 也有現成來源
   (`heat/joint_dispatch.py` 的對偶值)。

🔴🔴 **但這一支跑出來的數字對 (乙) 很不利**:AMV 的銘牌熱容量 651 MW_th
   **等於 `room` 中位數(597)的 109%** —— 它一台就能吃下整個可調度熱需求。
   **AMV 在電力側是 price taker(214 MW_e 之於 DK2),在熱側不是。**
   → 假裝它面對一個外生的 λ_heat,等於假裝它對自己造成的價格沒有影響,那正是
     電池線 λ 那條路上已經吃過的虧。而且哥本哈根的熱根本不是市場:**Varmelast 是集中調度**。
   → **(甲) 才是誠實的**:熱義務外生給定,agent 只在 PQ 可行域上選運轉點。
   ⚠️ 這是量出來的傾向,**不是替使用者拍板** —— 決定權仍在使用者。

用法:python new_src/trading/agent_spec.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "new_src"))

DATA = ROOT / "new_data"
OUT = ROOT / "figs" / "trading"

AGENT = "HOFOR Energiproduktion — Amagerværket"
NETWORK = "Storkøbenhavns Fjernvarme"
COMPANY = "HOFOR ENERGIPRODUKTION A/S"

# 蓄熱槽:**兩個獨立來源**,下面的 self-check 會用水的比熱把它們對起來。
#   (V) varmelast/dk2_fleet:1,000 MWh、±300 MW_th
#   (E) EPT 廠級 `varmeakkumuleringstank_m3`:20,000 m³
ACC_MWH, ACC_MW, ACC_M3 = 1000.0, 300.0, 20000.0
CP_WATER_MJ_KG_K = 4.186          # 水的比熱
RHO_WATER_KG_M3 = 1000.0

# 燃料:兩台燒的**不是同一種生質**(見 [[biomass-fuel-price]] —— 混為一談會出錯)
FUEL_OF = {"AMV1": "wood_pellets", "AMV4": "wood_chips"}


def load_units() -> pd.DataFrame:
    """AMV 逐台的**實測**效率(EPT 生產檔是機組級,每年每台一列)。

    🔑 η 是**量出來的**不是目錄值:eta = 產出 ÷ `brutto_TJ`(實際燃料投入)。
    ⚠️ `eta_tot > 1` 正常 —— 煙氣冷凝在低熱值(LHV)基準下本來就會超過 1。
    """
    p = pd.read_parquet(DATA / "ept/ept_produktion_2023_2025.parquet")
    m = p[(p.selskab_navn == COMPANY) & (p.brutto_TJ.fillna(0) > 0)].copy()
    m["eta_el"] = m.elprod_TJ / m.brutto_TJ
    m["eta_th"] = m.varmeprod_TJ / m.brutto_TJ
    m["eta_tot"] = m.eta_el + m.eta_th
    m["e_h"] = m.elprod_TJ / m.varmelev_TJ          # 實測電熱比
    m["fuel"] = m.anlaeg_navn.map(FUEL_OF)
    cols = ["aar", "anlaeg_navn", "fuel", "elkapacitet_MW", "varmekapacitet_MW",
            "brutto_TJ", "eta_el", "eta_th", "eta_tot", "e_h"]
    return m[cols].sort_values(["anlaeg_navn", "aar"]).reset_index(drop=True)


def load_heat_demand() -> pd.DataFrame:
    """熱網的逐時需求 —— **消費欄**(CTR + VEKS),不是生產欄。

    🔴 生產欄含蓄熱充放與調度結果,拿它當 LP 輸入是循環論證(DATA.md §9)。
    🔴 `validate.load_dk2()` 已在分析層擋掉 2024-04-01 那 39 小時的量測中斷
       (兩個消費欄同時恰好為 0),這裡直接沿用,**不要自己重寫判準**。

    回傳的三個熱欄位:
        `dem`      CTR+VEKS 消費側總需求
        `mustrun`  必發(垃圾焚化)
        `room`     `dem − mustrun` = **可調度機組搶得到的那塊**  ← 階 1/2 的熱義務上界
    """
    from heat.validate import load_dk2
    d = load_dk2()
    return d.set_index("timestamp").sort_index()


def spec() -> dict:
    """把規格組起來。每一格都帶來源標記。"""
    u = load_units()
    last = u[u.aar == u.aar.max()]
    from heat.chp import dea_plant          # 目錄值 Cb / Cv 的唯一一份
    from heat.assumptions import biomass_fuel_price_eur_mwh

    tc = dea_plant("wood_chips")
    y = int(u.aar.max())
    return {
        "units": u,
        "nameplate_el_MW": float(last.elkapacitet_MW.sum()),
        "nameplate_th_MW": float(last.varmekapacitet_MW.sum()),
        "cb": tc.cb,
        "cv": tc.cv,
        "acc_mwh": ACC_MWH,
        "acc_mw": ACC_MW,
        "fuel_eur_mwh": {k: biomass_fuel_price_eur_mwh(y, k)
                         for k in ("wood_chips", "wood_pellets")},
        "year": y,
    }


# ─────────────────────────── self-check ───────────────────────────

def selfcheck(s: dict, heat: pd.DataFrame) -> None:
    u = s["units"]

    # ① 兩台都在,而且三年都有實測
    got = sorted(u.anlaeg_navn.unique())
    assert got == ["AMV1", "AMV4"], f"預期 AMV1+AMV4,實際 {got}"
    assert u.groupby("anlaeg_navn").aar.nunique().min() == 3, "有機組不足三年實測"

    # ② 🔑 蓄熱槽的兩個獨立來源要對得起來。
    #    20,000 m³ 的水要存 1,000 MWh,需要的溫差 ΔT = E / (V·ρ·cp)。
    #    區域供熱的供/回溫差典型在 30–60 K —— 落在裡面,兩個來源就互相驗證了。
    dt_k = ACC_MWH * 3600 / (ACC_M3 * RHO_WATER_KG_M3 * CP_WATER_MJ_KG_K / 1000)
    assert 30 <= dt_k <= 60, (
        f"蓄熱槽兩個來源對不起來:{ACC_M3:,.0f} m³ 要存 {ACC_MWH:,.0f} MWh "
        f"需要 ΔT={dt_k:.1f} K,不在區域供熱的 30–60 K 範圍內"
    )

    # ③ 實測效率的合理範圍(eta_tot > 1 是煙氣冷凝,但不該離譜)
    assert u.eta_el.between(0.10, 0.45).all(), "eta_el 超出合理範圍"
    assert u.eta_tot.between(0.85, 1.20).all(), "eta_tot 超出合理範圍(煙氣冷凝上限)"

    # ④ 🔴 銘牌電熱比 vs 實測電熱比:抽汽機不會貼著銘牌跑,但也不該差一倍
    for n, g in u.groupby("anlaeg_navn"):
        plate = g.elkapacitet_MW.iloc[0] / g.varmekapacitet_MW.iloc[0]
        meas = g.e_h.mean()
        assert 0.4 < meas / plate < 1.6, (
            f"{n}: 銘牌電熱比 {plate:.3f} vs 實測 {meas:.3f} —— 差太多,先查燃料欄"
        )

    # ⑤ 熱需求要涵蓋交易線的乾淨制度窗口(2025-12-08 起),否則階 1/2 沒得跑
    lo, hi = heat.index.min(), heat.index.max()
    need = pd.Timestamp("2025-12-08", tz=heat.index.tz)
    assert lo < need < hi, f"熱需求 {lo:%Y-%m-%d}→{hi:%Y-%m-%d} 沒蓋到乾淨窗口"

    # ⑥ 熱需求不該有 0(量測中斷已在 validate.load_dk2 擋掉,這裡確認擋乾淨了)
    assert (heat["dem"] > 50).all(), (
        f"熱需求出現 ≤50 MW_th 的格 {(heat['dem'] <= 50).sum()} 個 —— 量測中斷沒擋乾淨")

    # ⑦ 🔑 `room` 會是負的 —— 而且那**不是壞資料,是夏天的物理**:
    #    垃圾焚化必發,夏天光它一個就超過傳輸網的熱需求(5.6% 的小時)。
    #    所以判準不是「room 不可以是負的」,而是「負的必須集中在夏天」。
    #    散在冬天才代表 mustrun 欄接錯了。
    neg = heat[heat["room"] < 0]
    summer = neg.index.month.isin([5, 6, 7, 8, 9]).mean() if len(neg) else 1.0
    assert summer > 0.95, (
        f"room 為負的小時只有 {100 * summer:.1f}% 落在 5–9 月 —— "
        "散到冬天代表 mustrun(垃圾)欄接錯了,不是季節現象")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = spec()
    heat = load_heat_demand()
    selfcheck(s, heat)

    u = s["units"]
    print(f"\n═══ agent 規格:{AGENT} ═══")
    print(f"熱網 {NETWORK}(varmelast 調度的那張網)\n")
    print("── 機組(EPT 機組級,η 為實測)──")
    print(u.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\n銘牌合計 {s['nameplate_el_MW']:.0f} MW_e / {s['nameplate_th_MW']:.0f} MW_th")
    print(f"蓄熱槽 {s['acc_mwh']:,.0f} MWh、±{s['acc_mw']:.0f} MW_th "
          f"(EPT {ACC_M3:,.0f} m³ ⇒ ΔT {ACC_MWH * 3600 / (ACC_M3 * RHO_WATER_KG_M3 * CP_WATER_MJ_KG_K / 1000):.0f} K,兩來源一致)")
    print(f"PQ 可行域 Cb={s['cb']} / Cv={s['cv']} [目錄 DEA 木片抽汽式]")
    print(f"燃料價 {s['year']}:木片 €{s['fuel_eur_mwh']['wood_chips']:.1f} / "
          f"木顆粒 €{s['fuel_eur_mwh']['wood_pellets']:.1f} /MWh_fuel  🟡 假定值")
    print(f"熱需求 {heat.index.min():%Y-%m-%d} → {heat.index.max():%Y-%m-%d}、"
          f"{len(heat):,} 列(CTR+VEKS 消費側)")
    print(f"  總需求 dem  中位 {heat['dem'].median():.0f} / 冬季尖峰 {heat['dem'].max():.0f} MW_th")
    print(f"  必發 mustrun 中位 {heat['mustrun'].median():.0f} MW_th(垃圾焚化)")
    neg = heat[heat["room"] < 0]
    print(f"  🔑 room = dem − mustrun 中位 {heat['room'].median():.0f} MW_th"
          f" ← 可調度機組搶得到的那塊;AMV 銘牌 {s['nameplate_th_MW']:.0f} MW_th "
          f"= 其 {100 * s['nameplate_th_MW'] / heat['room'].median():.0f}%")
    print(f"  🔴 room < 0 的小時 {len(neg):,}({100 * len(neg) / len(heat):.1f}%),"
          f"其中 {100 * neg.index.month.isin([5, 6, 7, 8, 9]).mean():.1f}% 在 5–9 月"
          f"(7 月佔 {100 * (neg.index.month == 7).mean():.0f}%)"
          " ← **夏天垃圾必發就吃掉全部需求,AMV 沒有熱可賣**")

    print("\n── 來源分級 ──")
    for tag, items in {
        "[實測] 逐台 η_el/η_th/電熱比": "EPT 生產檔 2023–2025(機組級)",
        "[官方] 銘牌容量": "EPT 機組級主檔(🔴 廠級的 elkapacitet 不可靠,DATA.md §10.2)",
        "[官方] 蓄熱槽": "varmelast(1,000 MWh/300 MW)× EPT(20,000 m³),兩者互驗",
        "[官方] 逐時熱需求": "varmelast CTR+VEKS 消費欄(2021– 全期完整)",
        "[目錄] Cb / Cv": "DEA Technology Catalogue 木片抽汽式 → heat/chp.dea_plant",
        "🟡[假定] 生質燃料價": "assumptions.BIOMASS_ASSUMED_EUR_MWH(真值仍缺)",
        "🔴[缺] AMV 自己的逐時熱交付": "varmelast 只有全部熱電機組合計,拆不到廠",
        "🔴[缺] 抽汽 Cv 的實測值": "只有目錄值;背壓 Cb 有實測母體,Cv 沒有",
    }.items():
        print(f"  {tag:<32} {items}")

    p = OUT / "agent_spec_amv.csv"
    u.to_csv(p, index=False)
    print(f"\n✓ 寫出 {p}")


if __name__ == "__main__":
    main()
