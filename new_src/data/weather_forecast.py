import requests
import pandas as pd

# Leak-free weather: historical-forecast-api archives the MODEL FORECAST (not ERA5
# reanalysis), so a row for July 1 holds what was forecast for July 1 — not the
# actual observed value. Using the plain archive-api (ERA5) here would leak.
URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# ponytail: lead time not pinned to the day-ahead 12:00 gate; it's the freshest
# short-lead forecast. Fine for a first stack. Upgrade to a pinned model-run
# (Open-Meteo previous-runs / model-runs API) if backtest scores look optimistic.

VARS = [
    "wind_speed_100m",
    "wind_gusts_10m",
    "wind_direction_100m",  # wind output drivers
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "cloud_cover",  # solar drivers
    "temperature_2m",  # load + panel efficiency
]

# DK1 = Jutland/Funen, DK2 = Zealand. One representative point per zone.
COORDS = {"DK1": (56.0, 9.0), "DK2": (55.7, 12.3)}


def fetch(start: str, end: str, area: str) -> pd.DataFrame:
    lat, lon = COORDS[area]
    r = requests.get(
        URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "hourly": ",".join(VARS),
            "timezone": "UTC",
        },
        timeout=120,
    )
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame(h)
    df["hour_utc"] = pd.to_datetime(df.pop("time"), utc=True)
    df.insert(1, "area", area)
    return df.sort_values("hour_utc").reset_index(drop=True)


if __name__ == "__main__":
    from pathlib import Path

    # historical-forecast-api goes back to ~2018 (empty by 2016); 2019 aligns with residual.
    START, END = "2019-01-01", "2026-07-08"
    out_dir = Path("new_data/weather")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in COORDS:
        d = fetch(START, END, area)
        assert d["hour_utc"].is_monotonic_increasing
        assert d["temperature_2m"].notna().any(), (
            f"{area}: all-null, source unavailable"
        )
        path = out_dir / f"weather_{area.lower()}_{START}_{END}.parquet"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        cov = d["temperature_2m"].notna().mean()
        print(
            f"✓ {area}: {len(d)} rows  {d['hour_utc'].min()} → {d['hour_utc'].max()}  coverage={cov:.1%}  → {path}"
        )
