import numpy as np
import pandas as pd
import holidays as holidays_lib
from pathlib import Path

# Tier-1 deterministic features: calendar + DK holidays + daylight. All derivable
# from timestamp + latitude, known arbitrarily far ahead → zero leak.
# NOTE: demand follows LOCAL time, so hour/weekday/holiday use Europe/Copenhagen
# local date, not UTC.

COORDS = {"DK1": (56.0, 9.0), "DK2": (55.7, 12.3)}  # latitude used for daylight


def _daylight(dates: pd.Series, lat_deg: float) -> pd.DataFrame:
    """Daylight hours + sunrise/sunset (local solar time) per calendar date."""
    doy = dates.dt.dayofyear.to_numpy()
    lat = np.radians(lat_deg)
    # solar declination (radians), standard approximation
    decl = 0.409 * np.sin(2 * np.pi / 365 * doy - 1.39)
    # hour angle at sunrise; clamp for safety (Denmark never polar, but be safe)
    cos_h = np.clip(-np.tan(lat) * np.tan(decl), -1, 1)
    h = np.arccos(cos_h)  # radians
    daylight_hours = 24 / np.pi * h
    # ponytail: solar noon ~12:00 local; ignores equation-of-time & longitude
    # offset (~<30min). Fine for a feature; add EoT correction if it ever matters.
    sunrise = 12 - daylight_hours / 2
    sunset = 12 + daylight_hours / 2
    return pd.DataFrame(
        {
            "daylight_hours": daylight_hours,
            "sunrise_hour": sunrise,
            "sunset_hour": sunset,
        }
    )


def build(start: str, end: str, area: str) -> pd.DataFrame:
    lat, _ = COORDS[area]
    ts = pd.date_range(start=start, end=end, freq="h", tz="UTC")
    local = ts.tz_convert("Europe/Copenhagen")
    local_date = pd.to_datetime(local.date)  # naive local calendar date
    local_hour = local.hour

    years = range(local.year.min(), local.year.max() + 1)
    dk = holidays_lib.Denmark(years=years, language="da")
    hol_map = {pd.Timestamp(k): v for k, v in dk.items()}

    df = pd.DataFrame({"timestamp_utc": ts.tz_convert("UTC"), "area": area})
    df["hour"] = local_hour
    df["dow"] = local.dayofweek  # 0=Mon
    df["month"] = local.month
    df["doy"] = local.dayofyear
    df["is_weekend"] = df["dow"].isin([5, 6])
    df["is_holiday"] = local_date.isin(hol_map)
    df["holiday_name"] = local_date.map(hol_map)

    # cyclical encodings (so 23h and 0h are neighbours)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["doy_sin"] = np.sin(2 * np.pi * df["doy"] / 365)
    df["doy_cos"] = np.cos(2 * np.pi * df["doy"] / 365)
    df["dow_sin"] = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dow"] / 7)

    dl = _daylight(pd.Series(local_date), lat)
    df["daylight_hours"] = dl["daylight_hours"].to_numpy()
    df["sunrise_hour"] = dl["sunrise_hour"].to_numpy()
    df["sunset_hour"] = dl["sunset_hour"].to_numpy()
    df["is_daylight"] = (local_hour >= df["sunrise_hour"]) & (
        local_hour < df["sunset_hour"]
    )
    return df


if __name__ == "__main__":
    START, END = "2019-01-01", "2026-07-08"
    out_dir = Path("new_data/calendar")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in COORDS:
        d = build(START, END, area)
        # sanity: summer day longer than winter day
        jun = d[d["month"] == 6]["daylight_hours"].mean()
        dec = d[d["month"] == 12]["daylight_hours"].mean()
        assert jun > dec + 5, "daylight seasonality wrong"
        path = out_dir / f"calendar_{area.lower()}_{START}_{END}.parquet"
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        print(
            f"✓ {area}: {len(d)} rows  daylight Jun={jun:.1f}h Dec={dec:.1f}h  "
            f"holidays={d['is_holiday'].sum() // 24} days  → {path}"
        )
