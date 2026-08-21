"""🔑 **Energistyrelsen 官方的「每一座中央熱電機組哪一年停」** — KF25/KF26 表 5.1–5.4 逐字轉錄。

**為什麼這是這個論文最重要的外部資料**:研究問題是「把燒東西的熱電聯產換成吃電的熱泵,
後果是什麼」。而丹麥能源署**已經假設這件事會發生,還逐廠給了年份**。
→ 論文的定位因此從「我假設一個情境」變成
   **「官方預測已經這樣假設,但它是年度、聚合的(DH-Invest + RAMSES);我補上逐時、機組級的後果」**。
   這與對 FFH50 的定位是同一個縫。

**Energistyrelsen 自己給的理由**(KF26 §5.2.4,我的摘要):
中央熱電機組的運轉會在**現有熱約、電力補貼與 CCS 合約到期後停止**,因為
「延壽的成本一般高於改用純產熱設備,例如熱泵或生質鍋爐」。
⚠️ 但署方自己加註:**這些年份不代表業者的最終決定**,是「在現行條件且無新政策下的可能路徑」。
🔴 **論文引用時一定要照抄這句免責,不要寫成「丹麥決定 2029 關掉 AMV1」。**

━━━ 版本 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**KF25**(2025-04)與 **KF26**(2026-04)的 DK2 表 5.4 **完全相同**(2026-08-21 逐格比對)
→ 假設是穩定的,不是每年在動。DK1 表 5.3 有變:KF26 拿掉了已關的 SSV4 與 ESV3。

原始 PDF 與 markdown 轉檔在 `new_data/plans/`(gitignored,`new_src/data/plans.py` 可重抓)。

━━━ ⚠️ 與 repo 其他資料的關係 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **`dk2_fleet.py` 是「現在有什麼」,這個檔是「官方假設什麼時候沒有」。** 兩者互補,不重疊。
- 🔴 **AMV1 = 2029** 是這張表裡對本論文最尖銳的一格:只剩三年,而 AMV1 是 64 MW_e / 251 MW_th。
- 🔴 **`kondens` 那張表的 `Kilde: EPT24`** —— 證明 EPT 有 2023、2024 的年度版本存在
  (我們手上只有 2025 版的滾動三年窗口)。見 `new_src/data/ept.py` 的版本說明。
"""

# ── 表 5.4:DK2 中央熱電機組(KF25 與 KF26 相同)────────────────────────────
# 欄位:熱約到期日 / 電力補貼結束年 / **KF 假設的最後一個完整運轉年**
DK2_CHP = {
    "AVV1": dict(title="Avedøreværket blok 1", heat_contract="2033-12-31",
                 el_support_end=2031, last_full_year=2033),
    "AVV2": dict(title="Avedøreværket blok 2", heat_contract="2027-12-31",
                 el_support_end=2023, last_full_year=2045),
    "ASV6": dict(title="Asnæsværket blok 6", heat_contract="2040-12-31",
                 el_support_end=None, last_full_year=2045),
    "HCV8": dict(title="H.C. Ørstedsværket blok 8", heat_contract="2026-12-31",
                 el_support_end=None, last_full_year=2026),
    "AMV1": dict(title="Amagerværket blok 1", heat_contract="2029-12-31",
                 el_support_end=2029, last_full_year=2029),
    "AMV4": dict(title="Amagerværket blok 4", heat_contract="2049-12-31",
                 el_support_end=2039, last_full_year=2049),
    "OEKR6": dict(title="Østkraft blok 6 (Bornholm)", heat_contract="2032-12-31",
                  el_support_end=2032, last_full_year=2032),
}

# ── 表 5.3:DK1 中央熱電機組(KF26 版;KF25 另有已關的 SSV4/ESV3)──────────
DK1_CHP = {
    "SSV3": dict(title="Studstrupværket blok 3", heat_contract="2030-12-31",
                 el_support_end=2031, last_full_year=2030),
    "SKV3_flis": dict(title="Skærbækværket blok 3 — 木片", heat_contract="2037-12-31",
                      el_support_end=2037, last_full_year=2037),
    "SKV3_gas": dict(title="Skærbækværket blok 3 — 天然氣", heat_contract="2037-12-31",
                     el_support_end=None, last_full_year=2037),
    "HEV": dict(title="Herningværket", heat_contract="2033-12-31",
                el_support_end=2022, last_full_year=2033),
    "FYV7": dict(title="Fynsværket blok 7", heat_contract=None,
                 el_support_end=None, last_full_year=2030,
                 note="燃煤,2024-04-22 關閉,2024-12 改燒天然氣"),
    "FYV8": dict(title="Fynsværket blok 8", heat_contract="2035-12-31",
                 el_support_end=2029, last_full_year=2035),
    "FYV9": dict(title="Fynsværket blok 9", heat_contract=None,
                 el_support_end=None, last_full_year=None,
                 note="KF26:整個預測期都在"),
    "NJV": dict(title="Nordjyllandsværket", heat_contract="2028-12-31",
                el_support_end=None, last_full_year=2028),
    "RAV": dict(title="Randersværket", heat_contract="2036-12-31",
                el_support_end=2024, last_full_year=2036),
    # KF25 有但 KF26 已移除(都已實際關閉):
    "SSV4": dict(title="Studstrupværket blok 4", heat_contract="2022-02-31",
                 el_support_end=None, last_full_year=2023,
                 note="🔴 已關:2024-06-30。KF26 已從表中移除"),
    "ESV3": dict(title="Esbjergværket blok 3", heat_contract="2023-04-01",
                 el_support_end=None, last_full_year=2023,
                 note="🔴 已關:2024-08。KF26 已從表中移除"),
}

