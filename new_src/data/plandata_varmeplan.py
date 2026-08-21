"""Plandata.dk 的**供熱規劃區**(varmeplansområde)—— 98 個市的供熱計畫,唯一的全國空間資料。

**為什麼需要**:KF25/KF26 說它們的「pipeline 專案」來源之一就是
「indberettet til plandata.dk 的 varmeforsyningsprojekter」。而丹麥**沒有單一的全國熱網計畫** ——
全國性規劃是 2022 年政府與 KL 的協議(各市 2023 年底前核准專案、**2028 完成**),
**由 98 個市各自執行**。Plandata 是那 98 份計畫唯一匯總得到的地方。

━━━ 兩個圖層 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  `theme_pdk_varmeplansomraade_vedtaget_v`  **已通過** 1,355 區
  `theme_pdk_varmeplansomraade_aflyst_v`    **已撤銷**   339 區 ← 🔑 計畫失敗的證據在這裡

━━━ 🔑 最有用的三個欄位 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  `vaerdi1207`   供熱方式:**Fjernvarme 904 區 vs Individuel varmeforsyning 790 區**
  `konvslutaar`  **轉換完成年** —— 🔑 **288 區指向 2028**,正好對上 KL 協議的期限
  `virknavn`     負責的供應商(Vestforbrænding 23 區、VEKS 27 區…)→ **接得上 agent**

⚠️ **這是空間計畫,不是需求序列。** 它告訴你「哪一塊地在哪一年要改成什麼」,
不會告訴你逐時熱需求。**別把它當熱需求資料用。**
⚠️ `datovedt` / `datoaflyst` 是 **YYYYMMDD 的整數**,不是日期型別 —— 直接 `to_datetime` 會變 1970。
⚠️ `forvarme` 99% 是空的,不要用。

━━━ 儲存 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

原始 GeoJSON(含幾何,27 MB)**照原樣留著**;另外把 `properties` 攤平成一個 parquet
(去掉幾何,只剩屬性)方便分析。**幾何要用的時候再讀 GeoJSON。**

用法:python new_src/data/plandata_varmeplan.py
"""

import json
import urllib.request
from pathlib import Path

import pandas as pd

PD_DIR = Path("new_data/plandata")
WFS = "https://geoserver.plandata.dk/geoserver/wfs"
LAYERS = {
    "theme_pdk_varmeplansomraade_vedtaget_v": "vedtaget",
    "theme_pdk_varmeplansomraade_aflyst_v": "aflyst",
}


def _url(layer: str) -> str:
    return (
        f"{WFS}?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeNames=pdk:{layer}&outputFormat=application/json&srsName=EPSG:4326"
    )


def pull() -> None:
    PD_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for layer, status in LAYERS.items():
        p = PD_DIR / f"{layer}.json"
        if not p.exists():
            with urllib.request.urlopen(_url(layer), timeout=600) as r:
                data = r.read()
            tmp = p.with_suffix(".json.tmp")
            tmp.write_bytes(data)
            tmp.rename(p)
            print(f"  ✓ {layer}: {len(data) / 1e6:.1f} MB")
        else:
            print(f"  · {layer}: 已存在,跳過")
        feats = json.load(open(p))["features"]
        for f in feats:
            rec = dict(f["properties"])
            rec["_lag"] = status
            rows.append(rec)

    df = pd.DataFrame(rows)
    # YYYYMMDD 整數 → 日期(⚠️ 直接 to_datetime 會被當 epoch 秒,變成 1970)
    for c in ("datovedt", "datoaflyst"):
        df[c + "_d"] = pd.to_datetime(df[c], format="%Y%m%d", errors="coerce")
    out = PD_DIR / "varmeplansomraader.parquet"
    tmp = out.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False, engine="pyarrow", compression="snappy")
    tmp.rename(out)
    print(f"\n✓ 屬性表:{len(df):,} 區 × {df.shape[1]} 欄 → {out}")
    print(f"  已通過 {(df._lag == 'vedtaget').sum():,} / 已撤銷 {(df._lag == 'aflyst').sum():,}"
          f"  ·  {df.komnavn.nunique()} 個市  ·  {df.virknavn.nunique()} 家供應商")
    print("  供熱方式:" + ", ".join(f"{k}={v}" for k, v in df.vaerdi1207.value_counts().items()))
    k = df.konvslutaar[df.konvslutaar.between(2020, 2040)]
    print(f"  轉換完成年(2020–2040):{len(k):,} 區,中位數 {k.median():.0f},"
          f"最多的一年 {int(k.mode().iloc[0])}({int((k == k.mode().iloc[0]).sum())} 區)")


if __name__ == "__main__":
    pull()
