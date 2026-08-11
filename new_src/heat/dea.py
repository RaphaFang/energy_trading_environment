"""從丹麥能源署 Technology Catalogue 讀出真實機組參數,取代 chp.Plant 的佔位值。

資料:`new_data/DEA_data/`(使用者 2026-08-07 下載)
  - `DEA_electricity_and_district_heating.csv` 15,581 列 / 74 個技術工作表
  - `DEA_energy_storage.csv` 3,181 列 / 17 個工作表(含 TTES 蓄熱槽、PTES 季節性儲熱)

格式是長表(tidy),關鍵欄位:
  ws         技術工作表(例:'09a Wood Chips, Large 50 degree')
  par        參數名(例:'Cb coefficient (50°C/100°C)')
  est        **ctrl / lower / upper** ← 這欄讓敏感度分析變成免費的
  year       2015/2020/2025/2030/2035/2040/2050
  val, unit  值與單位

⚠️ 目錄裡**沒有** CO2 排放因子(那是燃料屬性,不是技術屬性)→ `ef_chp`/`ef_pb` 仍需別的來源。
⚠️ 容量是「單一機組」的典型值。真實熱網有多台機組且大小不一 → 拿目錄容量當 `p_max`
   只是「典型機組」,若熱需求規模沒跟著對齊,仍會有機組/熱網尺寸不匹配的問題。

用法:python new_src/heat/dea.py            (列出可用技術 + 示範建一個 Plant)
"""

import os
import sys
from functools import lru_cache

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

DIR = "new_data/DEA_data"
TECH = f"{DIR}/DEA_electricity_and_district_heating.csv"
STORE = f"{DIR}/DEA_energy_storage.csv"
YEAR = 2020  # 研究期間 2019–2025;目錄格點是 2015/2020/2030/2050,取 2020 最貼近
# (lower/upper 只有 2020 與 2050 兩個年份,所以 2020 是唯一三種估計都齊的年份)


class NoCentralEstimate(KeyError):
    """目錄對這個參數只給 lower/upper,**沒有 ctrl 中央估計**。

    這不是資料缺漏,通常是因為該參數(尤其是**容量**)是業主的設計選擇而非技術屬性。
    刻意做成 `KeyError` 的子類別:既能被既有的 `except KeyError` 接住,又能單獨捕捉。
    """


