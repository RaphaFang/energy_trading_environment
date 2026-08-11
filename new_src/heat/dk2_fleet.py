"""大哥本哈根(DK2)接在傳輸網上的**實際機組**與容量 — 取代 DEA 的「典型機組」容量。

**為什麼需要這個檔**:DEA 目錄給的是技術原型的典型容量,不是這個熱網真的有什麼。
容量直接決定**每個 agent 在市場上有多大**,而市場力正是本論文的主題 → 拿原型容量
當 agent 大小,等於用一個編出來的數字回答研究問題。

⚠️ **不要用 DEA 原型容量或全國平均填空格。** 查不到就是 `NOT_FOUND`,
   讓它在下游炸掉,好過默默給一個看起來合理的數字。

來源共三個,可信度依序:
  (V) varmelast.dk `/api/v1/heatdata` 的 `objects` 說明文字 —— **熱網營運者自己講的
      熱容量**,對 MW_th 是最高權威。快照見 `new_data/heat/varmelast_dictionary.json`
      同批抓取(2026-08-09)。
  (E) ENTSO-E `query_installed_generation_capacity_per_unit('DK_2')` —— **廠級** MW_e,
      但只涵蓋大機組:六台裡只有 Amager 與 Avedøre 進得去,三家垃圾廠與 Køge 都沒有。
  (M) Energinet `CapacityPerMunicipality` —— **只有「該市 ≥100MW 機組合計」與
      「<100MW 合計」**,沒有機組名稱。所以它給的是**上界不是機組容量**,
      但它的**逐月變動**能定出商轉/除役時點(這是它最有價值的地方)。

用法:python new_src/heat/dk2_fleet.py    (印出車隊 + self-check)
"""

NOT_FOUND = None
"""查不到就是查不到。**不要**用 DEA 原型容量或全國平均補 —— 見模組 docstring。"""


