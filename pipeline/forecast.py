"""An ordinary least-squares trend with calendar-aware dates, no ML service."""

import math
from datetime import UTC, date, datetime

from mock_crm.data import month_start
from pipeline.storage import Database


def month_label(as_of: date, offset: int = 0) -> str:
    return month_start(datetime(as_of.year, as_of.month, 1, tzinfo=UTC), offset).strftime("%Y-%m")


def trend_forecast(monthly: list[dict], as_of: date | None = None) -> dict:
    as_of = as_of or datetime.now(UTC).date()
    current, oldest = month_label(as_of), month_label(as_of, -12)
    observed = {}
    for row in monthly:
        month = row["month"]
        date.fromisoformat(month + "-01")
        amount = float(row["won_revenue"])
        if not math.isfinite(amount) or amount < 0 or row.get("currency", "USD") != "USD":
            raise ValueError("Forecast requires finite nonnegative USD revenue")
        if month in observed:
            raise ValueError("Duplicate revenue month")
        observed[month] = amount
    history = {m: v for m, v in observed.items() if oldest <= m < current}
    if not history:
        raise ValueError("No complete monthly history in the last 12 months")
    labels = [
        month_label(as_of, offset)
        for offset in range(-12, 0)
        if month_label(as_of, offset) >= min(history)
    ]
    values = [history.get(month, 0.0) for month in labels]
    n = len(values)
    center_x, center_y = (n - 1) / 2, sum(values) / n
    denominator = sum((x - center_x) ** 2 for x in range(n))
    slope = (
        sum((x - center_x) * (y - center_y) for x, y in enumerate(values)) / denominator
        if n >= 3
        else 0.0
    )
    intercept = center_y - slope * center_x
    rmse = math.sqrt(sum((y - (intercept + slope * x)) ** 2 for x, y in enumerate(values)) / n)
    points = []
    for offset in (1, 2, 3):
        # Last complete month is n-1; current month is n; next month is n+1.
        amount = max(0.0, intercept + slope * (n + offset))
        points.append(
            {
                "month": month_label(as_of, offset),
                "won_revenue": round(amount, 2),
                "low": round(max(0.0, amount - 2 * rmse), 2),
                "high": round(amount + 2 * rmse, 2),
            }
        )
    return {
        "method": "linear trend" if n >= 3 else "mean fallback",
        "currency": "USD",
        "training_months": n,
        "history": [{"month": m, "won_revenue": v} for m, v in zip(labels, values, strict=True)],
        "residual_rmse": round(rmse, 2),
        "forecast": points,
        "assumptions": "Complete calendar months only; missing months mean zero; no seasonality. "
        "Bands are +/-2 residual RMSE, not calibrated intervals.",
    }


def forecast_from_models(db: Database, as_of: date | None = None) -> dict:
    return trend_forecast(db.rows("SELECT * FROM model_monthly_revenue ORDER BY month"), as_of)


def answer_pipeline_question(db: Database, as_of: date | None = None) -> str:
    """Answer the single supported question using fixed model queries and explicit assumptions."""
    as_of = as_of or datetime.now(UTC).date()
    latest = db.rows("SELECT run_id FROM sync_runs ORDER BY started_at DESC LIMIT 1")
    quality = (
        db.rows("SELECT passed FROM quality_results WHERE run_id=?", (latest[0]["run_id"],))
        if latest
        else []
    )
    if len(quality) != 5 or not all(row["passed"] for row in quality):
        return (
            "Forecast withheld: the latest run has failed or incomplete data quality checks. "
            "Review the run report before using the warehouse."
        )
    forecast = forecast_from_models(db, as_of)
    point = forecast["forecast"][0]
    scheduled = db.rows(
        "SELECT pipeline_amount, open_deals FROM model_monthly_revenue WHERE month=?",
        (point["month"],),
    )
    pipeline = float(scheduled[0]["pipeline_amount"]) if scheduled else 0
    overdue = db.rows(
        "SELECT COUNT(*) AS n FROM stg_deals WHERE stage NOT IN ('won','lost') AND close_date < ?",
        (as_of.isoformat(),),
    )[0]["n"]
    risk = (
        "no open pipeline is scheduled for that month"
        if pipeline == 0
        else "scheduled pipeline may slip or lose"
    )
    return (
        f"For {point['month']}, the history-based won revenue estimate "
        f"is USD {point['won_revenue']:,.2f}. "
        f"Open pipeline scheduled that month is USD {pipeline:,.2f}; "
        f"{overdue} open deals are overdue as of {as_of}. "
        f"Risk: the illustrative range is USD {point['low']:,.2f} to {point['high']:,.2f}, "
        f"and {risk}. "
        f"Assumptions: {forecast['training_months']} synthetic complete months, "
        f"{forecast['method']}, zero-filled gaps and no seasonality. "
        "This is a historical estimate, not a commitment from individual deals."
    )
