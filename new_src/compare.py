"""統一比較 harness:把 v1(perfect/naive)、統計模型(Ridge/Lasso/LightGBM/naive-24h)、
v2 多 agent 競爭,鎖在**同一批 testing 窗**上跑,共同標尺 = 單顆電池 €/窗。

綁 models/ 與 agents/ 的頂層入口,所以放 new_src/ 根目錄,不屬於任一邊。

兩把不同的尺(別混):
  rMAE   = 預測準度 = MAE(模型) / MAE(naive-24h)   ← 分母是「照抄昨天」的誤差
  佔天花板 = 錢     = €(模型) / €(perfect)          ← 分母是完美預知的報酬
錢的算法:每個預測模型「用預測價排程(perfect LP)、用真實價結算」= 照它的預測交易賺多少。

用法:python new_src/compare.py [W|M]   (W=每週, M=每月, 預設 M)
測試期 = SPLIT 之後(統計模型沒看過 → 不 leak),全部窗都跑,看分布不是看單一週。
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from agents.v1_single import naive, naive_hours, perfect, settle  # noqa: E402
from agents.v2_multi import solve_day  # noqa: E402
from models.forecast import fit_predict, load_training, rmae  # noqa: E402

ZONE = "DK1"
MIN_H = {"W": 160, "M": 600}  # 殘窗(頭尾不完整)跳掉
# λ 來源:agents/fringe.py 的 structural_lambda()(多變數偏導數,DK1 中位 0.0042)。
# 舊值 0.037 是單變數 OLS 斜率,把丹麥/德國的天氣相關性算到本地頭上 → 高估約 8 倍。
# 掃 10×/100× 看規模效應:λ×淨量 才是關鍵,λ=0.4×10MW ≡ λ=0.004×1GW。
LAMS = (0.004, 0.04, 0.4)  # 結構估計、10×、100×(λ=0 恆等於天花板,不用跑)
# A 方案異質體量:10 家,前 2 大合計 35%(對齊 Ørsted+Vattenfall),總量=10
W = np.array([1.8, 1.7, 1.2, 1.0, 0.8, 0.8, 0.7, 0.6, 0.6, 0.8])


def run_window(act, idx, preds_w, chg, dis):
    """一個窗(週/月)內,各策略的單顆電池報酬(€)。"""
    r = {"perfect": settle(*perfect(act), act)}
    for name, p in preds_w.items():
        r[name] = settle(*perfect(p), act)  # 照預測排程,真實價結算
    fc = preds_w["LightGBM"]  # v2.2 的信念價 = 最佳預測模型
    for lam in LAMS:
        # v2.1 上帝視角:agent 對真實價排程
        C, D, cleared, _ = solve_day(act, W, lam)
        r[f"v2.1 λ={lam}"] = float(
            np.mean([settle(C[i], D[i], cleared) for i in range(len(W))])
        )
        # v2.2 寫實:agent 對 LightGBM 預測價排程,真實出清價結算
        C, D, cleared, _ = solve_day(act, W, lam, belief=fc)
        r[f"v2.2 λ={lam}"] = float(
            np.mean([settle(C[i], D[i], cleared) for i in range(len(W))])
        )
    r["naive 固定時段"] = settle(*naive(pd.Series(act, index=idx), chg, dis), act)
    return r


def main():
    freq = (sys.argv[1] if len(sys.argv) > 1 else "M").upper()
    f = fit_predict(load_training(ZONE))
    te_idx, actual, preds = f["te_idx"], f["actual"], f["preds"]
    chg, dis = naive_hours(f["tr_price"], k=4)
    per = te_idx.tz_localize(None).to_period(freq)
    rm = rmae(actual, preds)  # 全測試期 rMAE(預測準度尺)

    out = {}
    for k in per.unique():
        m = np.asarray(per == k)
        if m.sum() < MIN_H[freq]:
            continue
        out[k] = run_window(
            actual[m], te_idx[m], {n: p[m] for n, p in preds.items()}, chg, dis
        )
    t = pd.DataFrame(out).T.sort_index()  # 列=窗, 欄=策略
    pct = t.div(t["perfect"], axis=0)

    unit = {"W": "週", "M": "月"}[freq]
    span = f"{t.index[0]} ~ {t.index[-1]}"
    print(f"\n=== {ZONE} 測試期 {span}({len(t)} 個{unit})|單顆電池 4MWh/1MW/η=0.9 ===")
    print(f"\n【總表】各策略跨全部{unit}的合計報酬\n")
    print(
        f"{'策略':<20}{'rMAE':>7}{'總€':>10}{f'€/{unit}':>9}{'佔天花板':>9}{'最差窗':>8}{'最好窗':>8}"
    )
    print("-" * 71)
    for c in t.sum().sort_values(ascending=False).index:
        r = f"{rm[c]:.2f}" if c in rm else ("0.00" if c == "perfect" else "—")
        print(
            f"{c:<20}{r:>7}{t[c].sum():>10,.0f}{t[c].mean():>9,.0f}"
            f"{t[c].sum() / t['perfect'].sum():>8.0%}{pct[c].min():>8.0%}{pct[c].max():>8.0%}"
        )

    print(f"\n【逐{unit}】佔天花板 %(看穩不穩,不是只看一個{unit})\n")
    cols = [c for c in t.columns if c != "perfect"]
    print(f"{'窗':<10}{'天花板€':>9}" + "".join(f"{c[:9]:>10}" for c in cols))
    print("-" * (19 + 10 * len(cols)))
    for k in t.index:
        print(
            f"{str(k):<10}{t.loc[k, 'perfect']:>9,.0f}"
            + "".join(f"{pct.loc[k, c]:>10.0%}" for c in cols)
        )
    print(
        "\nrMAE = 預測準度(分母 = naive-24h 的 MAE);佔天花板 = 錢(分母 = perfect 的 €)。兩把尺互不相干。"
    )


if __name__ == "__main__":
    main()
