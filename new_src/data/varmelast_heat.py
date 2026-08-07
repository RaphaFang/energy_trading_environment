"""大哥本哈根(DK2)實際逐時區域供熱資料 — varmelast.dk 公開 API。

**為什麼這份資料是關鍵**:DK1 沒有公開的逐時 DH 需求,只能用度日代理;而 2026-08-05
的檢驗證明「代理 vs CHP 發電量」根本驗不動(發電量由電價主導,識別力不足)。
這份 DK2 實際熱需求讓我們可以:
  1. **校準代理的函數形式**(T_base、基載比例、日內形狀)—— 在有真值的地方校準,
     再把校準好的形式移轉到 DK1,並在論文中說明外推假設。
  2. 拿到真實的熱需求量級,取代 `heat.demand.ANNUAL_TWH_DK1` 那個佔位值。
  3. legend 的分類(廢棄物/熱電/尖峰生質/尖峰氣/本地)**幾乎一對一對應 heat/chp.py 的
     LP 結構** → 可以直接驗證排程模型,不只驗證需求代理。

涵蓋:2021 起(2019/2020 無資料),逐時,單位 MJ/s = MW_th。
主要序列:BE-EO-CTR-EFF(CTR 熱需求)、DAP-VEKS-FORBRUG-EFF(VEKS 熱需求)、
TOTAL(總產熱)、BE-VL-AFFALD-EF(廢棄物)、BE-VL-KRAFTV-EF(熱電)、
BE-VL-BIO-EF / BE-VL-SPIDS-GAS-EF(尖峰生質/氣)、LOCAL(本地產熱)。

⚠️ 這是**大哥本哈根(DK2)**,不是 DK1。當校準與驗證用,不是 DK1 的直接輸入。
⚠️ API 是小型公用事業網站,抓取請保持禮貌間隔(本檔預設每季一次請求 + 2 秒延遲)。
"""

import json
import time
import urllib.request

import pandas as pd

URL = "https://www.varmelast.dk/api/v1/heatdata/historical"


def fetch(start: str, end: str) -> pd.DataFrame:
    """抓一段期間,回傳 wide 格式(每個 legend key 一欄)。"""
    with urllib.request.urlopen(f"{URL}?from={start}&to={end}", timeout=120) as r:
        d = json.load(r)
    rows = []
    for t in d["times"]:
        row = {"timestamp": t["timestamp"]}
        for v in t["values"]:
            row[v["key"]] = v["value"]
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return (
        df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    )


def fetch_range(start_year: int = 2021, end_year: int = 2026) -> pd.DataFrame:
    """逐季抓(單次請求別太大),回傳合併後的 DataFrame。"""
    parts = []
    for y in range(start_year, end_year + 1):
        for q0, q1 in (
            ("01-01", "04-01"),
            ("04-01", "07-01"),
            ("07-01", "10-01"),
            ("10-01", "12-31"),
        ):
            try:
                p = fetch(f"{y}-{q0}", f"{y}-{q1}")
            except Exception as e:  # 網站不穩就跳過該季,不要整批失敗
                print(f"  ! {y}-{q0}: {type(e).__name__}")
                continue
            if len(p):
                parts.append(p)
                print(f"  · {y}-{q0}→{q1}: {len(p)} 列")
            time.sleep(2)  # 禮貌間隔
    if not parts:
        return pd.DataFrame()
    return (
        pd.concat(parts)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    from pathlib import Path

    out_dir = Path("new_data/heat")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "varmelast_ckb_2021_2026.parquet"
    if path.exists():
        print(f"· 已存在,跳過 → {path}")
    else:
        d = fetch_range()
        assert len(d), "沒抓到任何資料"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        dem = [c for c in ("BE-EO-CTR-EFF", "DAP-VEKS-FORBRUG-EFF") if c in d]
        tot = d[dem].sum(axis=1)
        print(
            f"\n✓ {len(d)} 列  {d['timestamp'].min()} → {d['timestamp'].max()}\n"
            f"  熱需求(CTR+VEKS)MW_th: 均 {tot.mean():.0f}  尖峰 {tot.max():.0f}  最低 {tot.min():.0f}\n"
            f"  年熱量 ≈ {tot.mean() * 8760 / 1e6:.2f} TWh_th  → {path}"
        )
