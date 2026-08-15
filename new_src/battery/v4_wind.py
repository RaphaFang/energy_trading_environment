"""v4 — 風力情境:一群同體量風電商,其中部分額外裝一顆電池。

問的是「電池對風電商值多少錢」,答案有兩層:
  溢價 externality 之外的 batt_premium = 裝電池的人多賺的(純套利)
  externality                          = 電池打平價格對**沒裝**電池的純風商的外溢
風與價負相關(DK1 實測 −0.47)→ 電池充在「風多、價便宜」的時段抬升低價 → 對純風商是**正**
外部性。而採用率越高、電池彼此競爭越兇 → 溢價消散。

風的價格衝擊不在這裡重算:price 用真實出清價(已含全體風力),電池的 λ 只加在電池淨量上。
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from v1_single import settle  # noqa: E402
from v2_multi import solve_day  # noqa: E402
from v3_cournot import cournot_br  # noqa: E402


def wind_scenario(price, wind, n_batt, batt_mw, lam, cournot=False):
    """n_batt 家裝電池(各 batt_mw MW / 4h),其餘是純風商。
    price=真實價(已含全體風力→風的價格衝擊不重複算);wind=每家風力出力(MW,同 shape)。
    電池只套利價格(併網,和自己的風無關),彼此競爭(solve_day);cleared=price+λ×電池淨量。
    cournot=True → 電池改用 v3 的 Cournot 最佳反應(內化自身衝擊)。
    回傳 dict:純風商每 MW 風收益、風+電池商收益、電池溢價(=套利)、電池對純風商的外部性。"""
    price = np.asarray(price, float)
    wind = np.asarray(wind, float)
    if n_batt > 0:
        w = np.full(
            n_batt, float(batt_mw)
        )  # 體量=電池 MW(settle 是每 1MW/4MWh,線性放大)
        C, D, cleared, _ = solve_day(price, w, lam, br=cournot_br if cournot else None)
        arb_per_batt = batt_mw * settle(
            C[0], D[0], cleared
        )  # 每家電池套利(同質→取第0家)
    else:
        cleared = price.copy()
        arb_per_batt = 0.0
    wind_rev = float(cleared @ wind)  # 風商賣風 at 出清價(純風商 & 電池商的風部分同值)
    wind_rev_nobatt = float(price @ wind)  # 沒有任何電池時的風收益(比較基準)
    return dict(
        wind_only=wind_rev,  # 純風商收益
        wind_batt=wind_rev + arb_per_batt,  # 風+電池商收益
        batt_premium=arb_per_batt,  # 溢價 = 純套利
        externality=wind_rev - wind_rev_nobatt,  # 電池打平價格對純風商的外溢
    )


def demo():
    # 風與價負相關時,電池充「便宜(風多)時段」抬升低價 → 對純風商是正外部性
    ph = np.array([20, 20, 50, 50] * 6, float)  # 風多時便宜、風少時貴
    wd = np.array([3, 3, 0, 0] * 6, float)  # 風出力與價負相關
    r4 = wind_scenario(ph, wd, n_batt=5, batt_mw=2.0, lam=0.5)
    assert r4["batt_premium"] > 0, "電池套利應為正"
    assert r4["externality"] > 0, "電池充便宜(風多)時抬升低價 → 純風商受惠"
    print(
        f"  v4 ok: 電池溢價 €{r4['batt_premium']:.0f}、對純風商外部性 €{r4['externality']:.0f}(正)"
    )
    # 採用率越高 → 電池越多、彼此競爭 → 每家溢價消散
    prem = [wind_scenario(ph, wd, n, 2.0, 0.5)["batt_premium"] for n in (1, 5, 10)]
    assert prem[0] > prem[-1], "採用率上升,電池溢價應消散"
    print(f"  v4 消散 ok: 1家 €{prem[0]:.0f} → 10家 €{prem[-1]:.0f}")


if __name__ == "__main__":
    demo()
