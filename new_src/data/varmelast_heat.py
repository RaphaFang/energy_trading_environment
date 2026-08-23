"""大哥本哈根(DK2)實際逐時區域供熱資料 — varmelast.dk 公開 API。

**為什麼這份資料是關鍵**:DK1 沒有公開的逐時 DH 需求,只能用度日代理;而 2026-08-05
的檢驗證明「代理 vs CHP 發電量」根本驗不動(發電量由電價主導,識別力不足)。
這份 DK2 實際熱需求讓我們可以:
  1. **校準代理的函數形式**(T_base、基載比例、日內形狀)—— 在有真值的地方校準,
     再把校準好的形式移轉到 DK1,並在論文中說明外推假設。
  2. 拿到真實的熱需求量級,取代 `heat.demand.ANNUAL_TWH_DK1` 那個佔位值。
  3. legend 的分類(廢棄物/熱電/尖峰生質/尖峰氣/本地)**幾乎一對一對應 heat/chp.py 的
     LP 結構** → 可以直接驗證排程模型,不只驗證需求代理。

涵蓋:**2021-01 → 2026-07,逐時,48,887 列,每年都完整**(單位 MJ/s = MW_th)。
2019/2020 沒有資料。當初 5 個季度的缺口是抓取失敗,2026-08-11 已用 `fill_gaps()` 補齊。

🔴 **這個端點同時回傳兩類欄位,用途完全不同,混用會造成循環論證**(2026-08-09 查證,
官方欄位定義快照存在 `new_data/heat/varmelast_dictionary.json`):

  **① 消費(varmebehov 的實現值)—— 這才可以當 LP 的熱需求輸入**
      BE-EO-CTR-EFF          CTR 傳輸網熱消費(均 709 MW_th)
      DAP-VEKS-FORBRUG-EFF   VEKS 傳輸網熱消費(均 287 MW_th;key 裡 FORBRUG = 消費)

  **② 生產(varmeplan 的實現值)—— 只能當驗證對照,絕不可當輸入**
      TOTAL                  官方 title「Produktion i alt」= 總生產,**不是需求**
      BE-VL-KRAFTV-EF 熱電 64.6% / BE-VL-AFFALD-EF 焚化 27.7% / BE-VL-SPIDS-GAS-EF 尖峰氣 4.0%
      BE-VL-IO-EF 工業餘熱 / BE-VL-EVO-EF 電鍋爐 / BE-VL-VP-EF 熱泵 / BE-VL-OD-EF 資料中心餘熱
      BE-VL-BIO-EF、BE-VL-SPIDS-OLIE-EF 尖峰生質/油 / BE-VL-BG-EF 沼氣 / BE-VL-SOL-EF 太陽能熱
      這些序列**已經含蓄熱槽調度與經濟最佳化的結果** → 拿來當熱需求就是拿模型的輸出當輸入。

  🔴 **BE-VL-TOTAL-FAK 不是熱量欄** —— 官方 title「CO2 - Udledning」,單位 **Kg/GJ**
     (排放強度)。加進 MW_th 的分母會算錯佔比(先前 STATUS.md 的 64.4/27.3 就是這樣來的)。
  ⚠️ LOCAL(Lokal produktion)全期恆為 0,沒有資料。官網說明有一部分熱是本地直接送進
     配網、不經傳輸網 → **CTR+VEKS 是「傳輸層取用量」,不是終端消費總量**。對本模型這正好
     是對的邊界(LP 調度的就是接在傳輸網上的機組),但論文裡要標明是傳輸層口徑。

**生產 ≠ 消費,差額是蓄熱槽 + 管網損失**:dictionary 明寫 TOTAL 是
`Produktion i alt *eksklusive op- og afladning på varmelagre`(**不含**蓄熱充放)。
實測 2023–25:gap = 生產 − 消費,均 +21 MW、std 99、**41% 小時為負**、日內有清楚充放循環;
月均 gap 約佔消費 **1.0–3.7%**(≈2%)= 傳輸網損失。三座蓄熱槽(Amager 1,000 MWh/±300 MJ/s、
Avedøre 2,200 MWh/±330 MJ/s、Høje Taastrup 池儲 3,300 MWh/±30 MJ/s)在 `/api/v1/heatdata`
的 objects 裡有列,但**沒有數值序列** → 要重建蓄熱只能用 gap 扣掉損失近似。

**這是事後實測,不是事前計畫**:dictionary 寫「Data vises med 90 minutters forsinkelse」
(延遲 90 分鐘、每 5 分鐘更新 = 遙測簽名);CO2 說明寫熱電/焚化排放是 `målte værdier`(量測值)。
純需求**預測**在另一個 host:`app-lasso-api-prod-001.azurewebsites.net/api/prognosis/overall`
(「14-døgns varmeprognose」,欄位 totalDemand + forecastWaste),但**只往未來 14 天、只有日均、
無歷史** → 歷史逐時需求只能用 CTR+VEKS。

其他端點:`/api/v1/heatdata`(廠級即時值 + 業主與容量)、`/api/v1/heatdata/dictionary`
(唯一的官方欄位定義,已快照)、`/api/v1/heatdata/revisionplan`(機組檢修計畫)。

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


def fill_gaps(path, ranges) -> int:
    """補抓指定期間並**合併**進既有檔(不是重抓整份)。回傳新增列數。

    為什麼需要:2026-08-09 盤點發現 5 個季度當初因連線中斷整段沒抓到
    (2021 Q1/Q3、2022 Q1/Q3/Q4)—— **那是抓取失敗不是沒有資料**,而 2022 正好是
    能源危機年、電價最極端,對研究策略行為最有價值。

    安全作法(`new_data/` 是 gitignored,刪了無法還原):
      ① 只**新增**既有檔沒有的時間戳,既有列一律以舊檔為準
      ② 寫入前先驗證「舊資料逐格不變」,不通過就中止
      ③ 先寫 .tmp 再 rename,中途失敗不會留下半個檔
    """
    old = pd.read_parquet(path)
    old["timestamp"] = pd.to_datetime(old["timestamp"], utc=True)
    parts = []
    for a, b in ranges:
        try:
            p = fetch(a, b)
        except Exception as e:
            print(f"  ! {a}→{b}: {type(e).__name__} {str(e)[:60]}")
            continue
        print(f"  · {a}→{b}: 回傳 {len(p)} 列")
        if len(p):
            parts.append(p)
        time.sleep(2)  # 禮貌間隔:小型公用事業站
    if not parts:
        print("  (沒有任何新資料)")
        return 0

    new = pd.concat(parts)
    new = new[~new["timestamp"].isin(old["timestamp"])]  # 只要舊檔沒有的
    if not len(new):
        print("  (回傳的時間戳舊檔都已經有了,不動檔案)")
        return 0
    merged = (
        pd.concat([old, new])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="first")  # 衝突時保留舊值
        .reset_index(drop=True)
    )
    # ② 舊資料必須逐格不變 —— 這是「合併」而不是「重抓」的定義
    chk = merged[merged["timestamp"].isin(old["timestamp"])].reset_index(drop=True)
    o = old.sort_values("timestamp").reset_index(drop=True)
    assert len(chk) == len(o), f"舊列數變了:{len(o)} → {len(chk)}"
    assert chk["timestamp"].equals(o["timestamp"]), "舊時間戳被動到了"
    for c in o.columns:
        if c != "timestamp":
            assert chk[c].equals(o[c]), f"舊資料的 {c} 欄被改動了 —— 中止"
    tmp = path.with_suffix(".tmp.parquet")
    merged.to_parquet(tmp, index=False, engine="pyarrow", compression="snappy")
    tmp.replace(path)
    return len(new)


if __name__ == "__main__":
    from pathlib import Path

    out_dir = Path("new_data/heat")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "varmelast_ckb_2021_2026.parquet"
    if path.exists():
        # 當初失敗的 5 個季度(見 fill_gaps 的 docstring)。順帶試 2021 Q1 的 1–2 月,
        # 確認「2021 起才有資料」是真的,還是也只是沒抓到。
        GAPS = [
            ("2021-01-01", "2021-04-01"),
            ("2021-07-01", "2021-10-01"),
            ("2022-01-01", "2022-04-01"),
            ("2022-07-01", "2022-10-01"),
            ("2022-10-01", "2022-12-31"),
        ]
        # 🔑 2026-08-21:除了補洞,還要**往前延到今天**(使用者定案的預設窗口)。
        #    `fill_gaps` 本來就只新增、且寫入前逐格驗證舊資料沒被動到 → 直接沿用。
        import pandas as _pd

        _last = _pd.read_parquet(path)["timestamp"].max()
        _today = _pd.Timestamp.today().normalize().tz_localize("UTC")
        if _last < _today:
            GAPS.append((_last.strftime("%Y-%m-%d"), _today.strftime("%Y-%m-%d")))
            print(f"· 往前延伸:{_last.date()} → {_today.date()}")
        print(f"· 檔案已存在 → 補抓 {len(GAPS)} 個區間")
        n = fill_gaps(path, GAPS)
        d = pd.read_parquet(path)
        print(f"✓ 新增 {n:,} 列,現在共 {len(d):,} 列 → {path}")
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