FLEET = {
    "amager": dict(
        title="Amagerværket (AMV1 + AMV4/BIO4)",
        owner="HOFOR Energiproduktion",
        network="CTR",
        fuel="biomass",
        unit_type="extraction",  # 抽汽式,solve() 適用
        mw_th=810.0,  # (V) 「Den samlede kapacitet er på 810 MJ/s fjernvarme」(兩塊合計)
        mw_e=166.0,  # (M) 2022-08 起該市 ≥100MW 合計 = 166,且只剩 1 台 → 即 AMV4
        mw_e_note="(M) 廠級近似:AMV3(250 MW_e 燃煤)2020-03 除役後,København 的 "
        "≥100MW 只剩一台。AMV1 較小,落在 <100MW 那組,無法單獨切出。"
        "(E) ENTSO-E 記 Amagervaerket 479 MW_e 但燃料標成 Fossil Hard coal —— "
        "那是**過期登記**(AMV3 已除役、AMV1/AMV4 燒生質),不要用。",
        commissioned="2019-10",  # (M) 該市 ≥100MW 從 1 台 250 → 2 台 399(+149)
        commissioned_note="(M) 2019-10 出現第二台 ≥100MW(+149 MW_e)= AMV4/BIO4 併網;"
        "2020-03 掉回 1 台 149 MW_e = AMV3 燃煤除役。**兩個時點都是從逐月變動推出來的**,"
        "不是官方公告日期。",
        blocked_by="生質燃料價缺",  # 技術上可跑,但沒有燃料價
    ),
    "avedoere": dict(
        title="Avedøreværket (AVV1 + AVV2)",
        owner="Ørsted",
        network="CTR/VEKS",
        fuel="biomass",  # (V) 主要生質,可部分燒煤與天然氣
        unit_type="extraction",
        mw_th=880.0,  # (V) 「Den samlede kapacitet er på 880 MJ/s fjernvarme」(兩塊合計)
        mw_e=815.0,  # (E) ENTSO-E 廠級 815 MW_e,Biomass;(M) 亦為 815–823
        mw_e_note="(E)(M) 兩個獨立來源一致(815 vs 815–823)→ 這是六台裡最可信的 MW_e。"
        "⚠️ 但這是 **AVV1+AVV2 合計**,使用者要求的「1 與 2 分開」**兩個來源都做不到**:"
        "ENTSO-E 記成單一 plant,Energinet 只給該市合計(2022-08 起記成 4 台)。",
        commissioned=NOT_FOUND,
        commissioned_note="(M) 2019-01 已存在 699 MW_e/2 台 → 商轉早於資料起點 2016,"
        "查不到。2022-08 從 2 台 699 跳到 4 台 815 是**登記單位重新切分**,不是新建。",
        blocked_by="生質燃料價缺",
    ),
    "koege": dict(
        title="Køge Kraftvarmeværk",
        owner="VEKS",
        network="VEKS",
        fuel="biomass",  # (V) 木片、磨屑、鋸末、橄欖核
        unit_type=NOT_FOUND,  # VEKS 稱「träfyret kedel」(鍋爐)→ 可能根本不是抽汽式
        mw_th=54.0,  # (V) 「Køge Kraftvarmeværks varmekapacitet er 54 MJ/s」
        mw_e=NOT_FOUND,
        mw_e_note="(M) Køge 全市 <100MW 合計 43.0 MW_e,**是該市所有小機組的總和,"
        "不是這一台的容量** → 只能當上界。ENTSO-E 不收 <100MW 機組。",
        commissioned=NOT_FOUND,
        commissioned_note="VEKS 官網:2012-05 啟動改建、2013-12 開始供 Køge Fjernvarme、"
        "2015 初接上 VEKS 傳輸網。**這些是供熱里程碑不是機組商轉年**,不當商轉年用。",
        blocked_by="生質燃料價缺 + 機組型式未確認",
    ),
    "arc": dict(
        title="ARC — Amager Ressource Center (Amager Bakke)",
        owner="ARC(市政合作社)",
        network="CTR + Amager 配網",
        fuel="waste",
        unit_type="back_pressure",  # 目錄裡 WtE 全是背壓 → solve() 現在不適用
        mw_th=250.0,  # (V) 「Den samlede varmekapacitet er 250 MJ/s」(兩條爐線共用汽輪機)
        mw_e=NOT_FOUND,
        mw_e_note="(M) 落在 København 的 <100MW 那組(全市 174–232 MW_e),"
        "與其他小機組混在一起,**切不出來**。ENTSO-E 不收。",
        commissioned=NOT_FOUND,
        commissioned_note="(M) København 的 <100MW 合計在 2019–2024 間多次跳動,"
        "但那一組混了太多機組,無法歸因到 ARC。",
        blocked_by=None,  # ✅ 2026-08-11 背壓式已實作
    ),
    "vestforbraending": dict(
        title="Vestforbrænding",
        owner="Vestforbrænding(市政合作社)",
        network="自有配網 + 餘量給 VEKS/CTR",
        fuel="waste",
        unit_type="back_pressure",
        mw_th=143.0,  # (V) 「Den samlede fjernvarmekapacitet er 143 MJ/s」(兩條爐線)
        mw_th_note="⚠️ **這 143 不全部進傳輸網**:(V) 明說 Vestforbrænding 先供自己在 "
        "Ballerup/Furesø/Gladsaxe/Herlev/Lyngby-Taarbæk 的配網,**餘量**才給 VEKS 與 CTR。"
        "當 agent 建模時要的是進傳輸網那一部分,不是 143。",
        mw_e=NOT_FOUND,
        mw_e_note="(M) Glostrup 全市 <100MW 合計 41.8 MW_e(2019–2022 完全不變)→ 上界。",
        commissioned=NOT_FOUND,
        blocked_by="進傳輸網的比例未知(背壓式本身已可跑)",
    ),
    "argo": dict(
        title="ARGO — Roskilde Kraftvarmeværk",
        owner="ARGO(市政合作社)",
        network="VEKS + Roskilde 配網",
        fuel="waste",
        unit_type="back_pressure",
        mw_th=120.0,  # (V) 「Den samlede fjernvarmekapacitet er 120 MJ/s」(兩座爐,各自鍋爐與汽輪機)
        mw_e=NOT_FOUND,
        mw_e_note="(M) Roskilde 全市 <100MW 合計 34.9 MW_e(2019–2022 完全不變)→ 上界。",
        commissioned=NOT_FOUND,
        blocked_by=None,  # ✅ 2026-08-11 背壓式已實作
    ),
}


