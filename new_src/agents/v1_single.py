"""v1 — 單顆電池、price-taker、無 λ。也是 v2/v3/v4 共用的地基。

一顆電池(容量 E、功率 P、往返效率 η)當 price-taker,用真實 DK 隔日電價結算。
policy(當日24小時價) -> 每小時充/放 MW。三種參考策略:
  - perfect  : 完美預知,LP 最佳排程 = 天花板
  - naive    : 固定便宜時段充、貴時段放 = 地板
  - forecaster-driven : 用預測價排 perfect 的 LP、真實價結算(見 compare.py)

價格死(price-taker,歷史價不動);會流動的是 SoC。上層版本疊在這之上:
  v2_multi.py   λ 價格衝擊 + 輪流最佳反應(成交價 = 歷史價 + λ×全體淨量)
  v3_cournot.py agent 內化自身衝擊(LP → QP)+ 卡特爾/競爭 benchmark
  v4_wind.py    風電商情境
它們共用這裡的 perfect(LP oracle)與 settle(唯一算效率/可行性的地方)。
"""

import glob
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.optimize import linprog

E_MWH, P_MW, ETA = 4.0, 1.0, 0.90  # 4 小時充滿、往返效率 90%
RT = np.sqrt(ETA)  # 充/放各半的損耗


def load_prices(area: str) -> pd.Series:
    (f,) = glob.glob(f"new_data/price/price_{area.lower()}_*.parquet")
    df = pd.read_parquet(f)
    s = pd.Series(df["SpotPriceEUR"].values, index=pd.DatetimeIndex(df["HourUTC"]))
    return s.dropna().sort_index()


def settle(charge: np.ndarray, discharge: np.ndarray, price: np.ndarray) -> float:
    """報酬 = 賣電收入 − 買電支出(€)。走一遍 SoC:充電存 RT·c、放電抽 d/RT,
    並夾住可行範圍(存不下的不充、沒存的不能賣)——效率/可行性只在這裡算一次。"""
    soc = 0.0
    cash = 0.0
    for c, d, p in zip(charge, discharge, price):
        c_act = max(0.0, min(c, (E_MWH - soc) / RT))  # 不能超過容量
        soc += RT * c_act
        d_act = max(0.0, min(d, soc * RT))  # 不能賣超過存量
        soc -= d_act / RT
        cash += p * (d_act - c_act)
    return float(cash)


