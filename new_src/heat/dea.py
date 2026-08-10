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
    # 退回規則:某些參數目錄只給區間不給中央值(例:天然氣 DH 鍋爐容量只有 lower/upper)。
    # 要 ctrl 卻沒有 → 用 lower/upper 的中點,並且**不靜默**:回傳值仍是數字,但這個
    # 情況在 plant_params() 會被記錄到 provenance 裡,不會假裝是目錄的中央估計。
    lo, hi = s[s.est == "lower"], s[s.est == "upper"]
    if est == "ctrl" and len(lo) and len(hi):
        return (_nearest(lo) + _nearest(hi)) / 2.0
    if len(s):  # 最後手段:有什麼用什麼
        return _nearest(s)
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

# 🚩 **垃圾焚化(WtE)在目錄裡全部是背壓式**('08 WtE CHP, Large/Medium/Small'),
# 秸稈(09c Straw)也是。→ 這些機組**沒有抽汽可行域,熱電完全綁死**,不能當彈性來源。
# WtE 佔 DK1 熱電 13.2%、在 DK2(Amager/Vestforbrænding)更吃重 → 車隊有效彈性
# 比「總容量」看起來的少。要納入必須先在 chp.py 實作背壓式的等式約束。


def availability(ws: str, year: int = YEAR, est: str = "ctrl") -> float:
    """機組年可用率 —— 用來量化「改用 name plate 效率」帶來的樂觀偏誤。

    目錄有兩種寫法,這裡都吃:
      · 少數表直接給 `Availability`(例:'01 Coal CHP' = 0.95)
      · 多數只給 `Forced outage` 與 `Planned outage [weeks per year]` → 合成:
            availability = (1 − forced) × (1 − planned_weeks / 52)

    ⚠️ **`chp.solve()` 目前完全沒有用這個值**,它是資料不是行為。放在這裡是為了讓
    「name plate = 設計點效率、而 LP 沒建停機與最小負載」的代價可以被量化與引用。
    要補償的話是拿它**折減 p_max**(容量折減),不必引進整數變數 —— 見 STATUS.md §4.7 ②。
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
    if is_back_pressure(chp_ws):
        raise ValueError(
            f"{chp_ws!r} 是**背壓式**機組:熱電綁死在 P=Cb·Q 這條線上,沒有抽汽可行域。"
            f"chp.solve() 目前的約束是抽汽式的,套上去會給它不存在的彈性。"
            f"請改用抽汽式版本(見 CHP_ARCHETYPES),或先在 chp.py 實作背壓式的等式約束。"
        )
    g = lambda ws, p: get(ws, p, year, est)

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

    day_loss = get(store_ws, "Energy losses during storage", year, est, storage=True)
    return dict(
        p_max=g(chp_ws, "Generating capacity for one unit [MW_e]"),
        cb=g(chp_ws, "Cb coefficient"),
        cv=g(chp_ws, "Cv coefficient"),
        eta_el=eta_el(chp_ws),
        eb_max=g(eb_ws, "Generating capacity for one unit [MW_h]"),
        eta_eb=g(eb_ws, "Heat efficiency (net, annual average)"),
        hp_max=g(hp_ws, "Generating capacity for one unit [MW_h]"),
        cop_ref=g(hp_ws, "Heat efficiency (net, annual average)"),
        pb_max=g(pb_ws, "Generating capacity for one unit [MW_h]"),
        eta_pb=g(pb_ws, "Heat efficiency (net, annual average)"),
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

    # ② 背壓式必須被擋下來(它沒有抽汽可行域)
    assert is_back_pressure("09a Wood Chips, Large 50 degree"), (
        "木片大型是背壓式,應被判定為 True"
    )
    assert not is_back_pressure("09a Wood Chips extract. plant"), "抽汽式不該被判成背壓"
    try:
        plant_params("09a Wood Chips, Large 50 degree")
        raise AssertionError("背壓式應該要拋錯,不該回傳抽汽參數")
    except ValueError:
        pass
    print("  背壓/抽汽 ok: 背壓式機組會被擋下,不會誤用抽汽可行域")

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
            print(f"  {lab:<18}" + "".join(f"{p[k]:>10.3f}" for k in keys))
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
