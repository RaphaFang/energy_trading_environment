"""v3 — Cournot:agent 內化自身衝擊,最佳反應從 LP 升級成 QP。

v2 的每家都是 price-taker:優化時當自己動不了價,結算卻要付全體衝擊 → 大玩家一動就
壓垮自己的價(自我蠶食),跑出「大玩家每單位反而賺最少」的 artifact。v3 讓每家在自己的
目標裡加一項 −λ·w_i·Σ(自己淨量)²,大玩家自制,artifact 就消失。

實作上 v3 不改 v2:它只是換一種最佳反應,用 solve_day(..., br=cournot_br) 傳進去。

本檔還放三尺階梯的另外兩把錨(都是 Cournot 的特例,所以同檔):
  cartel(M)      一個規劃者統管全隊、內化全體衝擊 → 聯合利潤上界
  competitive(C) 拆成 n 個對稱小廠 → 每廠市場力 → 0 → 下界
  (中間的 N = Nash 就是 solve_day(..., br=cournot_br))
恆有 C ≤ N ≤ M;collusion 指標 Δ = (Π_obs − Π_N)/(Π_M − Π_N) 拿 M/N 當錨。
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from v1_single import perfect, settle  # noqa: E402
from v2_multi import fleet_revenue, solve_day  # noqa: E402


def cournot_br(seen, lam_wi, iters=100):
    """Cournot 最佳反應:max Σ seen·(d−c) − lam_wi·Σ(c−d)²(lam_wi=λ·自己體量)。
    多的二次項 = 內化「自己一動就推移出清價」→ 大玩家自制,不再壓垮自己的價。
    可行集 == perfect 的 LP polytope,所以用 Frank-Wolfe:線性化後的 oracle 剛好是
    perfect(含自身衝擊的邊際價),閉式線搜 → 不必裝 QP solver。lam_wi=0 就退回純 LP。

    簽名 (seen, lam_wi) 對齊 solve_day 的 br= → 可直接 solve_day(..., br=cournot_br)。"""
    c, d = perfect(seen)  # 從 price-taker LP 解起步
    if lam_wi <= 0:
        return c, d
    for _ in range(iters):
        u = c - d
        vc, vd = perfect(seen + 2 * lam_wi * u)  # 邊際價 = 平均價 + 自身衝擊的邊際
        dc, dd = vc - c, vd - d
        delta = dc - dd
        Cq = lam_wi * float(delta @ delta)  # 1D 二次係數(−t²)
        Bq = -float(seen @ delta) - 2 * lam_wi * float(
            u @ delta
        )  # 頂點方向上升量=FW gap
        if (
            Bq <= 1e-7
        ):  # 沒有上升方向 → 已最優(小 λ 下 LP 退化不會空轉,用 gap 不用頂點距)
            break
        t = 1.0 if Cq <= 1e-12 else min(1.0, max(0.0, Bq / (2 * Cq)))
        c, d = c + t * dc, d + t * dd
    return c, d


def nash(price, weights, lam, **kw):
    """N = Nash benchmark:少數大廠各自 Cournot 最佳反應。就是 v2 換上 Cournot 的 br。"""
    return solve_day(price, weights, lam, br=cournot_br, **kw)


def cartel(price, weights, lam):
    """M = 壟斷/卡特爾 benchmark:一個規劃者統管全隊,內化**全體** λ·ΣW 衝擊 → 聯合利潤上界。
    攤開後就是「own weight = 總體量」的 Cournot,一個 QP 解完、無迭代:
      max Σ act·(d−c) − λ·(ΣW)·Σ(c−d)²   (全隊同質 → 對稱解最優,一條 per-unit 排程套全隊)
    回傳 per-unit 排程 c/d、出清價、聯合利潤。"""
    w = np.asarray(weights, float)
    c, d = cournot_br(np.asarray(price, float), lam * w.sum())
    cleared = price + lam * w.sum() * (c - d)
    joint = float(w.sum() * settle(c, d, cleared))
    return c, d, cleared, joint


def competitive(price, weights, lam, n_firms=30):
    """C = 競爭 benchmark:把總體量拆成 n_firms 個對稱小廠,跑它們的 Cournot(廠越多 →
    每廠市場力 λ·ΣW/n → 0 → 越接近 price-taking)。用 solve_day 的 Gauss-Seidel(逐一更新、
    自帶阻尼)算 → 穩定、聯合利潤 ≥0。
    比「零內化的天真 price-taker」乾淨:後者在大 λ·ΣW 會倒賠(理性 price-taker 不該虧錢),
    那是優化看 act、結算卻付全體衝擊的不對稱病;拆成小廠讓每廠面對別人的衝擊就治好了。
    廠數越多聯合利潤越低,構成 C ≤ N ≤ M 的下錨。"""
    wt = np.asarray(weights, float).sum()
    w = np.full(n_firms, wt / n_firms)
    C, D, cleared, _ = nash(np.asarray(price, float), w, lam)
    return None, None, cleared, fleet_revenue(C, D, cleared, w)


def demo():
    # λ=0 應等同 LP;高 λ 下大玩家自制 → 淨量體積小於 price-taker(v2)
    # 用小價差(spread~8)才看得到自制:大價差時套利值 >> 罰項,電池仍打滿(bang-bang)
    pf = np.array([12, 12, 12, 20, 20, 20, 12, 12] * 3, float)  # 溫和價差
    w2 = [3.0, 1.0]  # 一大一小
    Cc0, Dc0, _, _ = nash(pf, w2, lam=0.0)
    Cl0, Dl0, _, _ = solve_day(pf, w2, lam=0.0)
    assert np.allclose(Cc0, Cl0) and np.allclose(Dc0, Dl0), "λ=0:Cournot 應退回 LP"
    Cc, Dc, _, _ = nash(pf, w2, lam=8.0)
    Cv, Dv, _, _ = solve_day(pf, w2, lam=8.0)
    vol_big_c = np.abs(Cc[0] - Dc[0]).sum()  # 大玩家 Cournot 淨量體積
    vol_big_v = np.abs(Cv[0] - Dv[0]).sum()  # 大玩家 price-taker 淨量體積
    assert vol_big_c < vol_big_v, "高 λ:Cournot 大玩家應自制(交易量 < price-taker)"
    print(
        f"  v3 ok: Cournot λ=0≡LP;λ=8 大玩家交易量 {vol_big_v:.2f}→{vol_big_c:.2f}(自制)"
    )
    # 三尺階梯:聯合利潤必須 0 ≤ C(Walrasian 競爭) ≤ N(Nash) ≤ M(卡特爾)。
    # 用大體量(GW 級 = 大 λ·w)才驗得到,順便守住「競爭不倒賠」——舊 naive price-taker 會。
    wm = [15.0, 10.0, 8.0, 7.0]  # ~40MW 隊,λ·ΣW 夠大讓市場力咬得動
    lam_m = 0.5
    _, _, _, jC = competitive(pf, wm, lam_m, n_firms=8)  # 8>4 廠即足證 C<N;省時
    Cn2, Dn2, cln2, _ = nash(pf, wm, lam_m)
    jN = fleet_revenue(Cn2, Dn2, cln2, wm)
    _, _, _, jM = cartel(pf, wm, lam_m)
    assert jM >= jN - 1e-6 >= jC - 1e-6 >= -1e-6, (
        f"聯合利潤須 0≤C≤N≤M,得 C{jC:.1f}/N{jN:.1f}/M{jM:.1f}"
    )
    print(f"  三尺 ok: 卡特爾 €{jM:.0f} ≥ Nash €{jN:.0f} ≥ 競爭 €{jC:.0f} ≥ 0")


if __name__ == "__main__":
    demo()
