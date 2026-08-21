import requests
import pandas as pd

# Energinet official day-ahead / intraday production forecasts (Solar, Onshore
# Wind, Offshore Wind). ForecastDayAhead is leak-free for day-ahead price; the
# shorter-lead columns leak. We keep ALL columns raw and pick features later.
URL = "https://api.energidataservice.dk/dataset/Forecasts_Hour"


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
    return df.sort_values(["HourUTC", "ForecastType"]).reset_index(drop=True)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from window import END, START, paths_for, retire_superseded
    out_dir = Path("new_data/forecast")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        d = fetch(START, END, area)
        assert d["ForecastDayAhead"].notna().any(), f"{area}: no day-ahead data"
        path, _old = paths_for(out_dir, f"forecast_{area.lower()}")
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        retire_superseded(path, _old, "HourUTC")
        types = sorted(d["ForecastType"].unique())
        print(
            f"✓ {area}: {len(d)} rows  {d['HourUTC'].min()} → {d['HourUTC'].max()}  types={types}  → {path}"
        )
