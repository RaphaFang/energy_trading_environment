"""建物的**供熱方式 × 供暖面積 × 市**(Danmarks Statistik `BYGB40`,2011 → 今年)。

**為什麼需要**:2022 氣候協議要在 **2035 前把瓦斯逐出住宅供暖**,
而「瓦斯用戶在哪、要換成什麼、會變成多少電或熱需求」是全國情境的起點。
🔑 **`BYGB40` 同時給「棟數」與「供暖面積(1000 m²)」** ——
**面積才是熱需求的代理**,棟數不是(一棟公寓樓 vs 一棟獨棟差很多)。

━━━ 為什麼是這張表,不是別的 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DST 沒有「住宅 × 供熱方式」的能源量表;`BYGB40` 是唯一同時有
**地理(116 個區域,含全部 98 個市)× 供熱方式(10 種)× 供暖面積 × 年份** 的。
⚠️ 它是 **BBR 登記**,不是實際用量 —— 面積要乘上比能耗才是熱需求。**這一步留給分析層。**

⚠️ **與 Evida 的數字對不上是正常的**:Evida(瓦斯配網商)記 355,179 台瓦斯爐,
BBR 記 299,192 台 —— 兩者口徑不同(接管 vs 登記)。**引用時要說是哪一個。**

📌 已知的地理分布(2026-08-21 查證,可交叉檢核抓下來的資料):
全國約 **412,000 戶**燒天然氣(佔住宅 15%),**27% 集中在北西蘭與東西蘭 = DK2**;
比例最高的是 **Dragør 69% / Allerød 61% / Egedal 55%**(全在大哥本哈根);
Bornholm 幾乎沒有,日德蘭與 Fyn 大部分地區低於十分之一。
🔑 **所以「瓦斯退場」在地理上是一個 DK2 問題** —— 又一個只做 DK2 的理由。

用法:python new_src/data/heating_stock.py
"""

import io
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from window import START  # noqa: E402

OUT = Path("new_data/heating_stock")
URL = "https://api.statbank.dk/v1/data"
TABLE = "BYGB40"


def _post(payload: dict) -> bytes:
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def pull() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # ⚠️ 「全部年份 × 全部市 × 全部用途 × 全部建造年」會爆量 →
    #    `anvendelse` 與 `opførelsesår` 取合計(*),其餘全取。**要細分時再單獨抓。**
    for unit, tag in [("50", "m2"), ("45", "antal")]:  # DST 用代碼不是文字
        name = f"bygb40_{tag}_{START[:4]}_latest"
        p = OUT / f"{name}.parquet"
        if p.exists():
            print(f"  · {name}: 已存在,跳過")
            continue
        raw = _post({
            "table": TABLE,
            "format": "CSV",  # ⚠️ BULK 對「全部區域」會被擋(EXTRACT-NOTALLOWED),CSV 不會
            # ⚠️ DST 沒有 ANVEND/OPFØRELSESÅR 的「合計」代碼 —— **省略該變數就會自動加總**。
            #    全取的話是 116×10×29×28×16 ≈ 1,500 萬列,沒必要。要細分時再單獨抓。
            "variables": [
                {"code": "OMRÅDE", "values": ["*"]},
                {"code": "MÆNGDE4", "values": [unit]},
                {"code": "OPVARM", "values": ["*"]},
                {"code": "Tid", "values": ["*"]},
            ],
        })
        df = pd.read_csv(io.BytesIO(raw), sep=";")
        tmp = p.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False, engine="pyarrow", compression="snappy")
        tmp.rename(p)
        print(f"  ✓ {name}: {len(df):,} 列 × {df.shape[1]} 欄 → {p}")


if __name__ == "__main__":
    pull()