# ── 表 5.2:凝汽機組(只發電,不供熱)──────────────────────────────────────
# ⚠️ 這些**不是** CHP,但它們是 DK2 適足性的備援容量 → 講尖峰時要記得它們存在。
CONDENSING = {
    "SSV5": dict(area="DK1", mw_e=14, last_full_year=2030),
    "DK1_oevrige": dict(area="DK1", mw_e=131, last_full_year=None, note="其餘分散式合計"),
    "KYV21": dict(area="DK2", mw_e=260, last_full_year=2023,
                  note="🔴 已關:2024-06-30。KF26 已移除"),
    "KYV22": dict(area="DK2", mw_e=260, last_full_year=None),
    "KYV_oevrige": dict(area="DK2", mw_e=146, last_full_year=None),
    "MAV": dict(area="DK2", mw_e=70, last_full_year=None, note="Masnedøværket"),
    "OEKR_reserve": dict(area="DK2", mw_e=62, last_full_year=None),
    "DK2_oevrige": dict(area="DK2", mw_e=56, last_full_year=None),
}

# ── 表 5.1:全國熱容量 pipeline(MW,KF26 版,四捨五入到 50)────────────────
# 🔑 **這是「熱泵取代熱電」的全國版本** —— 對照 HOFOR 一家的 300 MW。
PIPELINE_MW = {
    "varmepumper":    {2025: 1200, 2026: 1250, 2027: 1400, 2028: 1550},
    "solvarme":       {2025: 1100, 2026: 1100, 2027: 1100, 2028: 1100},
    "elkedler":       {2025: 2550, 2026: 2900, 2027: 3500, 2028: 3800},
    "biomassekedler": {2025: 2600, 2026: 2650, 2027: 2650, 2028: 2650},
}
# KF25 版(基準年早一年,留著看趨勢修正的方向):
PIPELINE_MW_KF25 = {
    "varmepumper":    {2024: 800,  2025: 1200, 2026: 1250},
    "solvarme":       {2024: 1100, 2025: 1100, 2026: 1100},
    "elkedler":       {2024: 2250, 2025: 2800, 2026: 2850},
    "biomassekedler": {2024: 2300, 2025: 2300, 2026: 2300},
}

# ── 焚化產能的路徑(KF25 第 26 章,文字敘述;圖 26.4/26.5 的數值是圖不是表)──
WASTE_CAPACITY_PATH = """
🔴 **機制與 KL 死亡名單不同**:KF 假設產能下降來自 **2025 起的競爭化**
(部分產能「在新的框架條件下沒有競爭力」而關閉),**不是**來自 2020 政治協議指定的關廠名單。
→ 這與我們用 EPT 量到的「名單關了兩座、全國燒的量沒變」互相印證。

路徑(KF25 §26.3):
  · 2028 起  產能 ≈ 丹麥自己的可燒垃圾量
  · 2030–31 仍進口約 0.03 Mt(佔總量 0.9%)
  · 2032     產能 = 丹麥垃圾量
  · 2033–35  小幅**出口** 約 0.01 Mt(0.2%)
  · 2035–50  🔴 **假設固定不變**(署方明說「沒有專業基礎可以預測」)
排序:先減進口 → 再減本國產能 → 最後轉出口。
⚠️ KF25 的焚化排放**高於** KF24,因為垃圾熱價格上限提高 + 配額價下降
   → 焚化廠更賺 → **關得比 KF24 預期的少**。
"""

__all__ = ["DK2_CHP", "DK1_CHP", "CONDENSING", "PIPELINE_MW", "PIPELINE_MW_KF25",
           "WASTE_CAPACITY_PATH"]

if __name__ == "__main__":
    print("KF25/KF26 假設的最後完整運轉年 — DK2 中央熱電機組\n")
    for k, v in sorted(DK2_CHP.items(), key=lambda kv: kv[1]["last_full_year"] or 9999):
        print(f"  {v['last_full_year']}  {k:6s} {v['title']}")
    print("\n全國熱容量 pipeline (KF26, MW):")
    for tech, yrs in PIPELINE_MW.items():
        print(f"  {tech:16s} " + "  ".join(f"{y}:{m:,}" for y, m in yrs.items()))
