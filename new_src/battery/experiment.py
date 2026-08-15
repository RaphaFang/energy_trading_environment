"""真實資料實驗 — v3/v4/三把尺/異質 agent 全部在這裡跑,產出文件裡的結果表。

為什麼統包一支:這些實驗共用「載 DK1 價格 → 切窗 → 跑 agent → 用單顆天花板當標尺」
這套骨架,分四支會複製四份。v1/v2 各自的 main() 是「跑起來看看」的示範,這支才是
**產出論文數字的地方**。

**每個實驗都跑兩組體量**,因為這是本專案最重要的結論之一:
  10MW  丹麥實況(全國併網電池最大案例才 10–30MW)→ 競爭幾乎不咬,結果退化
  1GW   市場力咬得動的尺度 → 機制才看得見(自制、租值消散、溢價消散)
兩組並列本身就是結果:**丹麥現在不需要擔心儲能的市場力,體量到 GW 才需要。**
λ 固定用結構估計值(見 battery/fringe.py),不再靠灌 λ 製造競爭——真正的旋鈕是體量。

用法:
  python new_src/battery/experiment.py all        全部跑(預設)
  python new_src/battery/experiment.py v3         Cournot vs price-taker
  python new_src/battery/experiment.py v4         風力情境:電池溢價與外部性
  python new_src/battery/experiment.py scales     三把尺 C/N/M + 勾結指標
  python new_src/battery/experiment.py hetero     異質預測品質:哪個 agent 賺最多
  python new_src/battery/experiment.py v2.3       體量連續掃描(10MW→10GW)× 異質預測品質,
                                           不含風力(單一自變數),找優勢倍數的門檻
"""

import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(__file__)
sys.path.insert(0, _HERE)  # 同資料夾的 v1/v2/v3/v4/fringe
sys.path.insert(0, os.path.dirname(_HERE))  # new_src/ → models.forecast
from v1_single import load_prices, perfect, settle  # noqa: E402
from v2_multi import per_agent_revenue, solve_day  # noqa: E402
from v3_cournot import cartel, competitive, cournot_br, nash  # noqa: E402
from v4_wind import wind_scenario  # noqa: E402

LAM = 0.004  # 結構估計(battery/fringe.py structural_lambda,DK1 中位 0.0042)
# 異質體量:10 家,前 2 大合計 35%(對齊 Ørsted+Vattenfall)。乘上 SCALES 得實際 MW。
SHARE = np.array([1.8, 1.7, 1.2, 1.0, 0.8, 0.8, 0.7, 0.6, 0.6, 0.8]) / 10
# ⚠️ 體量錨點的可信度受 fringe 曲線的資料支撐限制(見 fringe.out_of_support)。
# 2026-08-03 實測 DK1 超界比例:10MW 1% / 500MW 7% / 1GW 21% / 3GW 100%。
# → **主實驗設在 500MW**:勾結空間已張開(M−C≈4.7pp),而模型仍在支撐內。
#   1GW 以上只當「機制標定」,數字是外推,不可當結果報。
SCALES = {
    "10MW (丹麥實況)": 10.0,  # 全國最大併網電池案例 10–30MW
    "500MW (主實驗,支撐內 7%)": 500.0,  # ← 唯一同時「有市場力」+「有資料支撐」的尺度
    "1GW (北歐 2030,21% 超界)": 1000.0,  # Nordic Energy Research 預估 ~1,800MW
    "10GW (機制標定,全外推)": 10000.0,  # 不寫實,用來標定「要多大才咬得動」
}
MIN_H = 160  # 殘週跳掉
NWEEK = 8  # v3/三把尺用的週數:Cournot 的 Frank-Wolfe 在大 λ·w 下每週要幾十秒


def weeks(area: str = "DK1", n: int | None = None) -> list[np.ndarray]:
    """切成週窗(SoC 跨天連續、週末歸零)。n=None 取全部。"""
    p = load_prices(area)
    wk = p.index.tz_localize(None).to_period("W")
    out = [g.values for _, g in p.groupby(wk) if len(g) >= MIN_H]
    return out if n is None else out[-n:]  # 取最近 n 週


