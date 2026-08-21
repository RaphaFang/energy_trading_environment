"""Energiproducenttællingen (EPT) — **全國**電廠與熱廠的機組級主檔與逐年實績。

為什麼需要這個檔:`dk2_fleet.py` 是**手工**查六台機組查出來的(varmelast 說明文字 +
ENTSO-E + 業者官網),涵蓋範圍只到 CTR/VEKS 熱傳輸網。要回答「全國焚化產能 −30%」
這種**國家級**政策問題,需要的是全國所有機組的容量、燃料、業主與**實際產出**。

EPT 就是那份東西:Energistyrelsen 依法向所有接公用電網/熱網的生產者收集,
**1,226 座廠、2,916 個機組**,免費、官方、可引用。

━━━ 三個檔各是什麼 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**A. stamdata_vaerk** —— **廠級**主檔(1 列 = 1 座 vaerk_id)。
   容量(indfyret / el / varme MW)、主燃料與燃料佔比、業主、市、熱網、蓄熱槽 m3。

**B. stamdata_anlaeg** —— **機組級**主檔(1 列 = 1 個 anlaeg)。多了 `anlaegstype_navn`
   (機組型式)、`idriftdato` / `skrotdato`(商轉/除役日)、`aktoer`。
   🔑 **`anlaegstype_navn` 是 `dk2_fleet` 的 `unit_type` 一直在猜的那個欄位。**

**C. produktion** —— **2023–2025 逐年實績**。
   🔴 **它是「機組級」不是「廠級」** —— 每年約 2,900 列 = **每台 `vrkanl_ny` 一列**
   (2023: 2,844 / 2024: 2,877 / 2025: 2,916)。**2026-08-21 一開始誤以為是廠級,
   結論差很多,所以特別寫在這裡。**
   欄位:`brutto_TJ`(**燃料投入**)/ `varmeprod_TJ` / `varmelev_TJ` / `elprod_TJ` / `ellev_TJ`,
   加上**逐燃料投入 TJ**(kul / affald / skovflis / traepiller / halm / omgivelsesvarme …)。

   🔑 **所以逐台的效率是量得出來的,不是目錄值**:
       `eta_el = elprod_TJ / brutto_TJ`   `eta_th = varmeprod_TJ / brutto_TJ`
       `電熱比 = elprod_TJ / varmelev_TJ`
   ⚠️ **但 `Cv`(抽汽損失)算不出來** —— `eta_el` 是**年平均**(運轉點),
   `Cv` 是**斜率**(多抽一單位熱少發多少電)。平均值定不出斜率。
   ✅ **背壓機組例外**:熱電綁死在一條線上,所以**實測電熱比就是 `Cb`**。垃圾廠全部適用。

━━━ ⚠️ 三個使用前提 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 🔴 **是逐年,不是逐時。** 逐時熱需求仍然只有 varmelast(Storkøbenhavns Fjernvarme,
   = 全國供熱的 **26.0%**)。EPT 給的是**量與異質性**,不是形狀。
2. 🔴 **容量口徑與 varmelast 對不起來。** ARC:EPT 190 MW_th vs varmelast 250 vs 官網 247。
   但 **Vestforbrænding 142 vs 143 ✓**、**ARGO 電容量 33.1 vs 反推 33.6 ✓**。
   → **不要混用。** 逐廠比對過再決定用哪一個,差異記在 `figs/ept_fleet/FINDINGS.md`。
3. ⚠️ **一座實體廠可能有多個 `vaerk_id`**(Norfors 有 11 個、Vestforbrænding 21 個)。
   直接用 `Hovedbrændselsgruppe == "affald"` 篩會**漏掉並低估**
   (Vestforbrænding 會只拿到 69 MW_th 而不是 142)。
   → **一律先 groupby(selskab_navn, vaerk_postdistrikt) 再看。**

━━━ 儲存原則:raw ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**存來源回傳的原樣** —— 不挑欄位、不換單位、不加價區、不算電熱比。
價區判定與衍生表是分析的事,在 `new_src/heat/ept_fleet.py`。

━━━ 🔴 為什麼只有三年,以及 2019–2022 怎麼辦 ━━━━━━━━━━━━━━━━━━━━━━

**EPT 是年度版本制**,每一版只公布**最近三次報送**的滾動窗口。
證據不是猜的:**KF25 的方法章明文寫 `EPT2023, som inkluderer data frem til 2023`**,
**KF26 的凝汽表寫 `Kilde: EPT24`** → 2023、2024 版確實存在,只是**官網不再掛出來**。

→ **2019–2022 的機組級資料不是不存在,是舊版發布物。** 三條路:
  ① 寫信給 Energistyrelsen 要舊版(同生質價要 Dansk Fjernvarme 的做法)
  ② 用 `ens_el_og_fjernvarmesektor_1972_2024`(國家 × 燃料,1972+)蓋住長期趨勢
  ③ 接受機組級只有 2023–2025,把它當**橫斷面**用(異質性),長期用逐時的 varmelast
⚠️ **本輪(2026-08-21)採 ②+③,①尚未寄信。**

⚠️ **媒體 id 是 Energistyrelsen 換版就會變的**(每年一版)。抓下來的 xlsx 一併留著
(`*.xlsx`),因為**下一版上線後這個 id 會指到新資料** —— 同 `new_data/interconnectors/`
留 PDF 的理由。

🔴 **另一個坑:廠級主檔的 `elkapacitet_MW` 不可靠。** 1,226 座裡有 **225 座**與自己
機組加總對不上(Avedøre 在廠級檔記 **0 MW**,機組級是 805.6);全國合計 2,155 vs 7,440 MW。
→ **容量一律用 `anlaeg` 或 `produktion` 檔,不要用 `vaerk` 檔。**

用法:python new_src/data/ept.py
"""

