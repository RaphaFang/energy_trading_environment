"""丹麥的**政策文件與官方預測** — 論文第 1、2、8 章的一手來源。

⚠️ **這支不是抓時間序列,是抓文件。** 因此它與其他 `new_src/data/*.py` 有兩點不同:
① 沒有 2019→今天的窗口(文件有自己的發布年);② 存 PDF 原檔 **並**用 `markitdown`
轉一份 markdown —— 因為 PDF 的表格不可 grep,而我們要引用的正是表格。

🔴 **為什麼 PDF 一定要留在本機**:`new_data/` 是 gitignored,前提是「重跑腳本可重建」。
   對**下載的來源文件**這個前提不成立 —— kefm.dk 的 media id 每次改版就換,舊 id 直接 404
   (2026-08-21 實測:KF24 的兩個 id 已經死了)。**這與 `new_data/interconnectors/` 的
   AF25 PDF 是同一個問題。** → 抓到就別刪。

━━━ 這裡面最重要的一份 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**KF25/KF26 的「El og fjernvarme」forudsætningsnotat,表 5.3 與 5.4** ——
**Energistyrelsen 逐廠假設的最後運轉年**。已轉錄成 `new_src/heat/plant_lifetimes.py`(有版控)。
🔑 **AMV1 = 2029。** 這一格是整篇論文的支點。

用法:python new_src/data/plans.py
"""

import shutil
import subprocess
import urllib.request
from pathlib import Path

PLANS = Path("new_data/plans")

# name → (url, 一句話這是什麼)
SOURCES = {
    # ── 官方預測(每年一版,表 5.3/5.4 是逐廠退場年)──────────────────────
    "kf26_el_og_fjernvarme": (
        "https://www.kefm.dk/Media/639058804066502895/7.%20KF26%20forudsaetningsnotat%20El%20og%20fjernvarme.pdf",
        "KF26 電與區域供熱:表 5.1 熱容量 pipeline、5.2 凝汽、**5.3/5.4 逐廠退場年**、2.1 聯絡線",
    ),
    "kf25_el_og_fjernvarme": (
        "https://www.kefm.dk/Media/638835926226490298/7.%20KF25%20forudstningsnotat%20El%20og%20fjernvarme.pdf",
        "KF25 同上(DK2 的表 5.4 與 KF26 逐格相同,DK1 多兩座已關的)",
    ),
    "kf26_introduktion": (
        "https://admin.kefm.dk/Media/639058804252441086/1.%20KF26%20forudsaetningsnotat%20Introduktion.pdf",
        "KF26 導論:整套預測的邊界與免責",
    ),
    "kf25_introduktion": (
        "https://www.kefm.dk/Media/638743415001838643/1.%20KF25%20foruds%C3%A6tningsnotat%20Introduktion.pdf",
        "KF25 導論",
    ),
    "kf25_hoeringsnotat": (
        "https://www.kefm.dk/Media/638917252048649856/KF25%20Hringsnotat.pdf",
        "KF25 意見徵詢回覆 —— **業界對假設的反駁在這裡**,寫「爭議」那節用",
    ),
    # ── 焚化(產能怎麼降、降到哪)────────────────────────────────────────
    "kf25_kapitel26_affaldsforbraending": (
        "https://www.kefm.dk/Media/638822888958253044/Kapitel%2026%20Affaldsforbrnding.pdf",
        "KF25 焚化章:產能路徑 2028→2035、進口轉出口的時點、🔴 **降產能的機制是競爭化不是關廠名單**",
    ),
    "kf24_kapitel25_affaldsforbraending": (
        "https://www.kefm.dk/Media/638500583574605267/KF24%20Kapitel%2025%20Affaldsforbr%C3%A6nding.pdf",
        "KF24 焚化章 —— 拿來對照 KF25 為什麼上修(垃圾熱價格上限提高 → 關得比預期少)",
    ),
    "ens_monitorering_affaldsforbraending_2024": (
        "https://ens.dk/media/6180/download",
        "Energistyrelsen 產能監測 2024:**全國 27 座廠的名單**(圖 4.6)、4.35 Mt 核准產能、Svendborg 2023 底關閉",
    ),
    # ── 政治協議 ────────────────────────────────────────────────────────
    "klimaaftale_groen_stroem_og_varme_2022": (
        "https://www.kefm.dk/Media/637920977082432693/Klimaaftale%20om%20gr%C3%B8n%20str%C3%B8m%20og%20varme%202022.pdf",
        "2022-06-25 氣候協議:**2035 住宅不得用瓦斯**、禁止新的化石燃料熱網專案、熱網公司須提瓦斯退場計畫",
    ),
}

# 🔴 抓不到的(留著,免得下次又去找一輪):
UNAVAILABLE = {
    "kl_kapacitetstilpasningsplan_2020": (
        "KL 2020-12 的產能調整計畫分析報告(死亡名單的本體)—— "
        "kl.dk 的兩個 media id 與 ea-energianalyse 的直連都 404(2026-08-21)。"
        "**內容摘要已在記憶 `dk-waste-heat-policy`,要原文得另尋。**"
    ),
}


def _fetch(url: str, dest: Path) -> bool:
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            data = r.read()
    except Exception as e:
        print(f"  ✗ {dest.name}: {e}")
        return False
    if len(data) < 5000:  # 404 頁面也是 200,用大小擋掉
        print(f"  ✗ {dest.name}: 只有 {len(data)} bytes,八成是錯誤頁")
        return False
    tmp.write_bytes(data)
    tmp.rename(dest)
    return True


def _to_markdown(pdf: Path) -> None:
    """PDF 的表格不能 grep,而我們要引用的正是表格 → 一律轉一份 markdown。

    ⚠️ 使用者的全域規則:任何 PDF 都先 `markitdown` 再讀,不直接讀原始 PDF。
    """
    if shutil.which("markitdown") is None:
        print("    ⚠️ 找不到 markitdown,略過轉檔")
        return
    md = pdf.with_suffix(".md")
    out = subprocess.run(["markitdown", str(pdf)], capture_output=True, text=True)
    if out.returncode == 0 and len(out.stdout) > 1000:
        md.write_text(out.stdout)
        print(f"    ↳ {md.name} ({len(out.stdout):,} 字元)")


def pull() -> None:
    PLANS.mkdir(parents=True, exist_ok=True)
    for name, (url, what) in SOURCES.items():
        pdf = PLANS / f"{name}.pdf"
        if pdf.exists():
            print(f"  · {name}: 已存在,跳過")
            continue
        if _fetch(url, pdf):
            print(f"  ✓ {name}: {pdf.stat().st_size / 1e3:,.0f} KB — {what}")
            _to_markdown(pdf)
    if UNAVAILABLE:
        print("\n🔴 已知抓不到:")
        for k, why in UNAVAILABLE.items():
            print(f"  · {k}: {why}")


if __name__ == "__main__":
    pull()