def weeks_with_wind(area: str = "DK1"):
    """價格週窗 + 對齊的**真實**風力出力率(0~1)。

    出力率 = (陸域+離岸風的隔日預測 MWh) ÷ 該區風電裝置容量。用真實資料而不是拿價格
    反推,理由有二:(1) DB 裡就有(DATA.md §2 的 Forecasts_Hour),不必用代理;(2) 代理會把「風與價
    負相關」這個**待驗證的性質**變成建構出來的假設,外部性的符號就不可信了。
    容量取樣本期最大出力當代理(裝置容量隨年份成長,這裡當定值 → 容量因數會略低估)。"""
    import duckdb

    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, "
        "COALESCE(onshore_wind_da_mwh,0)+COALESCE(offshore_wind_da_mwh,0) AS wind "
        f"FROM training WHERE area='{area}' AND y_price_eur IS NOT NULL "
        "AND onshore_wind_da_mwh IS NOT NULL ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    d["cf"] = d["wind"] / d["wind"].max()  # 出力率
    idx = pd.DatetimeIndex(d["timestamp_utc"]).tz_localize(None)
    wk = idx.to_period("W")
    ps, cfs = [], []
    for _, g in d.groupby(wk):
        if len(g) >= MIN_H:
            ps.append(g["price"].to_numpy())
            cfs.append(g["cf"].to_numpy())
    return ps, cfs


def weeks_with_state(area: str = "DK1", n: int | None = None):
    """價格週窗 + 對齊的殘餘負載 x(非線性 impact 與局部 λ 都要它)。同 weeks() 的切法。"""
    import duckdb

    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, residual_mwh AS x "
        f"FROM training WHERE area='{area}' AND y_price_eur IS NOT NULL "
        "AND residual_mwh IS NOT NULL ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    wk = pd.DatetimeIndex(d["timestamp_utc"]).tz_localize(None).to_period("W")
    ps = [g["price"].to_numpy() for _, g in d.groupby(wk) if len(g) >= MIN_H]
    xs = [g["x"].to_numpy() for _, g in d.groupby(wk) if len(g) >= MIN_H]
    return (ps, xs) if n is None else (ps[-n:], xs[-n:])


def ceiling(price: np.ndarray) -> float:
    """單顆基準(per-battery numeraire):1 顆電池、λ=0、完美預知的收益。
    注意它**不是車隊上限**——10 家各拿 99% → 車隊 9.9×。是計量單位,不是天花板。"""
    return settle(*perfect(price), price)


