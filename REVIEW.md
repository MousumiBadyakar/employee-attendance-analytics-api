# REVIEW.md

## Defects Found and Fixed

| # | Where (function / line) | What is wrong | How detected (test, input, or symptom) | How fixed |
|---|---|---|---|---|
| 1 | `compute_late_minutes` | Late calculation must apply the 10-minute grace period while counting whole minutes from shift start. | Tested punches around the grace-period boundary. | Applied the strict `> 10 minutes` condition and floor-minute calculation. |
| 2 | `compute_late_minutes` | Overnight shifts require the correct shift-start date for early-morning punches. | Tested overnight shifts and early-morning punch-ins. | Added overnight shift-date handling. |
| 3 | Attendance indexes | Duplicate employee/date attendance records could be created during simultaneous requests without a database constraint. | Sent concurrent punch-in requests for the same employee and date. | Added a unique compound index on `emp_code` and `date`; handled duplicate-key conflicts. |
| 4 | `POST /attendance/punch-in` | Simultaneous punch-ins must not create multiple records. | Ten concurrent requests produced one `201` and nine `409` responses. | Relied on the unique index and handled duplicate-key errors as conflicts. |
| 5 | `POST /attendance/punch-out` | Simultaneous punch-outs must not overwrite an already completed punch-out. | Ten concurrent requests produced one `200` and nine `409` responses. | Used a conditional update so only one request can complete the punch-out. |
| 6 | `compute_work_hours` and punch-out logic | Work hours must use elapsed seconds and half-up rounding; overtime requires at least 30 whole minutes after shift end. | Tested work-hour calculations and the 30-minute overtime threshold. | Used elapsed-time calculations and the required rounding and overtime rules. |
| 7 | Attendance regularization (`PATCH`) | Corrections must validate inputs, recompute derived fields, and reject no-op changes. | Tested invalid status, missing reason, invalid punch-out, and a no-op correction. | Added validation, recomputation, and explicit rejection of unchanged values. |
| 8 | Attendance regularization (`PATCH`) | Concurrent corrections must not silently lose audit-history entries. | Sent two concurrent corrections to the same record. | Used a conditional update and returned `409` when the record changed concurrently. |
| 9 | Attendance regularization history | The audit trail must record only fields that actually changed. | Inspected the history after a successful status correction. | Appended a history entry containing the actor, reason, timestamp, and actual field changes. |
| 10 | Employee monthly analytics | Monthly calculations must respect weekdays, half-days, and the employee's joining date. | Tested a mid-month joiner and a month before the joining date. | Used aggregation calculations and handled periods before joining with zero metrics and a null attendance percentage. |
| 11 | Department summary | Headcount must include employees who joined by month-end even if they have no attendance records. | Checked department summaries against employee counts and attendance data. | Aggregated from employees and looked up attendance records. |
| 12 | Late leaderboard | Equal totals must share a competition rank, and the limit must be applied after ranking. | Tested employees with tied late-minute totals. | Used database ranking and retained every employee whose rank is at most the requested limit. |
| 13 | Department trend | The response must include dates with no attendance and calculate the moving average over a seven-day window. | Requested a range containing dates with no records. | Used MongoDB gap filling and a window calculation instead of generating daily rows in Python. |
| 14 | `GET /attendance` | Attendance listing needs filtering, stable sorting, pagination, and index support. | Tested employee filtering and checked the query plan. | Added the required query filters, sorting, pagination, and supporting indexes. |
| 15 | `GET /admin/explain/{endpoint}` | Explain output must use execution statistics for the requested query or aggregation. | Tested all five supported explain endpoint types. | Added explain handling for the supported query types and returned MongoDB execution statistics. |
| 16 | Application startup | Required indexes must exist after startup without manual setup. | Inspected the indexes created by the running application. | Added index creation to the startup routine. |

## Items Reviewed and Considered Correct

- Employee creation rejects duplicate employee codes and returns the expected conflict response.
- Employee listing supports department filtering and pagination.
- API timestamps use epoch milliseconds, while stored instants use MongoDB datetime values.
- Attendance dates and shift calculations use the IST time zone.
- Invalid month values and invalid request data return `422` responses.
- Unknown employees return `404` for employee monthly analytics.
- The tested attendance and analytics endpoints returned the expected response structures.
- The tested concurrency scenarios returned conflict responses rather than server errors.
