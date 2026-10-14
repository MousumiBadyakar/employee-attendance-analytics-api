# DECISIONS.md

### 1. Indexes

I created a unique index on `employees.emp_code` to prevent duplicate employee codes and a unique compound index on `attendance_logs.emp_code` and `date` to guarantee one attendance record per employee per day. The `(date, emp_code)` index supports date-based queries and sorting, while `(status, date, emp_code)` supports status-filtered attendance listing. The `(department, joined_on)` index supports department filtering and joining-date queries. I considered a standalone index on `late_minutes`, but avoided adding it because leaderboard queries also filter by month. I would verify this choice using execution statistics on production-sized data.

### 2. Punch-in race

When identical punch-in requests arrive simultaneously, both may attempt to insert a record. MongoDB's unique compound index allows only one insertion for the same employee and date. The successful request returns `201 Created`, while the duplicate-key error is converted into `409 Conflict`.

### 3. Ties

The leaderboard uses competition ranking. Employees with equal late-minute totals share a rank, and the next rank is skipped. The limit is applied after ranking, so all employees whose rank is at most the requested limit are returned, including ties at the cutoff.

### 4. Headcount

The department summary starts from employees and looks up attendance records. This ensures employees who joined by the period end are counted even if they have no attendance logs.

### 5. Scaling

For 100 times the data, I would benchmark queries with representative data, review index efficiency, monitor slow aggregation pipelines, and consider archiving older attendance records.