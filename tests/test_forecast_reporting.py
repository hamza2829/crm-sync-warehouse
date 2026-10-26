from datetime import date

import pytest

from pipeline.forecast import answer_pipeline_question, month_label, trend_forecast
from pipeline.reporting import generate_report
from pipeline.sync import sync
from quality.checks import QualityError, run_checks


def rows(values, months=None):
    months = months or [f"2026-{i:02d}" for i in range(1, len(values) + 1)]
    return [
        {"month": month, "won_revenue": value} for month, value in zip(months, values, strict=True)
    ]


def test_linear_trend_forecasts_actual_next_calendar_months():
    result = trend_forecast(rows([10, 20, 30]), date(2026, 4, 15))
    assert [r["month"] for r in result["forecast"]] == ["2026-05", "2026-06", "2026-07"]
    assert [r["won_revenue"] for r in result["forecast"]] == [50, 60, 70]
    assert result["residual_rmse"] == 0


def test_forecast_excludes_current_incomplete_month():
    result = trend_forecast(rows([10, 20, 30, 9999]), date(2026, 4, 15))
    assert result["forecast"][0]["won_revenue"] == 50


def test_forecast_fills_calendar_gaps():
    result = trend_forecast(rows([10, 30], ["2026-01", "2026-03"]), date(2026, 4, 1))
    assert [r["won_revenue"] for r in result["history"]] == [10, 0, 30]


def test_forecast_mean_fallback_with_short_history():
    result = trend_forecast(rows([10, 20]), date(2026, 3, 1))
    assert result["method"] == "mean fallback"
    assert result["forecast"][0]["won_revenue"] == 15


def test_forecast_clips_negative_prediction():
    assert trend_forecast(rows([30, 20, 10]), date(2026, 4, 1))["forecast"][0]["won_revenue"] == 0


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")], [-1]])
def test_forecast_rejects_invalid_history(values):
    with pytest.raises(ValueError):
        trend_forecast(rows(values), date(2026, 4, 1))


def test_forecast_duplicate_month_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        trend_forecast(rows([10, 20], ["2026-01", "2026-01"]), date(2026, 4, 1))


def test_year_rollover():
    assert month_label(date(2026, 12, 31), 1) == "2027-01"


def test_dashboard_is_offline_and_answer_states_assumptions(db, crm, tmp_path):
    run_id = sync(db, crm)
    db.run_models()
    report = tmp_path / "report.md"
    run_checks(db, run_id, report_path=report)
    dashboard = generate_report(db, run_id, tmp_path, report)
    document = dashboard.read_text(encoding="utf-8")
    assert "plotly.js" in document
    assert '<script src="http' not in document
    assert "Data quality:" in document and "Quarantine" in document
    answer = answer_pipeline_question(db)
    assert "USD" in answer and "Assumptions:" in answer and "overdue" in answer
    assert "Forecast USD" in report.read_text()


def test_bad_quality_withholds_forecast_but_generates_report(db, crm, tmp_path):
    run_id = sync(db, crm, drift=True)
    db.run_models()
    report = tmp_path / "report.md"
    with pytest.raises(QualityError):
        run_checks(db, run_id, report_path=report)
    path = generate_report(db, run_id, tmp_path, report)
    assert "Withheld" in path.read_text(encoding="utf-8")
    assert "Forecast withheld" in answer_pipeline_question(db)


def test_answer_requires_completed_quality_checks(db, crm):
    sync(db, crm)
    db.run_models()
    assert "incomplete" in answer_pipeline_question(db)