# 蓄熱槽(三座,都在傳輸網上)。來源全部是 (V)。
# ⚠️ `/api/v1/heatdata/historical` **沒有蓄熱槽的數值序列** —— 只能用
#    「生產 − 消費 − 損失」反推,見 data/varmelast_heat.py 的 docstring。
STORAGE = {
    "amager_acc": dict(title="Varmeakkumulator, Amagerværket", mwh=1000.0, mw=300.0),
    "avedoere_acc": dict(
        title="Varmeakkumulatorer, Avedøreværket", mwh=2200.0, mw=330.0
    ),
    "hoeje_taastrup_pit": dict(
        title="Høje Taastrup Damvarmelager", mwh=3300.0, mw=30.0, cycles_per_year=27.5
    ),
}

# varmelast 自己公布的車隊合計(來源:/lastfordeling/hvad-er-lastfordeling)。
# 拿來當交叉檢查 —— **對不太起來,差距記在 demo() 裡**。
PUBLISHED_TOTALS = dict(
    chp_mw_th=1600.0, waste_mw_th=425.0, peak_mw_th=1300.0, storage_mw=690.0
)


def derived_mw_e(key: str, cb: float) -> float:
    """**背壓式**機組的電容量可以從熱容量反推:P = Cb·Q ⇒ P_max = Cb · Q_max。

    這不是繞過 NOT_FOUND,是背壓式的**物理定義**:熱電綁死在一條線上,
    所以「電容量」與「熱容量」不是兩個獨立的數,給一個就決定另一個。
    熱容量來自 varmelast(熱網營運者自己講的,對 MW_th 是最高權威),
    Cb 來自 DEA 目錄 → 兩個都是真值,推出來的也是。

    ⚠️ 只對 `unit_type == "back_pressure"` 成立。抽汽式有凝汽尾,
    電容量是獨立的自由度,不能這樣推。
    """
    v = FLEET[key]
    assert v["unit_type"] == "back_pressure", (
        f"{key} 不是背壓式,電容量不能從熱容量反推(抽汽式有獨立的凝汽容量)"
    )
    return cb * v["mw_th"]


def runnable() -> dict:
    """現在真的能餵進 `chp.solve()` 的機組。

    2026-08-11 起 = **ARC 與 ARGO**(背壓式已實作,垃圾用處理費當負燃料價,
    電容量由 `derived_mw_e()` 從熱容量反推)。生質三台仍卡燃料價;
    Vestforbrænding 卡「進傳輸網的比例未知」。
    """
    return {k: v for k, v in FLEET.items() if not v.get("blocked_by")}