def perfect(price: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """完美預知的最佳排程(LP)。x = [charge, discharge, soc](各 n 個)。
    最大化 Σ price·(d−c);soc_t = soc_{t−1} + RT·c_t − d_t/RT ∈ [0,E];窗終歸零。
    SoC 當決策變數 → 約束是稀疏 bidiagonal(每列 3 個非零),換掉舊的稠密下三角累加,
    LP 規模從 O(n²) 降到 O(n):168h 的窗快、720h 的月窗才跑得動。"""
    n = len(price)
    cobj = np.concatenate([price, -price, np.zeros(n)])  # min → c 係數 +p、d 係數 −p
    i = np.arange(n)
    # soc_t − soc_{t−1} − RT·c_t + d_t/RT = 0
    A_eq = sp.coo_matrix(
        (
            np.concatenate(
                [np.full(n, -RT), np.full(n, 1 / RT), np.ones(n), -np.ones(n - 1)]
            ),
            (
                np.concatenate([i, i, i, i[1:]]),  # 列 = 每個小時一條
                np.concatenate(
                    [i, n + i, 2 * n + i, 2 * n + i[:-1]]
                ),  # 欄 = c, d, soc_t, soc_{t−1}
            ),
        ),
        shape=(n, 3 * n),
    ).tocsr()
    # 充完當下也不能爆容量:soc_{t−1} + RT·c_t ≤ E。少了這條,LP 會在負價小時「同一小時
    # 先充爆再放掉」偷分,而 settle 會把它夾掉 → 天花板虛高、agent 反而「贏過天花板」。
    # 有了這條,LP 可行集 == settle 可行集(夾取永不觸發)。
    A_ub = sp.coo_matrix(
        (
            np.concatenate([np.full(n, RT), np.ones(n - 1)]),
            (np.concatenate([i, i[1:]]), np.concatenate([i, 2 * n + i[:-1]])),
        ),
        shape=(n, 3 * n),
    ).tocsr()
    bounds = [(0, P_MW)] * (2 * n) + [(0, E_MWH)] * (n - 1) + [(0, 0)]  # 窗終 SoC=0
    r = linprog(
        cobj,
        A_ub=A_ub,
        b_ub=np.full(n, E_MWH),
        A_eq=A_eq,
        b_eq=np.zeros(n),
        bounds=bounds,
        method="highs",
    )
    x = r.x if r.success else np.zeros(3 * n)
    return x[:n], x[n : 2 * n]


def naive(
    price: pd.Series, chg=(1, 2, 3, 4), dis=(18, 19, 20, 21)
) -> tuple[np.ndarray, np.ndarray]:
    """固定 hour-of-day 排程:每天同樣便宜時段充、貴時段放,SoC 在整個窗(週)內連續。
    時段由 naive_hours 從訓練期學(不是手挑)。需帶時間索引的 Series(才知道是幾點)。"""
    hours = np.asarray(price.index.hour)
    c = np.where(np.isin(hours, chg), P_MW, 0.0)
    d = np.where(np.isin(hours, dis), P_MW, 0.0)
    return c, d


def naive_hours(train_price: pd.Series, k: int = 6) -> tuple[list, list]:
    """有根據的固定時段:用訓練期「平均每小時價格輪廓」挑——平均最便宜 k 小時充、
    最貴 k 小時放。只看訓練期平均、不看當天實際價(leak-safe),仍是固定 baseline。
    ponytail: k=6 > 電池 4 小時容量,settle 會把超出的夾掉(多標的時段不會硬塞爆)。"""
    prof = train_price.groupby(train_price.index.hour).mean()  # 24 小時平均輪廓
    chg = sorted(prof.nsmallest(k).index.tolist())
    dis = sorted(prof.nlargest(k).index.tolist())
    assert prof[dis].mean() > prof[chg].mean(), "放電時段平均價應高於充電時段"
    return chg, dis


def backtest(price: pd.Series, policy, freq: str = "W") -> pd.Series:
    """逐週跑 policy,回傳每週報酬(€)。SoC 在一週(168h)內連續、週末歸零——
    跨天不再漏財(晚上充的電隔天早上放得掉)。policy 收到帶索引的 Series。"""
    rev = {}
    wk = price.index.tz_localize(None).to_period(freq)  # 去 tz 免警告
    for key, g in price.groupby(wk):
        if len(g) < 24:  # ponytail: 跳過太短的殘週
            continue
        c, d = policy(g)
        rev[key.to_timestamp()] = settle(c, d, g.values)
    return pd.Series(rev).sort_index()


def _metrics(rev: pd.Series, ppy: float = 52) -> dict:
    ann = rev.mean() * ppy  # ppy = 每年期數(週 → 52)
    sharpe = rev.mean() / rev.std() * np.sqrt(ppy) if rev.std() > 0 else 0.0
    return dict(total=rev.sum(), per_year=ann, sharpe=sharpe, n=len(rev))


def demo() -> None:
    # self-check:定價恆定→無套利→≈0;完美≥naive≥0;尖峰日有利可圖
    flat = np.full(24, 50.0)
    c, d = perfect(flat)
    assert abs(settle(c, d, flat)) < 1e-6, "constant price must yield ~0"
    idx = pd.date_range("2022-01-01", periods=24, freq="h")
    vals = np.full(24, 30.0)
    vals[3] = 5
    vals[19] = 120  # 便宜谷(3點)+ 尖峰(19點)
    spike = pd.Series(vals, index=idx)
    cp, dp = perfect(spike.values)
    cn, dn = naive(spike)  # 預設 chg 含 3 點、dis 含 19 點
    rp, rn = settle(cp, dp, spike.values), settle(cn, dn, spike.values)
    assert rp >= rn >= 0, f"perfect {rp} must beat naive {rn} >=0"
    assert rp > 0, "spike day must be profitable"
    # LP 可行集 == settle 可行集:負價下也不能靠「同小時充爆再放掉」偷分,
    # 否則 settle 會夾掉 → 天花板虛高(這條抓過一個真 bug)
    neg = np.array([-30.0, -20.0, 5.0, 80.0, -25.0, 60.0] * 4)
    cn2, dn2 = perfect(neg)
    assert abs(settle(cn2, dn2, neg) - float(neg @ (dn2 - cn2))) < 1e-6, (
        "LP 排程被 settle 夾到 → 兩邊可行集不一致"
    )
    print(
        f"  self-check ok: flat≈0, spike perfect €{rp:.1f} ≥ naive €{rn:.1f}, 負價無夾取"
    )


def main() -> None:
    demo()
    print(
        f"\n電池: {E_MWH} MWh / {P_MW} MW / η={ETA}   (price-taker, 真實 DA 價, 週窗)\n"
    )
    for area in ("DK1", "DK2"):
        price = load_prices(area)
        cut = int(len(price) * 0.7)  # 時序切分:前 70% 學時段,後 30% 測(不 leak)
        train, test = price.iloc[:cut], price.iloc[cut:]
        chg, dis = naive_hours(train, k=4)  # k=4 配合電池 4 小時容量
        rp = backtest(test, lambda g: perfect(g.values))
        rn = backtest(test, lambda g: naive(g, chg, dis))
        mp, mn = _metrics(rp), _metrics(rn)
        cap = mn["total"] / mp["total"] * 100 if mp["total"] else 0
        print(
            f"[{area}]  測試 {mp['n']} 週  {test.index.min().date()} → {test.index.max().date()}"
        )
        print(f"   naive 時段(訓練期學,k=4): 充 {chg}  放 {dis}")
        print(
            f"   完美預知(天花板) : 總 €{mp['total']:>10,.0f}   年均 €{mp['per_year']:>8,.0f}   Sharpe {mp['sharpe']:.2f}"
        )
        print(
            f"   naive 固定時段(地板): 總 €{mn['total']:>10,.0f}   年均 €{mn['per_year']:>8,.0f}   Sharpe {mn['sharpe']:.2f}"
        )
        print(
            f"   naive 捕獲了天花板的 {cap:.0f}%   (中間留給 forecaster / 之後的 agent)\n"
        )


if __name__ == "__main__":
    main()
