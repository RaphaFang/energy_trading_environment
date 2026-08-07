"""Tier-3 燃料價 — 天然氣(TTF)、煤(API2 ARA)、碳(EUA),外加 EUR/USD 匯率。

為什麼要這些:殘餘負載告訴你**需要多少**火力(量),燃料價告訴你那些火力**多貴**(價)。
熱側的 CHP 模型直接用它們算邊際成本。

來源:yfinance(Yahoo Finance)。ticker 與**原始單位**:
  TTF=F     Dutch TTF Natural Gas    EUR/MWh    2019+ 完整
  MTF=F     Coal API2 CIF ARA        **USD/公噸**  2019+ 完整
  CO2.L     SparkChange Physical EUA ETC  EUR/tCO2   僅 2021-10 起
  EURUSD=X  歐元/美元匯率              —          煤價換算成 EUR 要用

為什麼煤用 ARA 不用「丹麥煤價」:煤是全球海運商品,北歐(含丹麥)的參考價**就是**
API2 CIF ARA(鹿特丹)。沒有丹麥煤價這種東西。同理碳價是 EU ETS 全歐單一價。
只有生質是區域性定價,需要丹麥能源署的資料(**目前仍缺**)。

**儲存原則:raw。** 存 Yahoo 回傳的完整 OHLCV,不挑欄位、不換單位、不換幣別。
  - 煤的 USD→EUR、公噸→MWh_fuel 的換算是**分析時**才做的事(見 load_duckdb.build_fuel),
    不在儲存時做。這樣換算規則改了不用重抓。
  - 舊的「只存收盤價」單欄檔案留在 new_data/fuel/ 沒動;新的 raw 檔在 new_data/fuel/raw/。

leak 安全:期貨結算價當天就公開,而合併成逐時是在 load_duckdb 用「交易日 −2 天」
的收盤價往回配(隔日競價中午前截標,那時只知道 ≤D-2)。leak 防護在合併層,不在這裡。

用法:python new_src/data/fuel_prices.py
"""

import glob
from pathlib import Path

import pandas as pd

FUEL = Path("new_data/fuel")
RAW = FUEL / "raw"  # 完整 OHLCV,原始單位
MANUAL = FUEL / "manual"  # 使用者手動補的 CSV(碳價 2019→2021-10)
START, END = "2019-01-01", "2025-10-01"

# Yahoo ticker -> (檔名, 原始單位) — 檔名帶幣別,避免日後誤用
TICKERS = {
    "TTF=F": ("ttf_gas_eur_mwh", "EUR/MWh"),
    "MTF=F": ("api2_coal_usd_t", "USD/tonne"),
    "CO2.L": ("eua_co2_eur_t", "EUR/tCO2"),
    "EURUSD=X": ("eurusd_rate", "USD per EUR"),
}


def _have(name: str) -> bool:
    return bool(glob.glob(str(RAW / f"{name}_*.parquet")))


def pull_yahoo() -> None:
    import yfinance as yf  # ponytail: heavy import, only when actually pulling

    RAW.mkdir(parents=True, exist_ok=True)
    for tk, (name, unit) in TICKERS.items():
        if _have(name):
            print(f"  · {name}: 已存在,跳過")
            continue
        d = yf.download(tk, start=START, end=END, progress=False, auto_adjust=False)
        if d.empty:
            print(f"  ✗ {name} ({tk}): 抓不到")
            continue
        if isinstance(d.columns, pd.MultiIndex):  # 單一 ticker 也會回 MultiIndex
            d.columns = d.columns.get_level_values(0)
        d.index.name = "date"
        p = RAW / f"{name}_{START}_{END}.parquet"
        d.to_parquet(p, engine="pyarrow", compression="snappy")
        print(
            f"✓ {name:18} [{unit:11}] {len(d):>5} 天  "
            f"{d.index.min().date()} → {d.index.max().date()}  欄位={list(d.columns)}"
        )


def load_manual() -> None:
    """吃 new_data/fuel/manual/ 裡任何 Date+Price 的 CSV(補碳價 2019→2021-10)。

    來源建議:Sandbag carbon price viewer、EEA datahub、investing.com 的
    Carbon Emissions Futures 歷史資料匯出。丟進去重跑就會被吃掉。
    """
    csvs = glob.glob(str(MANUAL / "*.csv"))
    if not csvs:
        print(f"  (manual/ 沒有 CSV → 碳價仍只有 2021-10 起,涵蓋約 52%)")
        return
    for f in csvs:
        raw = pd.read_csv(f)
        date_col = next(
            c for c in raw.columns if "date" in c.lower() or "time" in c.lower()
        )
        price_col = next(
            c
            for c in raw.columns
            if c != date_col and ("price" in c.lower() or "close" in c.lower())
        )
        s = (
            pd.Series(
                pd.to_numeric(
                    raw[price_col].astype(str).str.replace(",", ""), errors="coerce"
                ).values,
                index=pd.to_datetime(raw[date_col], errors="coerce", dayfirst=False),
            )
            .dropna()
            .sort_index()
        )
        s.index.name = "date"
        p = FUEL / f"eua_co2_eur_t_manual_{START}_{END}.parquet"
        s.rename("Close").to_frame().to_parquet(
            p, engine="pyarrow", compression="snappy"
        )
        print(
            f"✓ manual 碳價: {s.index.min().date()} → {s.index.max().date()} ({len(s)} 天) → {p}"
        )


def main() -> None:
    MANUAL.mkdir(parents=True, exist_ok=True)
    pull_yahoo()
    load_manual()
    print(
        "\n⚠️ 仍缺:**生質燃料價**(木片/顆粒)。無國際期貨,需丹麥能源署\n"
        "   『Samfundsøkonomiske beregningsforudsætninger』或 Energipriser 統計。"
    )


if __name__ == "__main__":
    main()
