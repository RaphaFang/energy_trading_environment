from pathlib import Path
import holidays
import pandas as pd

output_path = Path("/Users/fangsiyu/Desktop/energy/data/holi/holiday.parquet")

dk_holidays = holidays.Denmark(years=2026, language="da")
pd_holidays = {pd.to_datetime(k): v for k, v in dk_holidays.items()}

date_range = pd.date_range(start="2026-03-16", end="2026-06-16", freq="D")
dk_holidays_df = pd.DataFrame({"date": date_range})

is_nat_holiday = dk_holidays_df["date"].isin(pd_holidays)
is_weekend = dk_holidays_df["date"].dt.dayofweek.isin([5, 6])

dk_holidays_df["is_holiday"] = is_nat_holiday | is_weekend
dk_holidays_df["holiday_name"] = dk_holidays_df["date"].map(pd_holidays)



output_path.parent.mkdir(parents=True, exist_ok=True)
dk_holidays_df.to_parquet(output_path, index=False, engine="pyarrow", compression="snappy")