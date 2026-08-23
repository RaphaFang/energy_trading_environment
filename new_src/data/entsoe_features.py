"""Tier-2 features from ENTSO-E Transparency Platform (day-ahead, leak-free).

Needs: pip install entsoe-py   and   export ENTSOE_TOKEN=<your token>
Get a token: register at https://transparency.entsoe.eu, then email
transparency@entsoe.eu asking for "Restful API access" (grant is manual).

Two layers, kept apart on disk (never overwrites raw):
  RAW      new_data/entsoe/*.parquet          — exactly what the API returned
  DERIVED  new_data/entsoe/derived/*.parquet  — our own calculations (residual)

RAW pulls:
  1. day-ahead LOAD forecast — DK_1/DK_2 (fills Energinet gap) + DE_LU/SE_3/SE_4
     (neighbours, so we can build their residual = load − wind − solar)
  2. neighbour wind+solar day-ahead fc — DE_LU/SE_3/SE_4 (NOT DK: Energinet already has it)
  3. day-ahead NTC — DK↔DE / DK↔NL (the borders that publish it)
  4. offered capacity — DK↔NO/SE + DK1↔DK2 (Nordic/internal borders NTC endpoint omits)

DERIVED:
  neighbour RESIDUAL = load_fc − (wind_fc + solar_fc). The generation forecast alone
  is half the story: a windy Germany only dumps cheap power into DK if its OWN demand
  doesn't soak it up. residual = net surplus/deficit = the real cross-border push.
"""

import glob
import os
from pathlib import Path

import pandas as pd
from entsoe import EntsoePandasClient

RAW = Path("new_data/entsoe")
DERIVED = RAW / "derived"

# DK_1/DK_2 fill Energinet's load-fc gap; DE_LU/SE_3/SE_4 let us build neighbour residual
LOAD_ZONES = ["DK_1", "DK_2", "DE_LU", "SE_3", "SE_4"]
RES_ZONES = ["DE_LU", "SE_3", "SE_4"]  # neighbour wind+solar day-ahead forecast
NEIGHBOURS = [
    "DE_LU",
    "SE_3",
    "SE_4",
]  # zones we compute residual for (load & res both pulled)

# Borders whose day-ahead NTC IS published (Core region: DK↔DE, DK↔NL).
NTC_BORDERS = [("DK_1", "DE_LU"), ("DK_1", "NL"), ("DK_2", "DE_LU")]
# Nordic/internal borders the NTC endpoint omits (flow-based) → offered_capacity has them.
OFFERED_BORDERS = [
    ("DK_1", "NO_2"),
    ("DK_1", "SE_3"),
    ("DK_2", "SE_4"),
    ("DK_1", "DK_2"),
]

START = pd.Timestamp("2019-10-01", tz="UTC")  # align with earliest output-forecast data
# 2026-08-21:END 改成「今天」(使用者定案的預設窗口),START 維持 2019-10-01
# —— 那是**來源**的限制(輸出預測最早只到那裡),不是設定。
END = pd.Timestamp(pd.Timestamp.today().strftime("%Y-%m-%d"), tz="UTC")


def _have(name: str) -> bool:
    """🔴 只看**這次窗口**的檔 —— 舊窗口的檔不算數,否則窗口永遠延長不了。"""
    return (RAW / f"{name}_{START.date()}_{END.date()}.parquet").exists()


def _old_raw(name: str, folder) -> list:
    new = folder / f"{name}_{START.date()}_{END.date()}.parquet"
    return sorted(q for q in folder.glob(f"{name}_*.parquet") if q != new)


def _save(df: pd.DataFrame, name: str, folder: Path = RAW) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}_{START.date()}_{END.date()}.parquet"
    _old = _old_raw(name, folder)
    df.to_parquet(p, engine="pyarrow", compression="snappy")
    import sys as _s
    from pathlib import Path as _P

    _s.path.insert(0, str(_P(__file__).resolve().parent))
    from window import retire_superseded

    retire_superseded(p, _old, None)
    print(f"✓ {name}: {len(df)} rows  {df.index.min()} → {df.index.max()}  → {p}")


