import requests
import pandas as pd

URL = "https://api.energidataservice.dk/dataset/ProductionConsumptionSettlement"


def fetch(start="2021-01-01", end="2026-07-01", area="DK1") -> pd.DataFrame:
    """Load + wind + solar + residual demand (= load - wind - solar), hourly."""
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

    num = lambda cols: cols.apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
    out = pd.DataFrame(
        {
            "hour_utc": pd.to_datetime(df["HourUTC"], utc=True),
            "area": area,
            "load_mwh": pd.to_numeric(df["GrossConsumptionMWh"], errors="coerce"),
            "wind_mwh": num(df.filter(like="Wind")),
            "solar_mwh": num(df.filter(like="Solar")),
        }
    )
    # ponytail: residual = load - wind - solar; ignores must-run CHP/hydro, good enough for a first stack
    out["residual_mwh"] = out["load_mwh"] - out["wind_mwh"] - out["solar_mwh"]
    return out.sort_values("hour_utc").reset_index(drop=True)


if __name__ == "__main__":
    from pathlib import Path

    START, END = "2019-01-01", "2026-07-08"
    out_dir = Path("new_data")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        d = fetch(START, END, area)
        assert (
            d["residual_mwh"] == d["load_mwh"] - d["wind_mwh"] - d["solar_mwh"]
        ).all()
        path = out_dir / f"residual_{area.lower()}_{START}_{END}.parquet"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        print(
            f"✓ {area}: {len(d)} rows  {d['hour_utc'].min()} → {d['hour_utc'].max()}  → {path}"
        )
