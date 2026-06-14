import requests
from pathlib import Path
import pandas as pd

LAT, LON = 56.0, 9.0
ZONE = "DK1"
VARS = "wind_speed_100m,shortwave_radiation,temperature_2m"
START = "2026-03-16"
END = "2026-06-16"
TODAY = pd.Timestamp.utcnow().normalize().tz_localize(None)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _to_df(hourly: dict) -> pd.DataFrame:
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def fetch_archive(start: str, end: str) -> pd.DataFrame:
    r = requests.get(ARCHIVE_URL, params={
        "latitude": LAT, "longitude": LON,
        "start_date": start, "end_date": end,
        "hourly": VARS, "timezone": "UTC",
    }, timeout=90)
    r.raise_for_status()
    return _to_df(r.json()["hourly"])


def fetch_forecast() -> pd.DataFrame:
    r = requests.get(FORECAST_URL, params={
        "latitude": LAT, "longitude": LON,
        "hourly": VARS, "past_days": 7, "forecast_days": 5,
        "timezone": "UTC",
    }, timeout=90)
    r.raise_for_status()
    return _to_df(r.json()["hourly"])


def main():
    ARCHIVE_END = "2026-06-13"
    FORECAST_START_AFTER = pd.Timestamp("2026-06-13T23:00:00", tz="UTC")
    FORECAST_END = pd.Timestamp("2026-06-16T00:00:00", tz="UTC")

    arch = fetch_archive(START, ARCHIVE_END)

    fc = fetch_forecast()
    fc = fc[(fc["time"] > FORECAST_START_AFTER) & (fc["time"] <= FORECAST_END)]

    df = pd.concat([arch, fc], ignore_index=True).drop_duplicates("time").sort_values("time")
    df = df.rename(columns={"time": "timestamp_utc"})
    df["zone_code"] = ZONE

    out = Path("data/cleaned") / f"weather_{ZONE.lower()}_{START}_{END}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, engine="pyarrow", compression="snappy")


if __name__ == "__main__":
    main()