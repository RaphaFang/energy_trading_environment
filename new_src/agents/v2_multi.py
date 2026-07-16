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


def solve_day(price, weights, lam, rounds=15, tol=1e-3, belief=None, br=None):
    """一週的均衡:輪流(Gauss-Seidel)最佳反應。weights[i] = 玩家 i 的體量(電池數/權重)。
    每家每 MWh 排程相同,但淨量按體量放大 → 大玩家一動就撼動出清價。
    回傳每家「每單位體量」的排程 C/D、出清價、用了幾回合。

    belief=None(預設)= v2.1 上帝視角:agent 對「真實價」最佳反應。
    belief=預測價(如 LightGBM)= v2.2:agent 只信自己的預測來排程(price + λ×別人),
    但**結算仍用真實出清價**(真實價 + λ×實際淨量)→ 競爭+預測誤差合體。

    br(seen, lam_wi) -> (c, d) = 最佳反應函式,預設 price-taker(吃 perfect 的 LP、
    無視自己的 λ·w_i)。v3 傳 Cournot 版進來內化自身衝擊 → 版本演進不用改這支。"""
    if br is None:  # 預設 = v2 price-taker:不內化自身衝擊,忽略 lam_wi

        def br(seen, lam_wi):
            return perfect(seen)

    w = np.asarray(weights, float)
    bel = price if belief is None else np.asarray(belief, float)  # 排程依據的信念價
    N, H = len(w), len(price)
    C = np.zeros((N, H))
    D = np.zeros((N, H))
    used = rounds
    for r in range(rounds):
        change = 0.0
        for i in range(N):  # 輪流,馬上看到別人這輪的新決定
            net = (w[:, None] * (C - D)).sum(0)  # 全體體量加權淨量
            others = net - w[i] * (C[i] - D[i])  # 扣掉自己 = 別人的加權淨量
            seen = (
                bel + lam * others
            )  # 我信的價被別人推移(v2.2 用預測價、v2.1 用真實價)
            c, d = br(seen, lam * w[i])
            change += np.abs(c - C[i]).sum() + np.abs(d - D[i]).sum()
            C[i], D[i] = c, d
        if change < tol:  # 沒人想再改 → 收斂
            used = r + 1
            break
    cleared = price + lam * (w[:, None] * (C - D)).sum(0)  # 出清價(真實價+全體加權衝擊)
    return C, D, cleared, used


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