def demo() -> None:
    # ① 熱容量六台都要有(這是 varmelast 自己講的,沒有理由缺)
    for k, v in FLEET.items():
        assert v["mw_th"], f"{k} 缺 mw_th,但 varmelast 的說明文字有給"
    # ② MW_e 只有兩台查得到 —— 這個事實本身要被鎖住,免得日後被人偷偷填滿
    have_e = [k for k, v in FLEET.items() if v["mw_e"] is not NOT_FOUND]
    assert set(have_e) == {"amager", "avedoere"}, (
        f"MW_e 應該只有 Amager 與 Avedøre 查得到,現在是 {have_e} —— "
        "若有人補了值,請確認來源是機組級而不是全市合計(那只是上界)"
    )
    # ③ 交叉檢查:分項加總 vs varmelast 自己公布的合計
    chp = sum(v["mw_th"] for v in FLEET.values() if v["fuel"] == "biomass")
    wst = sum(v["mw_th"] for v in FLEET.values() if v["fuel"] == "waste")
    print(
        f"  熱容量 ok: 熱電 {chp:.0f} MW_th(公布 {PUBLISHED_TOTALS['chp_mw_th']:.0f},"
        f"差 {chp / PUBLISHED_TOTALS['chp_mw_th'] - 1:+.0%})、"
        f"垃圾 {wst:.0f}(公布 {PUBLISHED_TOTALS['waste_mw_th']:.0f},"
        f"差 {wst / PUBLISHED_TOTALS['waste_mw_th'] - 1:+.0%})"
    )
    # 差距是真的,不是我算錯 → 明講,不要假裝一致
    assert abs(chp / PUBLISHED_TOTALS["chp_mw_th"] - 1) < 0.15
    assert abs(wst / PUBLISHED_TOTALS["waste_mw_th"] - 1) < 0.25

    # ④ 蓄熱:三座合計 vs 公布值
    smw = sum(v["mw"] for v in STORAGE.values())
    smwh = sum(v["mwh"] for v in STORAGE.values())
    print(
        f"  蓄熱 ok: {smw:.0f} MW / {smwh:,.0f} MWh(公布 {PUBLISHED_TOTALS['storage_mw']:.0f} MW)"
        f" —— 對照 chp.Plant 目前的 s_max=2,880 MWh(DEA 單一 TTES)"
    )

    # ⑤ 🔴 最重要的一行:把「一台都跑不了」變成會被看到的事實
    r = runnable()
    assert set(r) == {"arc", "argo"}, (
        f"預期 ARC 與 ARGO 可跑(背壓式已實作、垃圾有處理費當燃料價),實際 {list(r)}"
    )
    print(
        f"  ✅ 可跑機組 = {len(r)}/6:{', '.join(r)}(背壓式 2026-08-11 已實作,"
        f"垃圾用處理費當負燃料價)"
    )
    print(
        "  🔴 仍不可跑:生質 3 台卡**燃料價缺**;Vestforbrænding 卡**進傳輸網的比例未知**。"
    )


def main() -> None:
    print("=== DK2 傳輸網上的實際機組(varmelast 車隊)===\n")
    print(f"  {'機組':<36}{'MW_th':>7}  {'MW_e':>10}  {'燃料':<8}{'型式':<15}業主")
    print("  " + "-" * 104)
    for v in FLEET.values():
        e = f"{v['mw_e']:.0f}" if v["mw_e"] is not NOT_FOUND else "NOT_FOUND"
        ut = v["unit_type"] or "NOT_FOUND"
        print(
            f"  {v['title'][:35]:<36}{v['mw_th']:>7.0f}  {e:>10}  "
            f"{v['fuel']:<8}{ut:<15}{v['owner']}"
        )
    print(
        f"\n  商轉年份:只有 Amager 推得出來({FLEET['amager']['commissioned']}),其餘 NOT_FOUND"
    )
    print("\n=== 蓄熱槽 ===")
    for v in STORAGE.values():
        print(f"  {v['title'][:44]:<46}{v['mwh']:>8,.0f} MWh  {v['mw']:>5.0f} MW")
    print("\n=== self-check ===")
    demo()
    print(
        "\n⚠️ MW_e 四台 NOT_FOUND 不是懶得查:ENTSO-E 只收大機組、Energinet 只給"
        "**全市合計**(是上界不是機組容量)、業者官網是 JS 頁面沒有數字。"
        "\n   要真值的下一步:能源署 Energiproducenttællingen(EPT)電廠普查,或直接問 varmelast。"
    )


if __name__ == "__main__":
    main()
