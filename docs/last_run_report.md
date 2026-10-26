# Last run report

Run: `be473c6a-9ffd-412e-b2c4-cee32f38cb9f`
Started (UTC): 2026-10-26T11:35:18.564609+00:00
Records seen: 625; loaded: 625; quarantined: 0.

Synthetic data from a mock CRM. All money is USD.

| Check | Status | Observed | Expectation |
| --- | --- | --- | --- |
| freshness | PASS | 4.921694444444445e-05 | newest source update within 48 hours |
| quarantine_rate | PASS | 0 | each resource below 5% rejected in this run |
| row_count | PASS | {"current": 500, "previous": null} | positive and within 20% of previous run |
| unique_ids | PASS | 0 | 0 duplicate ids across raw tables |
| won_amounts | PASS | 0 | 0 won deals with NULL amount |

Drift report:

```json
{
  "companies": {
    "rejected": 0,
    "seen": 25,
    "unknown_fields": []
  },
  "contacts": {
    "rejected": 0,
    "seen": 100,
    "unknown_fields": []
  },
  "deals": {
    "rejected": 0,
    "seen": 500,
    "unknown_fields": []
  }
}
```

## Expected next month and risk

For 2026-11, the history-based won revenue estimate is USD 128,001.98. Open pipeline scheduled that month is USD 0.00; 299 open deals are overdue as of 2026-10-26. Risk: the illustrative range is USD 72,623.75 to 183,380.21, and no open pipeline is scheduled for that month. Assumptions: 12 synthetic complete months, linear trend, zero-filled gaps and no seasonality. This is a historical estimate, not a commitment from individual deals.

| Month | Forecast USD | Illustrative low | Illustrative high |
| --- | --- | --- | --- |
| 2026-11 | 128,001.98 | 72,623.75 | 183,380.21 |
| 2026-12 | 127,160.02 | 71,781.79 | 182,538.25 |
| 2027-01 | 126,318.07 | 70,939.84 | 181,696.29 |

Complete calendar months only; missing months mean zero; no seasonality. Bands are +/-2 residual RMSE, not calibrated intervals.
