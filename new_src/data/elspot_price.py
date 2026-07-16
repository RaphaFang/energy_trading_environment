import requests
import pandas as pd

# Nord Pool day-ahead hourly spot price per bidding zone — the model TARGET (y).
# Actual settled prices; safe as the label. Can be negative (wind oversupply).
URL = "https://api.energidataservice.dk/dataset/Elspotprices"


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
        timeout=120,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json()["records"])
    df["HourUTC"] = pd.to_datetime(df["HourUTC"], utc=True)
    return df.sort_values("HourUTC").reset_index(drop=True)


if __name__ == "__main__":
    from pathlib import Path

    START, END = "2019-01-01", "2026-07-08"
    out_dir = Path("new_data/price")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        d = fetch(START, END, area)
        assert d["SpotPriceEUR"].notna().any(), f"{area}: no price data"
        path = out_dir / f"price_{area.lower()}_{START}_{END}.parquet"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        neg = (d["SpotPriceEUR"] < 0).mean()
        print(
            f"✓ {area}: {len(d)} rows  {d['HourUTC'].min()} → {d['HourUTC'].max()}  neg-price={neg:.1%}  → {path}"
        )
