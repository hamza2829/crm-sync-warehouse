"""A self-contained offline Plotly dashboard and a matching Markdown run report."""

import html
from datetime import UTC, datetime
from pathlib import Path

import plotly.graph_objects as go

from pipeline.forecast import answer_pipeline_question, forecast_from_models
from pipeline.storage import Database
from quality.checks import quality_markdown


def generate_report(
    db: Database,
    run_id: str,
    output_dir: str | Path = "artifacts",
    report_path: str | Path = "docs/last_run_report.md",
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    funnel = db.rows("SELECT * FROM model_funnel ORDER BY stage_order")
    monthly = db.rows("SELECT * FROM model_monthly_revenue ORDER BY month")
    checks = db.rows("SELECT * FROM quality_results WHERE run_id=? ORDER BY check_name", (run_id,))
    quarantine = db.rows(
        "SELECT resource, record_id, reason FROM quarantine WHERE run_id=? ORDER BY resource, record_id LIMIT 10",
        (run_id,),
    )
    run = db.rows("SELECT * FROM sync_runs WHERE run_id=?", (run_id,))[0]
    passed = len(checks) == 5 and all(row["passed"] for row in checks)
    projection = forecast_from_models(db) if passed else None
    answer = answer_pipeline_question(db)
    chart = go.Figure(
        go.Bar(
            x=[r["stage"] for r in funnel],
            y=[r["reached_deals"] for r in funnel],
            marker_color=["#4263eb", "#748ffc", "#a5b4fc", "#12b886", "#fa5252"],
            text=[r["reached_deals"] for r in funnel],
            textposition="outside",
        )
    )
    chart.update_layout(title="Funnel snapshot", yaxis_title="Deals (assumed progression)")
    revenue = go.Figure()
    for key, label, color in (
        ("pipeline_amount", "Open pipeline", "#91a7ff"),
        ("won_revenue", "Won revenue", "#12b886"),
    ):
        revenue.add_bar(
            x=[r["month"] for r in monthly],
            y=[float(r[key]) for r in monthly],
            name=label,
            marker_color=color,
        )
    if projection:
        points = projection["forecast"]
        revenue.add_scatter(
            x=[r["month"] for r in points],
            y=[r["high"] for r in points],
            mode="lines",
            line_width=0,
            showlegend=False,
            name="Band high",
        )
        revenue.add_scatter(
            x=[r["month"] for r in points],
            y=[r["low"] for r in points],
            fill="tonexty",
            fillcolor="rgba(66,99,235,.12)",
            line_width=0,
            name="Illustrative residual band",
        )
        revenue.add_scatter(
            x=[r["month"] for r in points],
            y=[r["won_revenue"] for r in points],
            mode="lines+markers",
            line={"dash": "dash", "color": "#4263eb"},
            name="Trend forecast",
        )
    revenue.update_layout(
        title="Monthly close-date amounts and next 3 calendar months",
        yaxis_title="USD",
        barmode="group",
    )
    for figure in (chart, revenue):
        figure.update_layout(
            template="plotly_white",
            font_family="Arial",
            height=360,
            margin={"t": 60, "b": 60, "l": 60, "r": 25},
            paper_bgcolor="rgba(0,0,0,0)",
            legend_orientation="h",
        )
    chart_html = chart.to_html(
        full_html=False, include_plotlyjs=True, config={"displayModeBar": False}
    )
    revenue_html = revenue.to_html(
        full_html=False, include_plotlyjs=False, config={"displayModeBar": False}
    )
    quality_rows = "".join(
        f"<tr><td>{html.escape(row['check_name'])}</td><td class={'ok' if row['passed'] else 'bad'}>{'PASS' if row['passed'] else 'FAIL'}</td><td>{html.escape(row['expectation'])}</td></tr>"
        for row in checks
    )
    rejected_rows = "".join(
        f"<tr><td>{html.escape(row['resource'])} #{html.escape(row['record_id'])}</td><td>{html.escape(row['reason'])}</td></tr>"
        for row in quarantine
    )
    won = sum(float(r["won_revenue"]) for r in monthly)
    forecast_label = (
        f"${projection['forecast'][0]['won_revenue']:,.0f}" if projection else "Withheld"
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CRM warehouse | Run report</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5fa;color:#17213b;font:15px/1.6 Arial,sans-serif}}
main{{max-width:1200px;margin:auto;padding:36px 24px}}h1{{font-size:36px;letter-spacing:-1px;margin:8px 0}}
h2{{font-size:20px;margin-top:0}}p{{margin:8px 0}}.eyebrow{{color:#4263eb;letter-spacing:2px;font-size:12px;font-weight:bold}}
.muted{{color:#5e6b85}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}}
.card,section{{background:white;border:1px solid #e3e7ef;border-radius:14px;padding:22px;margin-bottom:18px}}
.card{{margin:0}}.value{{font-size:30px;font-weight:bold}}.ok{{color:#087f5b}}.bad{{color:#c92a2a}}
.answer{{border-left:4px solid #4263eb}}table{{width:100%;border-collapse:collapse;text-align:left}}
td,th{{border-bottom:1px solid #edf0f5;padding:10px 6px;vertical-align:top}}.scroll{{overflow:auto}}
@media(max-width:700px){{.grid{{grid-template-columns:repeat(2,1fr)}}main{{padding:20px 12px}}h1{{font-size:28px}}}}
</style></head><body><main>
<div class="eyebrow">SYNTHETIC CRM / WAREHOUSE</div><h1>From CRM records to a clearer pipeline</h1>
<p class="muted">Offline run report. Mock data, USD amounts, no real CRM connection.</p>
<div class="grid">
<div class="card"><div class="muted">Warehouse deals</div><div class="value">{run["row_count"]:,}</div></div>
<div class="card"><div class="muted">Won revenue, observed months</div><div class="value">${won:,.0f}</div></div>
<div class="card"><div class="muted">Next month estimate</div><div class="value">{forecast_label}</div></div>
<div class="card"><div class="muted">Quarantined this run</div><div class="value">{run["quarantined"]}</div></div>
</div><section class="answer"><h2>What is expected to close next month, and what is the risk?</h2><p>{html.escape(answer)}</p></section>
<section>{chart_html}<p class="muted">Snapshot conversion assumes sequential progression. Lost is a separate terminal outcome. These are not cohort conversion rates.</p></section>
<section>{revenue_html}<p class="muted">Linear trend of up to 12 complete months; calendar gaps count as zero. The current incomplete month is excluded. Shading is +/-2 residual RMSE, not a calibrated confidence interval.</p></section>
<section><h2>Data quality: <span class="{"ok" if passed else "bad"}">{"PASS" if passed else "FAIL / INCOMPLETE"}</span></h2>
<div class="scroll"><table><tr><th>Check</th><th>Status</th><th>Expectation</th></tr>{quality_rows}</table></div></section>
<section><h2>Quarantine</h2><p>{run["quarantined"]} rejected records in this run. Showing at most 10.</p>
<div class="scroll"><table><tr><th>Record</th><th>Reason</th></tr>{rejected_rows}</table></div></section>
<p class="muted">Run {html.escape(run_id)} | Generated {datetime.now(UTC).isoformat()} | Synthetic demonstration, not production.</p>
</main></body></html>"""
    target = output / "dashboard.html"
    # Apply the project's typography rule to bundled chart-library text as well.
    target.write_text(document.replace(chr(0x2014), "-"), encoding="utf-8")
    text = quality_markdown(db, run_id) + "\n## Expected next month and risk\n\n" + answer + "\n"
    if projection:
        text += "\n| Month | Forecast USD | Illustrative low | Illustrative high |\n| --- | --- | --- | --- |\n"
        for point in projection["forecast"]:
            text += f"| {point['month']} | {point['won_revenue']:,.2f} | {point['low']:,.2f} | {point['high']:,.2f} |\n"
        text += "\n" + projection["assumptions"] + "\n"
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8")
    return target
