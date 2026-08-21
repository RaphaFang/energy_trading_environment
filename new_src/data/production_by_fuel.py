import pandas as pd
import requests

from _http import paged_json

# Hourly generation split by fuel per price area. The heat track's key validation data:
# Biomass / Waste / FossilGas are almost all CHP in Denmark, so their hourly pattern is
# the observable footprint of heat-driven dispatch. Also carries TotalLoad and exchanges.
URL = "https://api.energidataservice.dk/dataset/ElectricityBalanceNonv"


def fetch(start: str, end: str, area: str) -> pd.DataFrame:
    df = paged_json(
        URL,
        {"filter": f'{{"PriceArea":["{area}"]}}', "sort": "HourUTC ASC", "limit": 0},
        start,
        end,
    )
    df["HourUTC"] = pd.to_datetime(df["HourUTC"], utc=True)
    for c in df.columns:
        if c not in ("HourUTC", "HourDK", "PriceArea"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("HourUTC").reset_index(drop=True)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from window import END, START, paths_for, retire_superseded
    out_dir = Path("new_data/production")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        path, _old = paths_for(out_dir, f"production_{area.lower()}")
        if path.exists():  # skip-if-exists:絕不覆蓋已抓好的原始檔
            print(f"· {area}: 已存在,跳過 → {path}")
            continue
        d = fetch(START, END, area)
        assert len(d), f"{area}: no rows"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        retire_superseded(path, _old, "HourUTC")
        therm = [c for c in ("Biomass", "Waste", "FossilGas") if c in d]
        print(
            f"✓ {area}: {len(d)} rows  {d['HourUTC'].min()} → {d['HourUTC'].max()}\n"
            f"   熱電機組平均出力 MW: "
            + ", ".join(f"{c}={d[c].mean():.0f}" for c in therm)
            + f"  → {path}"
        )
