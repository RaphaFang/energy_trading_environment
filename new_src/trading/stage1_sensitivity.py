"""階段 1 的敏感度掃描 —— **把「彈性值 12.3 M€/年」那個水準的可信範圍框出來**。

━━━ 為什麼非做不可 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

階 1 報出來的 12.3 M€/年,建在兩個**不是實測**的參數上:

    Cb  背壓線斜率  —— 用 AMV 的**實測電熱比**當代理(0.235 / 0.321)。
                       真正的 Cb 是 P/Q 的**下界**,而實測值是個**平均運轉點**
                       → 真值只會**更低**,不會更高。所以要往下掃。
    Cv  抽汽損失係數 —— **只有 DEA 目錄值 0.14,沒有實測**(背壓機組有實測母體,抽汽的沒有)。
                       往上下各掃 50%。

🔑 **分母(地板)一律用「歷史行為基準」= 貼著實測電熱比跑,它與 Cb / Cv 無關。**
   如果地板改用「物理背壓線」,Cb 調低地板就跟著掉,差額會被灌水 —— 那是自己騙自己。

━━━ 這支要回答的三個問題 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 12.3 M€ 這個**水準**在合理參數範圍內會擺到哪裡?(→ 報區間,不報點估計)
2. **89% 這個比值**站不站得住?(比值的分子分母共用參數,應該穩很多 —— 要驗)
3. 哪一個參數比較要命?(→ 之後要不要花力氣去要實測 Cv)

用法:python new_src/trading/stage1_sensitivity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "new_src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage1_lp import (  # noqa: E402
    OUT, SPLIT, _unit_arrays, _units_measured, build_panel, run_strategy,
)

CB_MULT = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]   # × 實測電熱比;1.00 = 階 1 的基準設定
CV_GRID = [0.070, 0.105, 0.140, 0.175, 0.210]    # DEA 目錄值 0.14 的 0.5×–1.5×


def scan(h: pd.DataFrame, u: pd.DataFrame, year: int) -> pd.DataFrame:
    rows = []
    yrs = (h.index.max() - h.index.min()).days / 365.25
    for cb_m in CB_MULT:
        for cv in CV_GRID:
            units = _unit_arrays(u, year, cb_mult=cb_m, cv=cv)
            top = run_strategy(h, units, "opt", "price").profit.sum()
            fc = run_strategy(h, units, "opt", "price_fc").profit.sum()
            flr = run_strategy(h, units, "hist").profit.sum()
            gap = (top - flr) / yrs / 1e6
            rows.append({
                "Cb 倍數": cb_m,
                "Cv": cv,
                "彈性價值 M€/年": gap,
                "用預測 M€/年": (fc - flr) / yrs / 1e6,
                "回收 %": 100 * (fc - flr) / (top - flr) if top > flr else np.nan,
                "AMV4 邊際成本": units["AMV4"]["mc"],
            })
    return pd.DataFrame(rows)


def selfcheck(t: pd.DataFrame) -> None:
    # ① 基準格必須重現階 1 的數字(Cb 倍數 1.00 × Cv 0.14)
    base = t[(t["Cb 倍數"] == 1.00) & (t["Cv"] == 0.140)].iloc[0]
    assert abs(base["彈性價值 M€/年"] - 12.3) < 0.5, (
        f"基準格 {base['彈性價值 M€/年']:.2f} M€ 對不上階 1 報的 12.3 —— 掃描接錯了")

    # ② 🔑 Cb 調低 = 機組能往下跑得更多 = 彈性只會**變大**,不會變小(單調性)
    for cv, g in t.groupby("Cv"):
        v = g.sort_values("Cb 倍數")["彈性價值 M€/年"].to_numpy()
        assert (np.diff(v) <= 1e-6).all(), (
            f"Cv={cv}: Cb 調低反而讓彈性變小 —— 可行域接反了({v.round(2)})")

    # ③ 回收率必須落在 0–100(用預測不可能贏過完美預知,也不該輸給地板)
    assert t["回收 %"].between(0, 100).all(), "回收率跑出 0–100 之外 → 管線壞了"


def main() -> None:
    h = build_panel()
    h = h[h.index >= pd.Timestamp(SPLIT, tz=h.index.tz)]
    u = _units_measured()
    year = int(h.attrs["year"])
    t = scan(h, u, year)
    selfcheck(t)

    print(f"\n═══ 階段 1 敏感度掃描({len(CB_MULT)}×{len(CV_GRID)} = {len(t)} 格)═══")
    print("\n── 彈性價值 M€/年(分母 = 歷史行為基準,與參數無關)──")
    print(t.pivot(index="Cb 倍數", columns="Cv", values="彈性價值 M€/年")
          .round(1).to_string())
    print("\n── 回收 %(用模型 A 的預測 ÷ 完美預知)──")
    print(t.pivot(index="Cb 倍數", columns="Cv", values="回收 %").round(1).to_string())

    v, r = t["彈性價值 M€/年"], t["回收 %"]
    base = t[(t["Cb 倍數"] == 1.00) & (t["Cv"] == 0.140)].iloc[0]
    print(f"\n基準格(Cb=實測電熱比、Cv=0.14):彈性 {base['彈性價值 M€/年']:.1f} M€/年、"
          f"回收 {base['回收 %']:.1f}%")
    print(f"🔴 彈性價值全域範圍:{v.min():.1f} – {v.max():.1f} M€/年"
          f"(最大 ÷ 最小 = {v.max() / v.min():.1f} 倍)")
    print(f"✅ 回收率全域範圍:{r.min():.1f} – {r.max():.1f} %"
          f"(全距只有 {r.max() - r.min():.1f} pp)")

    # 哪個參數比較要命:固定另一個參數,看這個參數掃出來的全距(對所有格取平均)
    #   ⚠️ 命名照「變動的是誰」:固定 Cv 這一欄裡變動的是 Cb → 那是 Cb 的貢獻。
    d_cb = t.groupby("Cv")["彈性價值 M€/年"].agg(lambda x: x.max() - x.min()).mean()
    d_cv = t.groupby("Cb 倍數")["彈性價值 M€/年"].agg(lambda x: x.max() - x.min()).mean()
    print(f"\n彈性價值的全距:掃 Cb 平均 {d_cb:.1f} M€ / 掃 Cv 平均 {d_cv:.1f} M€"
          f"  → **{'Cb' if d_cb > d_cv else 'Cv'} 比較要命**")

    p = OUT / "stage1_sensitivity.csv"
    t.to_csv(p, index=False)
    print(f"\n✓ 寫出 {p}")


if __name__ == "__main__":
    main()