def _run_v3(area="DK1", nonlinear=False):
    """v3:每家內化自身衝擊(Cournot)vs 不內化(price-taker)。看大玩家是否停止自我蠶食。

    nonlinear=True:出清價走真 fringe 曲線,**且**每家的自制強度改用該小時的局部
    λ(x)(見 v3_cournot.cournot_br 的向量 lam_wi)。兩者必須一起換——只換出清價會讓
    大玩家在陡段自制不足。這是「非線性 × 內化」的正確組合。
    """
    if nonlinear:
        import fringe as F

        st = F.load_state(area).dropna(subset=["price", "x"])
        fr = F.fit_fringe(st)
        ws, xs = weeks_with_state(area, NWEEK)
    else:
        ws, xs = weeks(area, NWEEK), None
    print("\n" + "=" * 78)
    if nonlinear:
        # 不要印 LAM:這個模式根本沒用它,印了會讓人以為結果是 λ=0.004 跑出來的
        print(
            f"【v3】Cournot 自制 vs price-taker    {NWEEK} 週,10 家異質體量"
            f"  [非線性 impact + 局部曲率自制,曲線中位 λ={np.median(fr['lam_local']):.4f}]"
        )
        print(
            "  ⚠️ fit_fringe 是 price~x 的**雙變數**擬合(零控制),落在被鄰國汙染的高群\n"
            "     (實測:控德風光+邊界後 λ 塌到 ~0.005–0.009)→ 這條曲線約陡 3–4 倍,\n"
            "     下面的體量校準會系統性偏小。修法見 fringe.py 模組 docstring。"
        )
    else:
        print(
            "【v3】Cournot 自制 vs price-taker    λ=%.3f,%d 週,10 家異質體量"
            % (LAM, NWEEK)
        )
    print("=" * 78)
    for label, tot in SCALES.items():
        w = SHARE * tot
        acc = {k: np.zeros(len(w)) for k in ("v2", "v3")}
        ceil = 0.0
        for wi, p in enumerate(ws):
            ceil += ceiling(p)
            # 非線性:出清價用真曲線,自制強度用該小時局部 λ(x)(兩者同源才一致)
            imp = F.nonlinear_impact(xs[wi], fr) if nonlinear else None
            lam_h = F.lambda_at(xs[wi], fr) if nonlinear else LAM
            for k, br in (("v2", None), ("v3", cournot_br)):
                C, D, cl, _ = solve_day(p, w, lam_h, br=br, impact=imp)
                acc[k] += per_agent_revenue(C, D, cl, w)
        if nonlinear:
            oos = F.out_of_support(np.concatenate(xs), tot, fr)
            label += f"   [超界 {oos:.0%}{'' if oos <= 0.10 else ' ⚠️外推'}]"
        print(f"\n  ── {label}   每家 {w[0]:.1f}–{w[-3]:.1f} MW,車隊 {tot:.0f} MW")
        print(
            f"     {'':16}{'最大玩家':>10}{'最小玩家':>10}{'大小差':>9}{'車隊/單顆基準':>14}"
        )
        for k, nm in (("v2", "price-taker"), ("v3", "Cournot")):
            r = acc[k] / w / ceil  # 每 MW 佔單顆基準
            big, sml = r[np.argmax(w)], r[np.argmin(w)]
            print(
                f"     {nm:<16}{big:>9.0%}{sml:>10.0%}{(sml - big) * 100:>8.0f}pp"
                f"{acc[k].sum() / ceil:>13.1f}×"
            )


def _run_v4(area="DK1"):
    """v4:一群同體量風商,部分裝電池。看電池溢價消散與對純風商的外部性。"""
    print("\n" + "=" * 78)
    print("【v4】風力情境:採用率 vs 電池溢價 / 對純風商的外部性")
    print("=" * 78)
    ws, shapes = weeks_with_wind(area)
    for label, tot in SCALES.items():
        batt_mw = tot / 10.0  # 10 家,每家裝的電池
        wind_mw = batt_mw * 5.0  # 風機是電池的 5 倍(典型風場配比)
        print(
            f"\n  ── {label}   10 家風商各 {wind_mw:.0f} MW 風,裝電池者另有 {batt_mw:.0f} MW/4h"
        )
        print(
            f"     {'裝電池家數':>10}{'純風商 €/MW風/週':>18}{'電池溢價 €/MW電/週':>20}{'外部性 €/MW風/週':>18}"
        )
        base = None
        for n_batt in (0, 2, 5, 10):
            wind_rev = prem = ext = 0.0
            for p, sh in zip(ws, shapes):
                wind = wind_mw * sh  # sh = 真實風力出力率(0~1),見 weeks_with_wind
                r = wind_scenario(p, wind, n_batt, batt_mw, LAM)
                wind_rev += r["wind_only"]
                prem += r["batt_premium"]
                ext += r["externality"]
            nw = len(ws)
            w_pw, p_pw = wind_rev / wind_mw / nw, (prem / batt_mw / nw if n_batt else 0)
            e_pw = ext / wind_mw / nw
            if base is None:
                base = w_pw
            print(
                f"     {n_batt:>10}{w_pw:>18,.0f}{p_pw if n_batt else 0:>20,.0f}{e_pw:>18,.1f}"
            )