import io
import urllib.request
from pathlib import Path

import pandas as pd

EPT = Path("new_data/ept")

# Energistyrelsen「Data: Oversigt over energisektoren」上的下載連結(2025 版報送)。
# https://ens.dk/analyser-og-statistik/data-oversigt-over-energisektoren
SOURCES = {
    "ept_stamdata_vaerk_2025": (
        "https://ens.dk/media/7197/download",
        "廠級主檔:容量、主燃料與燃料佔比、業主、市、熱網、蓄熱槽",
    ),
    "ept_stamdata_anlaeg_2025": (
        "https://ens.dk/media/7198/download",
        "機組級主檔:多了機組型式、商轉/除役日",
    ),
    "ept_produktion_2023_2025": (
        "https://ens.dk/media/7199/download",
        "2023–2025 逐年實績:熱/電產出與交付 + 逐燃料投入 TJ",
    ),
    # 🔑 機組級只有三年,但**國家 × 燃料**的長序列回到 1972 —— 兩者一起用才蓋得住
    #    使用者要的 2019→今天。⚠️ 但這份只到 2024(年度統計以完整年結算)。
    "ens_el_og_fjernvarmesektor_1972_2024": (
        "https://ens.dk/media/7433/download",
        "國家 × 燃料 1972–2024:El / Fjernvarme 的產出與投入、Elkapacitet(1972+)、"
        "Varmekapacitet 分類別(2022+,含 antal_anlaeg 與 andel_samlet_varmelevering)",
    ),
}


def _save(df: pd.DataFrame, raw: bytes | None, name: str) -> Path:
    """先寫 `.tmp` 再 rename —— 中途失敗不會留下半個檔。

    `raw` 給 bytes 才寫 xlsx 原檔;拆工作表時只有第一張帶 raw,
    否則同一個 xlsx 會被複製一份給每張表。
    """
    EPT.mkdir(parents=True, exist_ok=True)
    p = EPT / f"{name}.parquet"
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, engine="pyarrow", compression="snappy")
    tmp.rename(p)

    if raw is not None:
        x = EPT / f"{name}.xlsx"
        xtmp = x.with_suffix(".xlsx.tmp")
        xtmp.write_bytes(raw)
        xtmp.rename(x)
    return p


def pull() -> None:
    for name, (url, what) in SOURCES.items():
        if (EPT / f"{name}.parquet").exists():
            print(f"  · {name}: 已存在,跳過")
            continue
        with urllib.request.urlopen(url, timeout=180) as r:
            raw = r.read()
        x = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
        # ⚠️ 多工作表的檔(彙總長序列)每張表意義不同,**分開存**,不要只讀第一張
        #    (第一張是 `dokumentation`,讀了會以為只有 40 列)。
        if len(x.sheet_names) > 1:
            for i, sh in enumerate(x.sheet_names):
                d = x.parse(sh)
                _save(d, raw if i == 0 else None, f"{name}__{sh.lower()}")
                print(f"  ✓ {name}__{sh.lower()}: {d.shape[0]:,} 列 × {d.shape[1]} 欄")
            print(f"    ↳ {what}")
        else:
            df = x.parse(x.sheet_names[0])
            _save(df, raw, name)
            print(f"  ✓ {name}: {df.shape[0]:,} 列 × {df.shape[1]} 欄 — {what}")


def load(which: str) -> pd.DataFrame:
    """讀回來。`which` ∈ {vaerk, anlaeg, produktion}。"""
    key = {
        "vaerk": "ept_stamdata_vaerk_2025",
        "anlaeg": "ept_stamdata_anlaeg_2025",
        "produktion": "ept_produktion_2023_2025",
        # 國家 × 燃料的長序列(1972+),一張表一個檔
        "el": "ens_el_og_fjernvarmesektor_1972_2024__el",
        "fjernvarme": "ens_el_og_fjernvarmesektor_1972_2024__fjernvarme",
        "elkapacitet": "ens_el_og_fjernvarmesektor_1972_2024__elkapacitet",
        "varmekapacitet": "ens_el_og_fjernvarmesektor_1972_2024__varmekapacitet",
        "vindkapacitet": "ens_el_og_fjernvarmesektor_1972_2024__vindkapacitet",
    }[which]
    p = EPT / f"{key}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} 不存在 —— 先跑 python new_src/data/ept.py")
    return pd.read_parquet(p)


if __name__ == "__main__":
    pull()
