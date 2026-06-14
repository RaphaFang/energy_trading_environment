import pandas as pd
import numpy as np
import duckdb
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score
import plotly.graph_objects as go
from sklearn.preprocessing import MinMaxScaler

# ── Load ──────────────────────────────────────────────────────────────────────
con = duckdb.connect()
df = con.execute("""
    SELECT
        p.hour_utc::TIMESTAMP        AS hour_utc, 
        p.avg_price_eur              AS price_eur,
        w.wind_speed_100m,
        w.shortwave_radiation,
        w.temperature_2m,
        COALESCE(h.is_holiday, false)::INT AS is_holiday
    FROM read_parquet('data/cleaned/price_dk1_hourly_2026-03-16_2026-06-16.parquet') p
    JOIN read_parquet('data/cleaned/weather_dk1_2026-03-16_2026-06-16.parquet')      w
        ON DATE_TRUNC('hour', w.timestamp_utc::TIMESTAMP) = DATE_TRUNC('hour', p.hour_utc::TIMESTAMP)
    LEFT JOIN read_parquet('data/holi/holiday.parquet') h
        ON DATE_TRUNC('day', p.hour_utc::TIMESTAMP) = DATE_TRUNC('day', h.date::TIMESTAMP)
    ORDER BY p.hour_utc
""").df()
con.close()

# ── wind and solar features ──────────────────────────────────────────────────────────────

mms = MinMaxScaler()
wind_solar = mms.fit_transform(df[["wind_speed_100m", "shortwave_radiation"]])

df["wind_cubed"] = wind_solar[:, 0] ** 3
df["solar_sq"]   = wind_solar[:, 1] ** 2

# ── Lag features ──────────────────────────────────────────────────────────────
df = df.sort_values("hour_utc").reset_index(drop=True)
df["price_lag24h"]  = df["price_eur"].shift(24)
df["price_lag168h"] = df["price_eur"].shift(168)
df = df.dropna().reset_index(drop=True)

FEATURES = [
    "wind_cubed",
    "solar_sq",
    "temperature_2m",
    "is_holiday",
    "price_lag24h",
    "price_lag168h",

    "wind_speed_100m",
    "shortwave_radiation"
]

# ── Split ─────────────────────────────────────────────────────────────────────
cutoff = pd.Timestamp("2026-06-08")
train  = df[df["hour_utc"] <= cutoff]
pred   = df[df["hour_utc"] >  cutoff].copy()

# ── Train ─────────────────────────────────────────────────────────────────────
pipe = Pipeline([
    ("scaler", StandardScaler()),
    ("ridge",  RidgeCV(alphas=np.logspace(-2, 3, 50))),
])
pipe.fit(train[FEATURES], train["price_eur"])
best_alpha = pipe.named_steps["ridge"].alpha_
print(f"\nBest alpha: {best_alpha:.4f}")

# ── Predict ───────────────────────────────────────────────────────────────────
pred["predicted"] = pipe.predict(pred[FEATURES])

resid_std        = (train["price_eur"] - pipe.predict(train[FEATURES])).std()
pred["ci_upper"] = pred["predicted"] + 1.96 * resid_std
pred["ci_lower"] = pred["predicted"] - 1.96 * resid_std

# ── Metrics ───────────────────────────────────────────────────────────────────
has_actual = pred["price_eur"].notna()
mae, r2 = None, None
if has_actual.any():
    mae = mean_absolute_error(pred.loc[has_actual, "price_eur"], pred.loc[has_actual, "predicted"])
    r2  = r2_score(pred.loc[has_actual, "price_eur"], pred.loc[has_actual, "predicted"])
    print(f"MAE: {mae:.2f} EUR/MWh   R²: {r2:.3f}")

# ── Coefficients ──────────────────────────────────────────────────────────────
coefs = dict(zip(FEATURES, pipe.named_steps["ridge"].coef_ / pipe.named_steps["scaler"].scale_))
print("\nCoefficients:")
for k, v in coefs.items():
    print(f"  {k:25s} {v:+.4f}")

# ── Plot ──────────────────────────────────────────────────────────────────────
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=pd.concat([pred["hour_utc"], pred["hour_utc"].iloc[::-1]]),
    y=pd.concat([pred["ci_upper"], pred["ci_lower"].iloc[::-1]]),
    fill="toself", fillcolor="rgba(99,110,250,0.15)",
    line=dict(color="rgba(0,0,0,0)"),
    name="95% CI", hoverinfo="skip",
))

fig.add_trace(go.Scatter(
    x=pred["hour_utc"], y=pred["predicted"],
    mode="lines", line=dict(color="#636EFA", width=2),
    name="Predicted",
))

fig.add_trace(go.Scatter(
    x=pred["hour_utc"], y=pred["price_eur"],
    mode="lines+markers", line=dict(color="#EF553B", width=1.5, dash="dot"),
    marker=dict(size=4),
    name="Actual",
))

holidays = pred[pred["is_holiday"] == 1]
if not holidays.empty:
    fig.add_trace(go.Scatter(
        x=holidays["hour_utc"], y=holidays["predicted"],
        mode="markers", marker=dict(symbol="star", size=9, color="#FFD700"),
        name="Holiday",
    ))

title = f"DK1 Day-Ahead Price Forecast  Jun 9–15  |  α={best_alpha:.3f}"
if mae is not None:
    title += f"  MAE={mae:.1f}  R²={r2:.3f}"

fig.update_layout(
    title=title,
    xaxis_title="Hour (UTC)",
    yaxis_title="EUR / MWh",
    height=500,
    plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
    font=dict(color="#e0e0e0"),
    legend=dict(orientation="h", y=1.02),
    yaxis=dict(gridcolor="#2a2a3a"),
    xaxis=dict(gridcolor="#2a2a3a"),
)

fig.show()



# ================================================
# without Polynomial
# ================================================
# Best alpha: 11.5140
# MAE: 24.98 EUR/MWh   R²: 0.649

# Coefficients:
#   temperature_2m            +0.5173
#   is_holiday                -18.5268
#   price_lag24h              +0.3971
#   price_lag168h             +0.1755
#   wind_speed_100m           -1.3604
#   shortwave_radiation       -0.0712


# ================================================
# with Polynomial
# ================================================
# Best alpha: 37.2759
# MAE: 26.56 EUR/MWh   R²: 0.613

# Coefficients:
#   wind_cubed                -173.7406
#   solar_sq                  -77.6995
#   temperature_2m            +0.2111
#   is_holiday                -19.1283
#   price_lag24h              +0.3835
#   price_lag168h             +0.1581

# ================================================
# with Polynomial & the original 
# ================================================
# Best alpha: 37.2759
# MAE: 24.68 EUR/MWh   R²: 0.647

# Coefficients:
#   wind_cubed                -69.6207
#   solar_sq                  -56.6607
#   temperature_2m            +0.4171
#   is_holiday                -18.5038
#   price_lag24h              +0.3753
#   price_lag168h             +0.1698
#   wind_speed_100m           -0.9343
#   shortwave_radiation       -0.0246