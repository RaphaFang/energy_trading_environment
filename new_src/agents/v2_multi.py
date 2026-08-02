"""v2 — 多 agent 儲能競爭:在 v1 的單 agent 地基上加 λ 價格衝擊 + 輪流最佳反應。

「回合」= 求均衡的迭代,不是時間流逝:所有 agent 投同一次拍賣,輪流互相最佳反應
直到沒人想改(收斂 = Nash 均衡),或到回合上限(= 有限理性,只想幾步就停)。

膠水是 λ:看到的價 = 歷史價 + λ×(別人的淨買量)。沒有 λ,agent 互不影響、一輪收斂。
每個 agent 的預設最佳反應就是 v1.perfect(在被別人推移後的價上跑同一個 LP)。

v2.1 / v2.2 不是兩個檔,是 solve_day 的 `belief` 參數:
  belief=None   上帝視角,對真實價排程 → 隔離出「純價格衝擊」的成本
  belief=預測價  寫實,對自己的預測排程、真實價結算 → 價格衝擊 + 預測誤差

v3 的 Cournot 不改這裡:它只是換一種最佳反應,用 `br=` 傳進來(見 v3_cournot.py)。
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from v1_single import load_prices, perfect, settle  # noqa: E402


def _per_agent(spec, n, default):
    """把「共用」或「每家一份」統一成長度 n 的 list,呼叫端不必分兩種寫法。
    None            → 全員用 default
    單一函式         → 全員共用同一個策略
    list[函式]       → 每家一套策略
    1-D 陣列 (H,)    → 全員共用同一份信念價
    2-D 陣列 (N,H)   → 每家一份信念價
    """
    if spec is None:
        return [default] * n
    if callable(spec):
        return [spec] * n
    if isinstance(spec, (list, tuple)) and callable(spec[0]):
        assert len(spec) == n, f"策略數 {len(spec)} 對不上玩家數 {n}"
        return list(spec)
    arr = np.asarray(spec, float)
    if arr.ndim == 2:
        assert len(arr) == n, f"信念列數 {len(arr)} 對不上玩家數 {n}"
        return [row for row in arr]
    return [arr] * n


def solve_day(price, weights, lam, rounds=15, tol=1e-3, belief=None, br=None, impact=None):
    """一週的均衡:輪流(Gauss-Seidel)最佳反應。weights[i] = 玩家 i 的體量。
    回傳每家「每單位體量」的排程 C/D、出清價、用了幾回合。

    **agent 可以在三個維度上不一樣**(這是研究「哪個 agent 賺最多」的前提——
    全同質的話每家每單位報酬必然相同,那是對稱性不是發現):

      weights  體量      list[float]
      belief   資訊/預測  None=全員上帝視角;1-D 陣列=全員共用同一份預測;
                         2-D (N,H)=**每家一份**(A 家用 LightGBM、B 家用 naive…)
      br       策略      單一函式=全員共用;list[函式]=**每家一套**
                         (A 家 price-taker、B 家 Cournot 自制…)

    belief 的舊語意保留:None = v2.1 上帝視角,共用 1-D 陣列 = v2.2 全員同一個預測。
    不論信什麼,**結算一律用真實出清價**——信錯就會被罰。

    br(seen, lam_wi) -> (c, d)。預設 price-taker(吃 perfect 的 LP、無視自己的
    λ·w_i);v3 傳 Cournot 版進來內化自身衝擊。

    impact:價格衝擊怎麼算,**開關**,預設 None → 線性 `lam·net`(v2.1/v2.2 原本的
    公式,真實價 + λ×淨量)。要換成非線性(車隊淨量沿曲線跑遠,GW 級才需要),
    傳一個 `net(MW 陣列) -> Δp(€/MWh 陣列)` 的函式,例如 `agents/fringe.py` 的
    `nonlinear_impact(x, fringe)`(用真實 fringe 曲線 p₀(x+net)−p₀(x) 取代常數斜率,
    見 MULTI_AGENT_MARKET.md §3.9)。**不傳就完全是舊行為**——v3/v4/hetero/scales/
    compare.py 都沒傳這個參數,不受影響。⚠️ 只換了出清價這一層;br=cournot_br 的
    自制強度(lam_wi)還是常數,沒有跟著 impact 換成局部曲率,兩者同時用時大玩家
    的自制量會算錯(見 fringe.py 模組 docstring)。"""
    w = np.asarray(weights, float)
    N, H = len(w), len(price)
    bels = _per_agent(belief, N, np.asarray(price, float))  # 每家的信念價
    brs = _per_agent(br, N, lambda seen, lam_wi: perfect(seen))  # 每家的最佳反應
    impact_fn = impact if impact is not None else (lambda net: lam * net)
    C = np.zeros((N, H))
    D = np.zeros((N, H))
    used = rounds
    for r in range(rounds):
        change = 0.0
        for i in range(N):  # 輪流,馬上看到別人這輪的新決定
            net = (w[:, None] * (C - D)).sum(0)  # 全體體量加權淨量
            others = net - w[i] * (C[i] - D[i])  # 扣掉自己 = 別人的加權淨量
            seen = bels[i] + impact_fn(others)  # 我信的價,被別人的淨量推移
            c, d = brs[i](seen, lam * w[i])
            change += np.abs(c - C[i]).sum() + np.abs(d - D[i]).sum()
            C[i], D[i] = c, d
        if change < tol:  # 沒人想再改 → 收斂
            used = r + 1
            break
    cleared = price + impact_fn((w[:, None] * (C - D)).sum(0))  # 出清價(真實價+全體衝擊)
    return C, D, cleared, used


def per_agent_revenue(C, D, cleared, weights):
    """每家的報酬(€)。異質實驗的主要輸出——問「哪個 agent 賺最多」就是看這個。"""
    w = np.asarray(weights, float)
    return np.array([w[i] * settle(C[i], D[i], cleared) for i in range(len(w))])


def fleet_revenue(C, D, cleared, weights):
    """車隊總報酬(€):每家 per-unit 排程 × 體量,全部用同一個出清價結算。"""
    w = np.asarray(weights, float)
    return float(sum(w[i] * settle(C[i], D[i], cleared) for i in range(len(w))))


def _peak_hour(price):
    return int(np.argmax(price))


def demo():
    # self-check:λ=0 → agent 互不影響、排程相同;λ>0 → 大家把尖峰打平(出清尖峰價下降)
    p = np.full(24, 30.0)
    p[3] = 5
    p[19] = 120  # 便宜谷 + 尖峰
    C0, D0, cl0, _ = solve_day(p, [1, 1, 1], lam=0.0)
    assert np.allclose(C0[0], C0[1]) and np.allclose(D0[0], D0[1]), "λ=0 應各自相同"
    C1, D1, cl1, used = solve_day(p, [1, 1, 1], lam=4.0)
    h = _peak_hour(p)
    assert cl1[h] < p[h], "λ>0:大家搶賣尖峰 → 出清尖峰價應被壓低"
    assert used <= 15
    # belief 分離(v2.1 vs v2.2):餵爛預測(平價,看不出尖峰)→ agent 不搶尖峰 → 賺得比上帝視角少
    flat_belief = np.full(24, 30.0)
    Cg, Dg, clg, _ = solve_day(p, [1, 1, 1], lam=1.0)
    Cb, Db, clb, _ = solve_day(p, [1, 1, 1], lam=1.0, belief=flat_belief)
    god = fleet_revenue(Cg, Dg, clg, [1, 1, 1])
    blind = fleet_revenue(Cb, Db, clb, [1, 1, 1])
    assert blind < god, "瞎預測(平價)應賺不到尖峰,報酬須低於上帝視角"
    print(
        f"  v2 ok: λ=0 三家相同;λ=4 尖峰 €{p[h]:.0f}→出清 €{cl1[h]:.1f}(被打平),{used} 回合收斂"
    )
    print(f"  v2 belief ok: 上帝視角 €{god:.0f} > 瞎預測 €{blind:.0f}(預測誤差的代價)")
    _demo_heterogeneous(p)
    _demo_nonlinear_impact(p)


def _demo_heterogeneous(p):
    """異質 agent 的 self-check。同質時每家每單位報酬必然相同(對稱性,不是發現);
    要能問「哪個 agent 賺最多」,agent 必須真的不一樣。這裡驗兩個維度都通。"""
    # ① 資訊維度:三家同體量,預測品質不同(完美 / 有雜訊 / 全瞎)→ 報酬須照品質排序
    rng = np.random.default_rng(0)
    good = p.copy()  # 完美預知
    mid = p + rng.normal(0, 8, len(p))  # 有雜訊
    blind = np.full(len(p), p.mean())  # 看不出尖峰
    C, D, cl, _ = solve_day(p, [1, 1, 1], lam=0.5, belief=np.array([good, mid, blind]))
    rev = per_agent_revenue(C, D, cl, [1, 1, 1])
    assert rev[0] > rev[2], f"預測準的該賺比較多,得 {rev[0]:.1f} vs {rev[2]:.1f}"
    assert rev[0] >= rev[1] >= rev[2], f"報酬須照預測品質排序,得 {rev.round(1)}"
    # ② 共用信念要退回舊行為(向後相容):傳 1-D 陣列 == 全員同一份
    Cs, Ds, cls_, _ = solve_day(p, [1, 1, 1], lam=0.5, belief=mid)
    Ch, Dh, clh, _ = solve_day(p, [1, 1, 1], lam=0.5, belief=np.array([mid, mid, mid]))
    assert np.allclose(Cs, Ch) and np.allclose(cls_, clh), (
        "共用 belief 應等同每家都傳同一份"
    )
    # ③ 策略維度:每家可以有自己的 br(這裡用同一個驗管線,v3 會傳真的 Cournot 進來)
    same = lambda seen, lam_wi: perfect(seen)  # noqa: E731
    Cb, Db, clb, _ = solve_day(p, [1, 1, 1], lam=0.5, br=[same, same, same])
    Cd, Dd, cld, _ = solve_day(p, [1, 1, 1], lam=0.5)
    assert np.allclose(Cb, Cd), "list[br] 全傳同一個應等同預設"
    print(
        f"  v2 異質 ok: 預測品質 完美€{rev[0]:.0f} > 雜訊€{rev[1]:.0f} > 瞎€{rev[2]:.0f}"
        "(同體量,差異純粹來自資訊)"
    )


def _demo_nonlinear_impact(p):
    """`impact=` 開關的 self-check(見 `agents/fringe.py` 的 `nonlinear_impact`)。
    本地 import fringe(需要 sklearn),不用這個開關的呼叫端不會被迫裝它。

    驗兩件事:①車隊小、x 落在曲線平坦段時,非線性應該幾乎等於線性(近似沒被破壞,
    這是開關能安全預設關閉的理由);②車隊大到把 x 推進曲線陡段時,非線性衝擊要比
    常數線性外推更大(這正是要開這個開關的理由,見 MULTI_AGENT_MARKET.md §3.9)。"""
    import pandas as pd

    sys.path.insert(0, os.path.dirname(__file__))
    from fringe import fit_fringe, nonlinear_impact

    # 合成一條凸 fringe(曲棍球桿:低段平、x 大後翹陡),不依賴真實資料
    rng = np.random.default_rng(2)
    x = rng.uniform(-1000, 3500, 20000)
    price = 20 + 0.01 * x + 8e-6 * np.clip(x, 0, None) ** 2 + rng.normal(0, 5, len(x))
    fr = fit_fringe(pd.DataFrame({"price": price, "x": x}))

    lam_flat = 0.01  # 平坦段(x 遠小於 2000)大約的局部斜率,當線性對照組
    x_flat = np.full(len(p), 200.0)
    C0, D0, cl0, _ = solve_day(p, [1, 1, 1], lam=lam_flat)
    C1, D1, cl1, _ = solve_day(
        p, [1, 1, 1], lam=lam_flat, impact=nonlinear_impact(x_flat, fr)
    )
    assert np.allclose(cl0, cl1, atol=3), (
        f"平坦段、小車隊時非線性應接近線性,差 {np.abs(cl0 - cl1).max():.2f}"
    )

    x_steep = np.full(len(p), 2800.0)  # 陡段
    Cs, Ds, cls_, _ = solve_day(
        p, [80, 80, 80], lam=lam_flat, impact=nonlinear_impact(x_steep, fr)
    )
    Cl, Dl, cll, _ = solve_day(p, [80, 80, 80], lam=lam_flat)  # 同體量,仍用常數斜率
    h = _peak_hour(p)
    assert abs(p[h] - cls_[h]) > abs(p[h] - cll[h]), (
        "陡段、大車隊時非線性衝擊應比常數線性外推更大(不能用固定 λ 的地方)"
    )
    print(
        f"  impact= 開關 ok: 平坦段小車隊≈線性(差€{np.abs(cl0 - cl1).max():.1f});"
        f"陡段大車隊非線性壓尖峰€{p[h] - cls_[h]:.0f} > 線性外推€{p[h] - cll[h]:.0f}"
    )


def main():
    demo()
    price = load_prices("DK1")
    wk = price.index.tz_localize(None).to_period("W")  # 週窗:SoC 跨天連續,不漏財
    by_week = {k: g.values for k, g in price.groupby(wk) if len(g) >= 160}
    # 挑「正常波動週」:價格為正、無稀缺離群尖峰(0<谷,峰<€200),取週內價差最大
    normal = {k: p for k, p in by_week.items() if p.min() > 0 and p.max() < 200}
    week = max(normal, key=lambda k: np.ptp(normal[k]))
    p = normal[week]
    h = _peak_hour(normal[week])
    # A 方案 placeholder 體量分布:10 家,前 2 大合計 ~35%(對齊 Ørsted+Vattenfall),
    # 總量=10(和同質 v2 可比)。真數字待接 BRP/HHI(LITERATURE.md C1)。
    w = np.array([1.8, 1.7, 1.2, 1.0, 0.8, 0.8, 0.7, 0.6, 0.6, 0.8])
    print(
        f"\n示範週 {week}(DK1):{len(w)} 家異質電池,前2大={w[:2].sum() / w.sum():.0%},尖峰原始價 €{p[h]:.0f}\n"
    )
    print(
        f"{'λ':>5} {'回合':>4} {'尖峰出清價':>10} {'尖峰壓低':>9} {'車隊總報酬/週':>13} {'報酬消散':>9}"
    )
    rev0 = None
    for lam in (0.0, 1.0, 3.0, 6.0, 12.0):
        C, D, cleared, used = solve_day(p, w, lam)
        fleet = fleet_revenue(C, D, cleared, w)
        if rev0 is None:
            rev0 = fleet
        cut = p[h] - cleared[h]
        diss = (rev0 - fleet) / rev0 if rev0 else 0
        print(
            f"{lam:>5.1f} {used:>4} {cleared[h]:>9.1f}€ {cut:>8.1f}€ {fleet:>12,.0f} {diss:>8.0%}"
        )
    # λ=6 看異質:大玩家 vs 小玩家的每單位體量報酬
    C, D, cleared, _ = solve_day(p, w, 6.0)
    print("\nλ=6 各家(體量 / 週報酬 / 每單位體量報酬):")
    for i in np.argsort(-w):
        r = w[i] * settle(C[i], D[i], cleared)
        print(
            f"  家{i:>2}  體量 {w[i]:.1f}   報酬 €{r:>7,.0f}   每單位 €{r / w[i]:>6,.0f}"
        )
    print(
        "\n讀法:λ 越大 → 大家搶賣尖峰把它壓得越低(尖峰壓低↑)、每家報酬越少(競爭租值消散)。"
    )
    print("λ=0 = 純 price-taker(各做各的、互不影響);λ>0 才有真正的多 agent 互動。")
    print(
        "這也印證前面的理論:小電池的 λ 效果小,要 agent 夠大/夠多、或 λ 夠大,競爭才咬得動。"
    )
    print(
        "\n注意:這裡每家都不內化自身衝擊 → 大玩家會壓垮自己的價。v3_cournot.py 修掉它。"
    )


if __name__ == "__main__":
    main()