def _fetch_yearly(call, prefix: str) -> pd.DataFrame | None:
    """ENTSO-E caps each request at 1 year → loop in <=1y chunks, concat.

    Per-chunk tolerant: a 6-year pull over many series will hit gaps/transient
    errors; one bad chunk must not sink the whole series. Handles Series+DataFrame.
    """
    frames = []
    cur = START
    while cur < END:
        chunk_end = min(cur + pd.DateOffset(years=1), END)
        try:
            out = call(cur, chunk_end)
            frames.append(out.to_frame() if isinstance(out, pd.Series) else out)
        except Exception as e:  # ponytail: entsoe-py raises many types; treat all as "no data this chunk"
            print(
                f"  · {prefix} {cur.date()}→{chunk_end.date()}: skip ({type(e).__name__})"
            )
        cur = chunk_end
    if not frames:
        print(f"  ✗ {prefix}: no data at all, skipping")
        return None
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index().tz_convert("UTC")
    df.index.name = "timestamp_utc"
    return df.add_prefix(f"{prefix}_")


def _read_raw(prefix: str) -> pd.DataFrame:
    (f,) = glob.glob(str(RAW / f"{prefix}_*.parquet"))
    return pd.read_parquet(f)


def build_residuals() -> None:
    """DERIVED: residual = load_fc − total(wind+solar fc), per neighbour, hourly."""
    for z in (n.lower() for n in NEIGHBOURS):
        name = f"residual_{z}"
        # 🔴 只看**這次窗口**的檔 —— 用 `{name}_*` 會在 raw 已經延長之後仍然跳過,
        #    結果 derived 停在舊窗口而 raw 到今天,兩者不同步(2026-08-21 踩到)。
        if (DERIVED / f"{name}_{START.date()}_{END.date()}.parquet").exists():
            print(f"  · {name}: already built, skip")
            continue
        load = _read_raw(f"loadfc_{z}")
        res = (
            _read_raw(f"resfc_{z}").resample("1h").mean()
        )  # DE_LU is 15-min → to hourly
        (load_col,) = [c for c in load.columns if c.endswith("Forecasted Load")]
        # skipna: SE solar is unpublished in early years → treat as 0 (wind dominates there)
        resid = load[load_col] - res.sum(axis=1)
        df = resid.rename(f"{z}_residual_mwh").to_frame()
        df.index.name = "timestamp_utc"
        _save(df.dropna(), name, folder=DERIVED)


def main():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        raise SystemExit("Set ENTSOE_TOKEN first (see module docstring).")
    client = EntsoePandasClient(api_key=token)

    for z in LOAD_ZONES:  # day-ahead load forecast (process_type A01)
        name = f"loadfc_{z.lower()}"
        if _have(name):
            print(f"  · {name}: already pulled, skip")
            continue
        df = _fetch_yearly(
            lambda s, e, z=z: client.query_load_forecast(z, start=s, end=e), z.lower()
        )
        if df is not None:
            _save(df, name)

    for z in RES_ZONES:  # day-ahead wind + solar forecast
        name = f"resfc_{z.lower()}"
        if _have(name):
            print(f"  · {name}: already pulled, skip")
            continue
        df = _fetch_yearly(
            lambda s, e, z=z: client.query_wind_and_solar_forecast(z, start=s, end=e),
            z.lower(),
        )
        if df is not None:
            _save(df, name)

    for (
        a,
        b,
    ) in NTC_BORDERS:  # day-ahead NTC, both directions (import vs export capacity)
        for frm, to in ((a, b), (b, a)):
            name = f"ntc_{frm.lower()}_{to.lower()}"
            if _have(name):
                print(f"  · {name}: already pulled, skip")
                continue
            df = _fetch_yearly(
                lambda s, e, frm=frm, to=to: (
                    client.query_net_transfer_capacity_dayahead(frm, to, start=s, end=e)
                ),
                name,
            )
            if df is not None:
                _save(df, name)

    for (
        a,
        b,
    ) in OFFERED_BORDERS:  # Nordic/internal: offered capacity (A01=daily), both dirs
        for frm, to in ((a, b), (b, a)):
            name = f"oc_{frm.lower()}_{to.lower()}"
            if _have(name):
                print(f"  · {name}: already pulled, skip")
                continue
            df = _fetch_yearly(
                lambda s, e, frm=frm, to=to: client.query_offered_capacity(
                    frm, to, "A01", start=s, end=e
                ),
                name,
            )
            if df is not None:
                _save(df, name)

    build_residuals()  # DERIVED layer, from the raw pulls above


if __name__ == "__main__":
    main()