@lru_cache(maxsize=2)
def _load(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def get(
    ws: str,
    par_contains: str,
    year: int = YEAR,
    est: str = "ctrl",
    storage: bool = False,
):
    """取單一參數值。par_contains 用子字串比對(目錄的參數名很長且有特殊字元)。

    est='ctrl' 是中央估計;'lower'/'upper' 是目錄自帶的區間 → 敏感度分析直接用。
    """
    d = _load(STORE if storage else TECH)
    s = d[
        (d.ws == ws)
        & (d.par.astype(str).str.contains(par_contains, regex=False, na=False))
    ]
    if not len(s):
        raise KeyError(f"{ws!r} 找不到參數 {par_contains!r}")
    s = s.dropna(subset=["year", "val"])

    def _nearest(sub):
        # **年份格點隨技術與 est 而異**(ctrl 常有 2015/2020/2030/2050;lower/upper 常只有
        # 2020/2050;有些技術 ctrl 從 2025 才開始)→ 取最接近請求年份者,不硬性相等。
        return float(sub.loc[(sub["year"] - year).abs().idxmin(), "val"])

    want = s[s.est == est]
    if len(want):
        return _nearest(want)
    # 🔴 **沒有 ctrl 就拋錯,不要自己生一個中點**(2026-08-11 改;舊版回 (lower+upper)/2)。
    # 目錄對某些技術不給中央估計**是有理由的**:那些參數(尤其是容量)是**業主的設計選擇**,
    # 不是技術屬性。官方不給中央值是誠實,程式偷偷填一個才是造假 —— 而且填出來的數字
    # 會被後續當成「目錄真值」引用。實際踩到的兩個:
    #   · '05 Gas turb. CC' 容量只有 lower=100 / upper=500  → 舊版填了 300(5 倍區間的中點)
    #   · '44 Natural Gas DH Only' 容量只有 0.5–10 MW_h     → 同樣問題
    # 要區間就明確要 est='lower'/'upper';要中央值而目錄沒有,就由呼叫端自己決定並註明。
    lo, hi = s[s.est == "lower"], s[s.est == "upper"]
    if est == "ctrl" and len(lo) and len(hi):
        raise NoCentralEstimate(
            f"{ws!r} 的 {par_contains!r} **目錄沒有 ctrl 中央估計**,只有 "
            f"lower={_nearest(lo):g} / upper={_nearest(hi):g}。"
            f"這通常表示該參數是業主的設計選擇而非技術參數(容量最常見)。"
            f"請由呼叫端明確給值並註明依據,或改用 est='lower'/'upper'。"
        )
    raise KeyError(f"{ws!r} / {par_contains!r} 沒有 est={est} 的值")


def technologies(pattern: str = "", storage: bool = False) -> list[str]:
    d = _load(STORE if storage else TECH)
    ws = sorted(d["ws"].dropna().unique())
    return [w for w in ws if pattern.lower() in w.lower()]


def is_back_pressure(ws: str) -> bool:
    """這個技術是**背壓式**還是**抽汽式**?

    為什麼要分:`chp.solve()` 的可行域是抽汽式的(`P ≥ Cb·Q` 且 `P + Cv·Q ≤ P_max`,
    一塊面積)。**背壓式機組沒有這塊面積,它只能沿 `P = Cb·Q` 這條線走** —— 熱和電
    完全綁死,不能互換。用抽汽式的可行域去跑背壓機組,會給它不存在的彈性。

    目錄的表示法:背壓機組的 Cv 欄填 1.0 並附註
    "The Cv value does not exist for plants with a back pressure turbine or an ORC turbine"。
    所以判斷依據是技術名稱含 'back pressure',或註解文字提到 Cv 不存在。
    """
    d = _load(TECH)
    s = d[d.ws == ws]
    name = " ".join(s["Technology"].dropna().astype(str).unique()).lower()
    if "back pressure" in name or "back-pressure" in name:
        return True
    cv = s[s.par.astype(str).str.contains("Cv coefficient", regex=False, na=False)]
    txt = " ".join(cv["note_text"].dropna().astype(str).unique()).lower()
    return "does not exist" in txt


# 熱側可用的**抽汽式** CHP 原型(背壓式不適用目前的可行域,已排除)。
# 燃料別是選原型的依據 — DK1 2025 熱電發電量:生質 32.8% / 煤 27.8% / 氣 23.7% / 廢棄物 13.2%
CHP_ARCHETYPES = {
    "wood_chips": "09a Wood Chips extract. plant",
    "wood_pellets": "09b Wood Pellets extract. plant",
    "gas_cc": "05 Gas turb. CC, steam extract.",
    "coal": "01 Coal CHP",
}

# **背壓式**原型(2026-08-11 起 `chp.solve()` 支援)。熱電綁死 P=Cb·Q、**零熱電彈性**。
# 這些正是 DK2 的垃圾焚化(ARC / Vestforbrænding / ARGO,佔供熱 **27.7%**)。
# 溫度基準:CTR/VEKS 是高溫傳輸網 → 只能用 50 degree 那批,**不可混用 Medium 的
# (40°C/80°C)**,那等於偷偷改了熱網溫度(見 STATUS.md §4.8 ③)。
BP_ARCHETYPES = {
    "waste": "08 WtE CHP, Large, 50 degree",  # 46.81 MW_e/台,Cb 0.28
    "waste_medium": "08 WtE CHP, Medium",  # ⚠️ 40/80 低溫基準,DK2 不適用
    "straw": "09c Straw, Large, 50 degree",  # 38.99 MW_e/台,Cb 0.43
}


def availability(ws: str, year: int = YEAR, est: str = "ctrl") -> float:
    """機組年可用率 —— 用來量化「改用 name plate 效率」帶來的樂觀偏誤。

    目錄有兩種寫法,這裡都吃:
      · 少數表直接給 `Availability`(例:'01 Coal CHP' = 0.95)
      · 多數只給 `Forced outage` 與 `Planned outage [weeks per year]` → 合成:
            availability = (1 − forced) × (1 − planned_weeks / 52)

    ⚠️ **`chp.solve()` 目前完全沒有用這個值**,它是資料不是行為。放在這裡是為了讓
    「name plate = 設計點效率、而 LP 沒建停機與最小負載」的代價可以被量化與引用。
    要補償的話是拿它**折減 p_max**(容量折減),不必引進整數變數 —— 見 STATUS.md §4.8 ②。
    """
    try:
        return get(ws, "Availability", year, est)
    except KeyError:
        pass
    forced = get(ws, "Forced outage", year, est)
    try:
        planned = get(ws, "Planned outage", year, est)
    except KeyError:
        planned = 0.0
    return (1.0 - forced) * (1.0 - planned / 52.0)


def plant_params(
    chp_ws: str,
    year: int = YEAR,
    est: str = "ctrl",
    eb_ws: str = "41 Electric boiler, large",
    hp_ws: str = "40 Comp. hp, airsource 10 MW",
    pb_ws: str = "44 Natural Gas DH Only",
    store_ws: str = "141b Large TTES",
) -> dict:
    """把目錄參數對應成 `chp.Plant` 的欄位。回傳 dict,直接 `Plant(**這個)`。

    對應關係(左=我的參數,右=目錄參數名):
      p_max   ← Generating capacity for one unit [MW_e]
      cb      ← Cb coefficient (50°C/100°C)
      cv      ← Cv coefficient (50°C/100°C)
      eta_el  ← Electrical efficiency (net, annual average)
      eb_max  ← 電鍋爐 Generating capacity for one unit [MW_h]
      eta_eb  ← 電鍋爐 Heat efficiency (net, annual average)
      hp_max  ← 熱泵 Generating capacity for one unit [MW_h]
      cop_ref ← 熱泵 Heat efficiency (net, annual average)  ← 熱泵的「熱效率」就是 COP(>1)
      pb_max  ← 尖峰鍋爐 Generating capacity for one unit [MW_h]
      eta_pb  ← 尖峰鍋爐 Heat efficiency (net, annual average)
      s_max   ← TTES Energy storage capacity for one unit [MWh]
      s_rate  ← TTES Output capacity for one unit [MW]
      s_loss  ← TTES Energy losses during storage [%/day] ÷ 24 → 每小時比例
    """
    # ✅ 2026-08-11 起**背壓式也支援了**(`chp.solve()` 用背壓線上界表達,見那裡的說明)。
    # 這裡要做的兩件事:標記型式、把 Cv 歸零。
    # 🔴 **Cv 一定要歸零**:目錄給背壓表填 Cv=1.0 並附註「此值對背壓/ORC 機組不存在」,
    #    那是**哨兵值不是物理量**。照抄會讓容量線變成 P + 1.0·Qc ≤ P_max —— 憑空多出
    #    一條不存在的限制,把機組的熱出力砍掉一大半。
    bp = is_back_pressure(chp_ws)

    def g(ws, p):
        return get(ws, p, year, est)

    def eta_el(ws: str) -> float:
        # 🔴 **一定要 name plate,不能用 annual average**(2026-08-08 發現、2026-08-10 全面驗證)。
        # 目錄的 `Cb` 是用 **name plate** 效率算出來的:拿所有**背壓表**(只有它們同時列了
        # 電效率與熱效率)比對 η_el/η_th 與表列 Cb —— **16 張全中**,name plate 比值的誤差
        # 全部 ≤0.005,annual average 的誤差最小也有 0.006(見 demo() 的 self-check)。
        # `Cb`/`Cv`/`η_el` 出現在同一組可行域與燃料式裡 → **基準必須一致**,否則等於
        # 在同一個 LP 裡混用兩種效率定義。舊版把順序寫反了,是既有 bug。
        # ⚠️ 代價:name plate 是設計點效率,而 LP 沒有建強迫停機與最小負載 → **系統性樂觀**。
        #    可量化的補償見 availability();**目前只是資料,solve() 沒有用它**。
        try:
            return g(ws, "Electrical efficiency (net, name plate)")
        except KeyError:
            return g(ws, "Electrical efficiency (net, annual average)")

    def opt(ws: str, p: str):
        """沒有 ctrl 中央估計 → 回 `None`,**不編一個數字**(見 NoCentralEstimate)。

        回 None 而不是拋錯,是為了讓 `plant_params()` 仍能回傳完整的 dict,
        由呼叫端(`chp.dea_plant()`)決定怎麼處理 —— 但它**必須**處理,不能默默沿用。
        """
        try:
            return g(ws, p)
        except NoCentralEstimate:
            return None

    day_loss = get(store_ws, "Energy losses during storage", year, est, storage=True)
    return dict(
        # ⚠️ 容量欄用 opt():目錄對氣 CC 與天然氣 DH 鍋爐**都沒有 ctrl 容量**
        p_max=opt(chp_ws, "Generating capacity for one unit [MW_e]"),
        cb=g(chp_ws, "Cb coefficient"),
        # 背壓式的 Cv 是哨兵值(1.0)→ 歸零,理由見上
        cv=0.0 if bp else g(chp_ws, "Cv coefficient"),
        back_pressure=bp,
        eta_el=eta_el(chp_ws),
        eb_max=opt(eb_ws, "Generating capacity for one unit [MW_h]"),
        eta_eb=g(eb_ws, "Heat efficiency (net, annual average)"),
        hp_max=opt(hp_ws, "Generating capacity for one unit [MW_h]"),
        cop_ref=g(hp_ws, "Heat efficiency (net, annual average)"),
        pb_max=opt(pb_ws, "Generating capacity for one unit [MW_h]"),
        eta_pb=g(pb_ws, "Heat efficiency (net, annual average)"),
        # 變動 O&M。⚠️ **目錄對 CHP 記在 EUR/MWh_e、對純熱機組記在 EUR/MWh_h** —— 這不是
        # 我選的,是目錄的記帳方式。所以 CHP 沒有「每 MWh_th 的 vom」(vom_th 留 0),
        # 成本函數靠參數歸零吸收這個差異,不需要為機組類型分支。
        vom_e=g(chp_ws, "Variable O&M (*total) [EUR/MWh_e]"),
        vom_eb=g(eb_ws, "Variable O&M (*total) [EUR/MWh_h]"),
        vom_hp=g(hp_ws, "Variable O&M (*total) [EUR/MWh_h]"),
        vom_pb=g(pb_ws, "Variable O&M (*total) [EUR/MWh_h]"),
        s_max=get(
            store_ws,
            "Energy storage capacity for one unit [MWh]",
            year,
            est,
            storage=True,
        ),
        s_rate=get(
            store_ws, "Output capacity for one unit [MW]", year, est, storage=True
        ),
        s_loss=day_loss / 100.0 / 24.0 if day_loss > 1 else day_loss / 24.0,
    )


def demo() -> None:
    # ① 目錄讀得到、ctrl/lower/upper 三個估計都在
    cb = {
        e: get("09a Wood Chips, Large 50 degree", "Cb coefficient", est=e)
        for e in ("lower", "ctrl", "upper")
    }
    assert cb["lower"] <= cb["ctrl"] <= cb["upper"], f"Cb 區間應單調:{cb}"
    print(
        f"  DEA ok: 木片大型 CHP 的 Cb = {cb['ctrl']:.3f}(區間 {cb['lower']:.3f}–{cb['upper']:.3f})"
    )

    # ② 背壓/抽汽要分得出來,而且背壓式的 Cv 哨兵值必須被歸零
    assert is_back_pressure("09a Wood Chips, Large 50 degree"), (
        "木片大型是背壓式,應被判定為 True"
    )
    assert not is_back_pressure("09a Wood Chips extract. plant"), "抽汽式不該被判成背壓"
    b = plant_params("08 WtE CHP, Large, 50 degree")
    assert b["back_pressure"] is True, "WtE 應被標記為背壓式"
    assert b["cv"] == 0.0, (
        f"背壓式的 cv 必須歸零(目錄的 1.0 是哨兵值),得 {b['cv']} —— "
        "照抄會讓容量線多出一條不存在的限制"
    )
    assert get("08 WtE CHP, Large, 50 degree", "Cv coefficient") == 1.0, (
        "這張表的 Cv 原始值應該就是哨兵 1.0,若目錄改了要重新確認歸零邏輯"
    )
    e = plant_params("09a Wood Chips extract. plant")
    assert e["back_pressure"] is False and e["cv"] > 0, "抽汽式不該被歸零"
    print(
        f"  背壓/抽汽 ok: WtE 標記為背壓且 cv 哨兵值 1.0 已歸零;抽汽式保留 cv={e['cv']:.2f}"
    )

    # ③ 🔴 **基準一致性** — 目錄的 Cb 是用哪一種效率算的?這決定 eta_el 該取哪一欄。
    #    只有背壓表同時列了電效率與熱效率,所以拿它們當試紙:若 Cb 是 name plate 基準,
    #    則 η_el/η_th 的 name plate 比值應該重現表列 Cb,而 annual average 比值不該。
    np_err, aa_err = [], []
    for w in (w for w in technologies("") if is_back_pressure(w)):
        try:
            cb = get(w, "Cb coefficient")
            r_np = get(w, "Electrical efficiency (net, name plate)") / get(
                w, "Heat efficiency (net, name plate)"
            )
            r_aa = get(w, "Electrical efficiency (net, annual average)") / get(
                w, "Heat efficiency (net, annual average)"
            )
        except KeyError:
            continue  # 抽汽表沒有熱效率欄 —— 那正是兩個家族參數化方式不同的證據
        np_err.append(abs(r_np - cb))
        aa_err.append(abs(r_aa - cb))
    assert len(np_err) >= 10, f"可比對的背壓表太少({len(np_err)}),self-check 失去意義"
    assert max(np_err) < min(aa_err), (
        f"name plate 應該一致地比 annual average 更貼近 Cb:"
        f"NP 最差 {max(np_err):.4f} vs AA 最好 {min(aa_err):.4f}"
    )
    # 而 plant_params 必須真的取到 name plate 那一欄(這行才是防迴歸的重點)
    for lab, ws in CHP_ARCHETYPES.items():
        want = get(ws, "Electrical efficiency (net, name plate)")
        assert abs(plant_params(ws)["eta_el"] - want) < 1e-9, (
            f"{lab} 的 eta_el 沒有取 name plate(基準混用,就是 2026-08-08 那個 bug)"
        )
    print(
        f"  基準 ok: {len(np_err)} 張背壓表全部顯示 Cb 是 **name plate** 基準"
        f"(NP 誤差 ≤{max(np_err):.4f} < AA 誤差 ≥{min(aa_err):.4f});"
        f"四個原型的 eta_el 都取到 name plate"
    )

    # ④ 物理合理性:電效率 0–1、COP > 1、鍋爐效率接近 1
    p = plant_params("09a Wood Chips extract. plant")
    assert 0 < p["eta_el"] < 1, f"電效率應在 0–1,得 {p['eta_el']}"
    assert p["cop_ref"] > 1, f"熱泵 COP 應 >1,得 {p['cop_ref']}"
    assert 0.8 < p["eta_eb"] <= 1.05, f"電鍋爐效率應接近 1,得 {p['eta_eb']}"
    assert 0 < p["s_loss"] < 0.05, f"蓄熱槽每小時散熱應很小,得 {p['s_loss']}"
    print("  參數 ok: 電效率/COP/鍋爐效率/散熱率都在物理合理範圍")


def main() -> None:
    print("=== DEA Technology Catalogue 可用技術(熱側相關)===")
    for pat in ("CHP", "Wood", "WtE", "Electric boiler", "Comp. hp", "DH Only"):
        t = technologies(pat)
        if t:
            print(f"\n  [{pat}]")
            for w in t:
                print(f"    {w}")
    print("\n  [儲熱]")
    for w in technologies("TES", storage=True) + technologies(
        "hot water", storage=True
    ):
        print(f"    {w}")

    print(f"\n=== 示範:三個 CHP 原型的真實參數(year={YEAR}, est=ctrl)===")
    cands = {k: v for k, v in CHP_ARCHETYPES.items()}
    keys = ["p_max", "cb", "cv", "eta_el", "s_max", "s_rate", "s_loss"]
    print(f"  {'原型':<18}" + "".join(f"{k:>10}" for k in keys))
    for lab, ws in cands.items():
        try:
            p = plant_params(ws)
            # 沒有 ctrl 中央估計的欄位是 None(見 NoCentralEstimate)→ 印 n/a,不要編數字
            print(
                f"  {lab:<18}"
                + "".join(
                    f"{p[k]:>10.3f}" if p[k] is not None else f"{'n/a':>10}"
                    for k in keys
                )
            )
        except KeyError as e:
            print(f"  {lab:<18}(缺參數:{e})")

    print("\n=== 對照:chp.Plant 的預設值(2026-08-07 起 == 木片抽汽,不再是佔位值)===")
    from chp import Plant

    d = Plant()
    print("  " + "".join(f"{getattr(d, k):>10.3f}" for k in keys))

    print(
        "\n⚠️ 目錄裡沒有 CO2 排放因子(那是燃料屬性)→ ef_chp/ef_pb 仍需別的來源。\n"
        "⚠️ 容量是「單一機組」典型值;熱網規模要另外對齊,否則仍有尺寸不匹配問題。"
    )


if __name__ == "__main__":
    demo()
    main()
