import pandas as pd
import requests

# Hourly generation split by fuel per price area. The heat track's key validation data:
# Biomass / Waste / FossilGas are almost all CHP in Denmark, so their hourly pattern is
# the observable footprint of heat-driven dispatch. Also carries TotalLoad and exchanges.
URL = "https://api.energidataservice.dk/dataset/ElectricityBalanceNonv"


def fetch(start: str, end: str, area: str) -> pd.DataFrame:
    r = requests.get(
        URL,
        params={
            "start": start,
            "end": end,
            "filter": f'{{"PriceArea":["{area}"]}}',
            "sort": "HourUTC ASC",
            "limit": 0,
        },
        timeout=180,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json()["records"])
    df["HourUTC"] = pd.to_datetime(df["HourUTC"], utc=True)
    for c in df.columns:
        if c not in ("HourUTC", "HourDK", "PriceArea"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("HourUTC").reset_index(drop=True)


if __name__ == "__main__":
    from pathlib import Path

    START, END = "2019-01-01", "2026-07-08"
    out_dir = Path("new_data/production")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        path = out_dir / f"production_{area.lower()}_{START}_{END}.parquet"
        if path.exists():  # skip-if-exists:絕不覆蓋已抓好的原始檔
            print(f"· {area}: 已存在,跳過 → {path}")
            continue
        d = fetch(START, END, area)
        assert len(d), f"{area}: no rows"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        therm = [c for c in ("Biomass", "Waste", "FossilGas") if c in d]
        print(
            f"✓ {area}: {len(d)} rows  {d['HourUTC'].min()} → {d['HourUTC'].max()}\n"
            f"   熱電機組平均出力 MW: "
            + ", ".join(f"{c}={d[c].mean():.0f}" for c in therm)
            + f"  → {path}"
        )