def _run_scales(area="DK1"):
    """三把尺:聯合利潤必然 C(競爭) ≤ N(Nash) ≤ M(卡特爾)。勾結空間 = M−N。"""
    print("\n" + "=" * 78)
    print("【三把尺】C 競爭 ≤ N Nash ≤ M 卡特爾    勾結指標 Δ=(Π_obs−Π_N)/(Π_M−Π_N)")
    print("=" * 78)
    ws = weeks(area, NWEEK // 2)  # C 要跑 n_firms 家 Cournot,最貴的一格,再砍半
    print(
        f"\n     {'體量':<18}{'C 競爭':>10}{'N Nash':>10}{'M 卡特爾':>11}{'勾結空間 M−N':>14}"
    )
    for label, tot in SCALES.items():
        w = SHARE * tot
        jC = jN = jM = ceil = 0.0
        for p in ws:
            ceil += ceiling(p)
            # ponytail: 12 廠即足以證明 C<N(廠越多越接近 price-taking,收斂快);
            # 原本 20 廠在 10GW 要跑幾分鐘一週,對「C 是下錨」這個用途不值得。
            jC += competitive(p, w, LAM, n_firms=12)[3]
            C, D, cl, _ = nash(p, w, LAM)
            jN += per_agent_revenue(C, D, cl, w).sum()
            jM += cartel(p, w, LAM)[3]
        c, n_, m = jC / ceil, jN / ceil, jM / ceil
        print(
            f"     {label:<18}{c:>9.1f}×{n_:>10.1f}×{m:>10.1f}×{(m - n_) / n_ * 100:>12.1f}%"
        )
    print(
        "\n     (單位 = 車隊聯合利潤 ÷ 單顆基準。勾結空間 = 卡特爾比 Nash 多賺幾 %。)"
    )


def _run_hetero(area="DK1"):
    """異質預測品質:同體量、同市場,差異純粹來自資訊 → 哪個 agent 賺最多。"""
    from models.forecast import fit_predict, load_training

    print("\n" + "=" * 78)
    print("【異質 agent】10 家同體量,預測品質不同 — 預測優勢在競爭下值多少錢")
    print("=" * 78)
    f = fit_predict(load_training(area))
    te, act, preds = f["te_idx"], f["actual"], f["preds"]
    per = te.tz_localize(None).to_period("W")
    MIX = ["LightGBM"] * 3 + ["Ridge"] * 3 + ["naive-24h"] * 4
    for label, tot in SCALES.items():
        w = np.full(len(MIX), tot / len(MIX))
        acc, ceil = np.zeros(len(MIX)), 0.0
        for k in per.unique():
            m = np.asarray(per == k)
            if m.sum() < MIN_H:
                continue
            a = act[m]
            ceil += ceiling(a)
            bel = np.array([preds[n][m] for n in MIX])  # 每家一份預測
            C, D, cl, _ = solve_day(a, w, LAM, belief=bel)
            acc += per_agent_revenue(C, D, cl, w)
        print(f"\n  ── {label}   10 家各 {w[0]:.0f} MW")
        print(f"     {'agent 類型':<14}{'家數':>5}{'€/MW/週':>11}{'佔單顆基準':>12}")
        seen = {}
        for i, nm in enumerate(MIX):
            seen.setdefault(nm, []).append(i)
        nw = len(per.unique())
        for nm, idx in seen.items():
            per_mw = acc[idx].sum() / w[idx].sum() / nw
            print(
                f"     {nm:<14}{len(idx):>5}{per_mw:>11,.0f}{acc[idx].mean() / w[0] / ceil:>11.0%}"
            )


def _run_v2_3(area="DK1", nonlinear=False):
    """v2.3:體量連續掃描 × 異質預測品質 — 定出「預測優勢開始被放大」的門檻在哪。

    地基跟 §hetero 一樣(v2.2 belief=各家預測價、price-taker、λ 結構估計固定),
    唯一差別是把 SCALES 的 3 個離散點換成 log-spaced 連續網格(10MW→10GW,13 點,
    含原本兩個錨點 1GW/10GW)。**刻意不接 v4(風力)**——單一自變數是體量,
    加風力會多一個變因,測不出「優勢倍數」的門檻是被體量還是被風力推動的。

    nonlinear=True:出清價改走 `fringe.nonlinear_impact`(真 fringe 曲線 p₀(x+net)−p₀(x))
    取代常數 LAM,其餘完全不變 → 直接比「常數 λ vs 真曲線」對門檻的影響。
    2026-08-03 實跑:門檻(優勢首破 1.5×)從 ~3GW 左移到 ~440MW(7×)= 常數 λ 高估了
    「要多大才需要好預測」。⚠️ 但 ≥1GW 時 naive 報酬翻負(−41%@10GW),優勢倍數的分母
    跨越 0 就沒意義了——那是 price-taker 不內化自身腳印、一路交易進虧損的產物,
    不是市場預言。要解讀 GW 級,得先把 v3 的自制 lam_wi 也換成非線性(見 fringe.py)。
    """
    from models.forecast import SPLIT, fit_predict, load_training

    print("\n" + "=" * 78)
    print(
        "【v2.3】體量連續掃描 × 異質預測品質(不含風力,單一自變數=體量)"
        + ("  [非線性 impact]" if nonlinear else "")
    )
    print("=" * 78)
    df = load_training(area)
    f = fit_predict(df)
    te, act, preds = f["te_idx"], f["actual"], f["preds"]
    if nonlinear:
        import fringe as F

        fr = F.fit_fringe(
            pd.DataFrame(
                {
                    "price": df["y_price_eur"].to_numpy(),
                    "x": df["residual_mwh"].to_numpy(),
                }
            ).dropna()
        )
        resid = df.loc[df.timestamp_utc >= SPLIT, "residual_mwh"].to_numpy()
        assert len(resid) == len(act), f"residual {len(resid)} 對不上 test {len(act)}"
        # ponytail: residual 偶有 NaN → 中位數補,否則 p₀(NaN) 汙染整週出清價
        resid = np.where(np.isnan(resid), np.nanmedian(resid), resid)
    per = te.tz_localize(None).to_period("W")
    weeks_idx = [k for k in per.unique() if (per == k).sum() >= MIN_H]
    nw = len(weeks_idx)
    MIX = ["LightGBM"] * 3 + ["Ridge"] * 3 + ["naive-24h"] * 4
    scale_grid = np.geomspace(10.0, 10_000.0, 13)  # MW,10 段對數等距,含 1GW/10GW 錨點

    rows = []
    for tot in scale_grid:
        w = np.full(len(MIX), tot / len(MIX))
        acc, ceil = np.zeros(len(MIX)), 0.0
        for k in weeks_idx:
            m = np.asarray(per == k)
            a = act[m]
            ceil += ceiling(a)
            bel = np.array([preds[n][m] for n in MIX])  # 每家一份預測
            imp = F.nonlinear_impact(resid[m], fr) if nonlinear else None
            C, D, cl, _ = solve_day(a, w, LAM, belief=bel, impact=imp)
            acc += per_agent_revenue(C, D, cl, w)
        pct = {
            nm: acc[[i for i, n in enumerate(MIX) if n == nm]].mean() / w[0] / ceil
            for nm in ("LightGBM", "Ridge", "naive-24h")
        }
        rows.append(
            {
                "scale_mw": tot,
                **pct,
                "advantage": pct["LightGBM"] / pct["naive-24h"],
                # 支撐檢查:這個體量有多少小時把 fringe 查到資料範圍外(只有非線性才適用)
                "out_of_support": F.out_of_support(resid, tot, fr)
                if nonlinear
                else 0.0,
            }
        )

    out = pd.DataFrame(rows)
    hdr = f"\n     {'體量 MW':>10}{'LightGBM':>10}{'Ridge':>9}{'naive-24h':>11}{'優勢倍數':>10}"
    print(hdr + (f"{'超界%':>8}{'可信度':>12}" if nonlinear else ""))
    for _, r in out.iterrows():
        line = (
            f"     {r.scale_mw:>10,.0f}{r.LightGBM:>10.0%}{r.Ridge:>9.0%}"
            f"{r['naive-24h']:>11.0%}{r.advantage:>9.2f}×"
        )
        if nonlinear:
            f_ = r.out_of_support
            line += f"{f_:>7.0%}  " + (
                "ok" if f_ <= 0.10 else ("borderline" if f_ <= 0.25 else "外推,勿引用")
            )
        print(line)
    os.makedirs("new_src/results", exist_ok=True)
    out_path = (
        f"new_src/results/v2_3_sweep_{area}{'_nonlinear' if nonlinear else ''}.csv"
    )
    out.to_csv(out_path, index=False)
    print(f"\n  → 存到 {out_path},供畫連續曲線(優勢倍數 vs 體量)用。")
    if nonlinear:
        print(
            "  ⚠️ 標「外推」的列不可引用:fringe 查到資料範圍外,np.interp 夾端點 → 衝擊飽和,\n"
            "     不是估計值。且該處 naive 報酬翻負、優勢倍數分母跨 0 也失去意義。\n"
            "     本掃描是 price-taker(不內化自身腳印);要看內化版跑 `experiment.py v3-nl`。"
        )
    return out


def _run_iv(area="DK1"):
    """λ 的識別檢查:風力當工具變數(IV) vs OLS。見 fringe.iv_lambda 的排除限制討論。"""
    import fringe as F

    print("\n" + "=" * 78)
    print("【λ 識別】風力預測當工具變數(2SLS) vs OLS — λ 是不是內生偏誤出來的?")
    print("=" * 78)
    r = F.iv_lambda(area)
    print(f"\n  樣本 {r['n']:,} 小時,控制:gas / co2 / 德國殘餘 / 小時固定效果")
    print(
        f"  第一階段  風力→殘餘負載 係數 {r['first_stage_wind_coef']:.3f}"
        f"(預期 ≈−1:風多 1MW,殘餘少 1MW),F = {r['first_stage_F']:,.0f}"
        f"{'  (>10 = 強工具)' if r['first_stage_F'] > 10 else '  ⚠️弱工具'}"
    )
    print(f"\n  {'OLS λ':>12} = {r['lam_ols']:.4f}  €/MWh per MW")
    print(f"  {'IV  λ':>12} = {r['lam_iv']:.4f}  €/MWh per MW")
    ratio = r["lam_iv"] / r["lam_ols"] if r["lam_ols"] else float("nan")
    print(f"  {'IV / OLS':>12} = {ratio:.2f}×")
    print(
        "\n  讀法:兩者接近 → OLS 的內生性偏誤不嚴重,現行 λ 站得住。\n"
        "        差很多  → 觀察性估計有偏,模擬器該改用 IV 值。\n"
        "  ⚠️ 排除限制不完美:丹麥風與德國風同源,德國價又經聯絡線直接影響 DK。\n"
        "     已控 de_residual,但「德國風的其他管道」無法完全排除。"
    )
    return r


def main() -> None:
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    runners = {
        "v3": _run_v3,
        "v4": _run_v4,
        "scales": _run_scales,
        "hetero": _run_hetero,
        "v2.3": _run_v2_3,
        "v2.3-nl": lambda area="DK1": _run_v2_3(area, nonlinear=True),
        "v3-nl": lambda area="DK1": _run_v3(area, nonlinear=True),
        "iv": _run_iv,
    }
    print(
        f"\nλ = {LAM}(結構估計,見 battery/fringe.py)。單顆基準 = 1 顆 1MW/4MWh、λ=0、完美預知。"
    )
    for name, fn in runners.items():
        if which in ("all", name):
            fn()
    print()


if __name__ == "__main__":
    main()
