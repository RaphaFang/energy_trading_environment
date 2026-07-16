"""Tier-3 fuel prices: gas (TTF) + carbon (EUA) — the marginal cost of thermal power.

Why: residual tells you HOW MUCH thermal is needed (量); fuel price tells you how
EXPENSIVE that thermal is (價). Same residual in 2020 (cheap gas) vs 2022 (€339 gas)
= totally different price. This is the missing driver for the 2021-22 crisis regime.

Two sources (as requested):
  - yfinance (Yahoo): gas TTF=F (full 2019+), carbon CO2.L (only from 2021-10)
  - manual CSV (investing.com / Ember): backfill carbon 2019 → 2021-10 — drop the
    downloaded CSV into new_data/fuel/manual/ and rerun; any Date+Price CSV works.

Daily series. Forward-fill to hourly + previous-day close (leak-safe) is done at
MERGE time, not here — here we just store the raw daily prices.
"""

import glob
from pathlib import Path

import pandas as pd

FUEL = Path("new_data/fuel")
MANUAL = FUEL / "manual"
START, END = "2019-01-01", "2025-10-01"

# Yahoo ticker -> our clean column/file name
TICKERS = {"TTF=F": "ttf_gas_eur_mwh", "CO2.L": "eua_co2_eur_t"}


def _have(name: str) -> bool:
    return bool(glob.glob(str(FUEL / f"{name}_*.parquet")))


def _save(s: pd.Series, name: str) -> None:
    FUEL.mkdir(parents=True, exist_ok=True)
    s = s.rename(name)
    s.index.name = "date"
    p = FUEL / f"{name}_{START}_{END}.parquet"
    s.to_frame().to_parquet(p, engine="pyarrow", compression="snappy")
    print(
        f"✓ {name}: {len(s)} days  {s.index.min().date()} → {s.index.max().date()}  → {p}"
    )


def pull_yahoo() -> None:
    import yfinance as yf  # ponytail: heavy import, only when actually pulling

    for tk, name in TICKERS.items():
        if _have(name):
            print(f"  · {name}: already pulled, skip")
            continue
        d = yf.download(tk, start=START, end=END, progress=False, auto_adjust=True)
        if d.empty:
            print(f"  ✗ {name} ({tk}): no data")
            continue
        close = d["Close"]
        close = (
            close.iloc[:, 0] if hasattr(close, "columns") else close
        )  # unwrap multiindex
        _save(close.dropna(), name)


def load_manual() -> None:
    """Read any Date+Price CSV dropped in new_data/fuel/manual/ (investing.com/Ember export)."""
    csvs = glob.glob(str(MANUAL / "*.csv"))
    if not csvs:
        print(
            f"  (no manual CSV in {MANUAL}/ — carbon starts 2021-10 until you add one)"
        )
        return
    for f in csvs:
        raw = pd.read_csv(f)
        # autodetect: first datetime-parseable column = date, first numeric = price
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
        name = "eua_co2_eur_t_manual"
        _save(s, name)
        print(
            f"    ↳ from {Path(f).name}: {s.index.min().date()} → {s.index.max().date()}"
        )


def main() -> None:
    MANUAL.mkdir(parents=True, exist_ok=True)  # so the drop-folder exists for the user
    pull_yahoo()
    load_manual()


if __name__ == "__main__":
    main()
