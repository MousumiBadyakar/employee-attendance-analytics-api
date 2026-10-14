"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from decimal import Decimal, ROUND_HALF_UP

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


@app.on_event("startup")
def create_indexes():
    # Unique employee code
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employees_emp_code",
    )

    # One attendance record per employee per date
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_date",
    )

    # Supports attendance date-range queries and sorting
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="idx_attendance_date_emp",
    )

    # Supports status-filtered attendance queries
    db.attendance_logs.create_index(
        [("status", 1), ("date", -1), ("emp_code", 1)],
        name="idx_attendance_status_date_emp",
    )

    # Supports department analytics and employee filtering
    db.employees.create_index(
        [("department", 1), ("joined_on", 1)],
        name="idx_employees_department_joined",
    )

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str, shift_end: str,) -> int:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)
    punch_in = punch_in.astimezone(IST).replace(microsecond=0)  

    h, m = map(int, shift_start.split(":"))
    end_h, end_m = map(int, shift_end.split(":"))

    start_minutes = h*60 + m
    end_minutes = end_h*60 + end_m
    punch_minutes = punch_in.hour*60 + punch_in.minute

    overnight = end_minutes <= start_minutes

    if overnight and punch_minutes < end_minutes:
        shift_date = punch_in.date() - timedelta(days=1)
    else:
        shift_date = punch_in.date()
    start = datetime(shift_date.year, shift_date.month, shift_date.day, h, m, tzinfo = IST,)

    elapsed_seconds = (punch_in - start).total_seconds()

    if elapsed_seconds > 10 * 60:
        return int(elapsed_seconds // 60)

    return 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    elapsed_seconds = (punch_out - punch_in).total_seconds()
    hours = Decimal(str(elapsed_seconds)) / Decimal("3600")
    rounded_hours = hours.quantize(
        Decimal("0.01"),
        rounding = ROUND_HALF_UP,
    )
    return float(rounded_hours)


def compute_overtime(punch_out: datetime, shift_start: str, shift_end: str, date_str: str) -> int:
    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)

    punch_out =  punch_out.astimezone(IST).replace(microsecond=0)

    start_h, start_m = map(int, shift_start.split(":"))
    end_h, end_m = map(int, shift_end.split(":"))

    start_minutes = start_h*60 + start_m
    end_minutes = end_h*60 + end_m

    overnight = end_minutes <= start_minutes

    shift_date = datetime.fromisoformat(date_str).date()

    if overnight:
        shift_date += timedelta(days=1)

    scheduled_end = datetime(shift_date.year, shift_date.month, shift_date.day, end_h, end_m, tzinfo=IST,)

    elapsed_seconds = (punch_out - scheduled_end).total_seconds()
    overtime_minutes = int(elapsed_seconds // 60)

    if overtime_minutes >= 30:
        return overtime_minutes

    return 0


def validate_date(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a valid date in YYYY-MM-DD format",
        )

    if parsed.strftime("%Y-%m-%d") != value:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use YYYY-MM-DD format",
        )

    return value


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(
        default="09:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    shift_end: str = Field(
        default="18:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: str) -> str:
        try:
            parsed_date = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                "joined_on must be a valid date in YYYY-MM-DD format"
            )

        if parsed_date.strftime("%Y-%m-%d") != value:
            raise ValueError(
                "joined_on must use YYYY-MM-DD format"
            )

        return value

    @model_validator(mode="after")
    def validate_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError(
                "shift_start and shift_end must differ"
            )
        return self



class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = Field(default = None, ge = 100_000_000_000, le = 4_102_444_800_000,)
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str = Field(
        min_length=7,
        max_length=9,
        pattern=r"^EMP\d{4,6}$",
    )
    punched_at: Optional[StrictInt] = Field(
        default=None,
        ge=100_000_000_000,
        le=4_102_444_800_000,
    )


class RegularizeRequest(BaseModel):
    status: Optional[
        Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]
    ] = None

    punch_in: Optional[StrictInt] = Field(
        default=None,
        ge=100_000_000_000,
        le=4_102_444_800_000,
    )

    punch_out: Optional[StrictInt] = Field(
        default=None,
        ge=100_000_000_000,
        le=4_102_444_800_000,
    )

    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )
    return {"status": "ok"}



@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    created_at = datetime.now(timezone.utc)
    doc["created_at"] = created_at

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists",
        )

    response = body.model_dump()
    response["created_at"] = int(created_at.timestamp() * 1000)

    return response



@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),):
    q = {}
    if department is not None:
        q["department"] = department
    
    total = db.employees.count_documents(q)

    skip = (page-1) * page_size

    cursor = (
        db.employees.find(q, {"_id":0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )
    items = list(cursor)
    for item in items:
        created_at = item.get("created_at")
        if created_at is not None:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            item["created_at"] = int(
                created_at.timestamp() * 1000
            )
    return {"items": items, "total": total, "page": page, "page_size": page_size}



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # Convert the timestamp to IST.
    if body.punched_at is not None:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc,
        ).astimezone(IST)
    else:
        ts = datetime.now(IST)

    # Remove fractional seconds before calculations.
    ts = ts.replace(microsecond=0)

    # Convert shift times into minutes since midnight.
    start_minutes = (
        int(emp["shift_start"][:2]) * 60
        + int(emp["shift_start"][3:])
    )
    end_minutes = (
        int(emp["shift_end"][:2]) * 60
        + int(emp["shift_end"][3:])
    )

    # Determine whether the shift crosses midnight.
    overnight = end_minutes <= start_minutes

    # Calculate the attendance date.
    attendance_date = ts.date()

    if overnight and (ts.hour * 60 + ts.minute) < end_minutes:
        attendance_date -= timedelta(days=1)

    d = attendance_date.isoformat()

    # Quick check for an existing attendance record.
    if db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "date": d}
    ):
        raise HTTPException(
            status_code=409,
            detail="already punched in for this date",
        )

    # Build the attendance document.
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts,
            emp["shift_start"],
            emp["shift_end"],
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    # The unique index handles simultaneous duplicate requests.
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="already punched in for this date",
        )

    # Never expose MongoDB's internal ID.
    doc.pop("_id", None)
    # Convert the punch-in instant to epoch milliseconds
    # for the API response. MongoDB storage stays unchanged.
    doc["punch_in"] = int(ts.astimezone(timezone.utc).timestamp() * 1000)

    return doc



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[Literal[
        "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
    ]] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    date_from = validate_date(date_from, "date_from")
    date_to = validate_date(date_to, "date_to")

    if date_from and date_to and date_from > date_to:
         raise HTTPException(
            status_code=422,
            detail="date_from must be on or before date_to",
        )
    q = {}

    if emp_code is not None:
        q["emp_code"] = emp_code

    if date_from is not None or date_to is not None:
        q["date"] = {}

        if date_from is not None:
            q["date"]["$gte"] = date_from

        if date_to is not None:
            q["date"]["$lte"] = date_to

    if status is not None:
        q["status"] = status

    # Count all records matching the filters.
    total = db.attendance_logs.count_documents(q)

    # Calculate how many records to skip.
    skip = (page - 1) * page_size

    # Let MongoDB sort and paginate the results.
    cursor = (
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    items = list(cursor)

    # Convert BSON datetimes to epoch milliseconds.
    for item in items:
        for field in ("punch_in", "punch_out"):
            value = item.get(field)

            if value is not None:
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)

                item[field] = int(value.timestamp() * 1000)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    # 1. Verify that the employee exists.
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    # 2. Get the punch-out instant in UTC and truncate to seconds.
    if body.punched_at is not None:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc,
        )
    else:
        ts = datetime.now(timezone.utc)

    ts = ts.replace(microsecond=0)

    # 3. Find the most recent punch-in at or before this instant.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$ne": None, "$lte": ts},
        },
        sort=[("punch_in", -1)],
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No punch-in found for this timestamp",
        )

    # 4. Reject an attendance record that is already closed.
    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Attendance record already punched out",
        )

    # PyMongo may return naive datetimes; interpret them as UTC.
    punch_in_time = record["punch_in"]
    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    # 5. Validate the time interval.
    elapsed = ts - punch_in_time

    if elapsed <= timedelta(0):
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in",
        )

    if elapsed > timedelta(hours=24):
        raise HTTPException(
            status_code=422,
            detail="Punch-out cannot be more than 24 hours after punch-in",
        )

    # 6. Calculate the derived fields.
    work_hours = compute_work_hours(punch_in_time, ts)

    overtime_minutes = compute_overtime(
        ts,
        emp["shift_start"],
        emp["shift_end"],
        record["date"],
    )

    half_day = work_hours < 4.50

    # 7. Atomically update only if the record is still open.
    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance record already punched out",
        )

    # 8. Return the API representation, not MongoDB's internal _id.
    return {
        "emp_code": record["emp_code"],
        "date": record["date"],
        "status": record["status"],
        "punch_in": int(punch_in_time.timestamp() * 1000),
        "punch_out": int(ts.timestamp() * 1000),
        "work_hours": work_hours,
        "late_minutes": record["late_minutes"],
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
        "history": record.get("history", []),
    }



@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeRequest,
):
    # 1. Validate the requested attendance date.
    date = validate_date(date, "date")

    # 2. Check that the employee exists.
    emp = db.employees.find_one({"emp_code": emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # 3. Find the employee's attendance record.
    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date,
    })

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    # Helper: interpret naive MongoDB datetimes as UTC.
    def as_utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    # Helper: convert a datetime to epoch milliseconds.
    def to_epoch_ms(value):
        value = as_utc(value)
        if value is None:
            return None
        return int(value.timestamp() * 1000)

    # 4. Identify fields explicitly supplied by the client.
    supplied_fields = body.model_fields_set

    correction_fields = supplied_fields & {
        "status",
        "punch_in",
        "punch_out",
    }

    if not correction_fields:
        raise HTTPException(
            status_code=422,
            detail="At least one correction field is required",
        )

    # 5. Preserve the old values for comparison and audit history.
    old_values = {
        "status": record.get("status"),
        "punch_in": as_utc(record.get("punch_in")),
        "punch_out": as_utc(record.get("punch_out")),
        "late_minutes": record.get("late_minutes", 0),
        "work_hours": record.get("work_hours"),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False),
    }

    # Build the proposed state without changing MongoDB yet.
    proposed = {
        "status": old_values["status"],
        "punch_in": old_values["punch_in"],
        "punch_out": old_values["punch_out"],
    }

    # 6. Apply only the fields supplied in the request.
    for field in correction_fields:
        value = getattr(body, field)

        if field in {"punch_in", "punch_out"}:
            if value is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} must be an epoch-millisecond integer",
                )

            value = datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc,
            )

        proposed[field] = value

    # Normalize only timestamps explicitly supplied for correction.
    # Unchanged timestamps must remain untouched.
    for field in correction_fields & {"punch_in", "punch_out"}:
        value = proposed[field]

        if value is not None:
            proposed[field] = value.replace(microsecond=0)
            
    # 7. Validate status and punch-time combinations.
    if proposed["status"] in {"ABSENT", "LEAVE"}:
        if correction_fields & {"punch_in", "punch_out"}:
            raise HTTPException(
                status_code=422,
                detail="Do not supply punch times when setting ABSENT or LEAVE",
            )

        proposed["punch_in"] = None
        proposed["punch_out"] = None

    elif proposed["punch_in"] is None:
        raise HTTPException(
            status_code=422,
            detail="Presence status requires a punch-in time",
        )

    # 8. Validate that punch-in belongs to the requested attendance date.
    if proposed["punch_in"] is not None:
        punch_in_ist = proposed["punch_in"].astimezone(IST)
        punch_time = punch_in_ist.time().replace(tzinfo=None)

        shift_start = datetime.strptime(
            emp["shift_start"], "%H:%M"
        ).time()

        shift_end = datetime.strptime(
            emp["shift_end"], "%H:%M"
        ).time()

        is_overnight = shift_end <= shift_start
        punch_date = punch_in_ist.date()

        if is_overnight and punch_time < shift_end:
            punch_date -= timedelta(days=1)

        if punch_date.isoformat() != date:
            raise HTTPException(
                status_code=422,
                detail="Punch-in does not belong to this attendance date",
            )

    # 9. Validate punch-out against punch-in.
    if proposed["punch_out"] is not None:
        if proposed["punch_in"] is None:
            raise HTTPException(
                status_code=422,
                detail="Punch-out requires a punch-in",
            )

        elapsed = proposed["punch_out"] - proposed["punch_in"]

        if elapsed.total_seconds() <= 0:
            raise HTTPException(
                status_code=422,
                detail="Punch-out must be after punch-in",
            )

        if elapsed > timedelta(hours=24):
            raise HTTPException(
                status_code=422,
                detail="Punch-out cannot be more than 24 hours after punch-in",
            )

    # 10. Recalculate derived attendance fields.
    if proposed["punch_in"] is not None:
        late_minutes = compute_late_minutes(
            proposed["punch_in"],
            emp["shift_start"],
            emp["shift_end"],
        )
    else:
        late_minutes = 0

    if (
        proposed["punch_in"] is not None
        and proposed["punch_out"] is not None
    ):
        work_hours = compute_work_hours(
            proposed["punch_in"],
            proposed["punch_out"],
        )

        overtime_minutes = compute_overtime(
            proposed["punch_out"],
            emp["shift_start"],
            emp["shift_end"],
            date,
        )

        half_day = work_hours < 4.50

    else:
        work_hours = None
        overtime_minutes = 0
        half_day = False

    new_values = {
        **proposed,
        "late_minutes": late_minutes,
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    # 11. Build changes containing only values that actually changed.
    changes = {}

    for field, new_value in new_values.items():
        old_value = old_values[field]

        if old_value != new_value:
            if field in {"punch_in", "punch_out"}:
                old_value = to_epoch_ms(old_value)
                new_value = to_epoch_ms(new_value)

            changes[field] = {
                "from": old_value,
                "to": new_value,
            }

    # A correction that changes nothing must be rejected.
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="The correction does not change any values",
        )

    # 12. Create exactly one audit-history entry.
    now = datetime.now(timezone.utc).replace(microsecond=0)

    history_entry = {
        "at": to_epoch_ms(now),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    # 13. Update atomically, protecting against concurrent corrections.
    # The old field values and history must still match what we read.
    compare_and_swap = {
        "_id": record["_id"],
        "status": record.get("status"),
        "punch_in": record.get("punch_in"),
        "punch_out": record.get("punch_out"),
    }

    history = record.get("history", [])

    if "history" in record:
        history_condition = {"history": history}
    else:
        history_condition = {"history": {"$exists": False}}

    result = db.attendance_logs.update_one(
        {
            "$and": [
                compare_and_swap,
                history_condition,
            ]
        },
        {
            "$set": {
                "status": new_values["status"],
                "punch_in": new_values["punch_in"],
                "punch_out": new_values["punch_out"],
                "late_minutes": new_values["late_minutes"],
                "work_hours": new_values["work_hours"],
                "overtime_minutes": new_values["overtime_minutes"],
                "half_day": new_values["half_day"],
            },
            "$push": {"history": history_entry},
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance record changed concurrently; retry the correction",
        )

    # 14. Return the corrected record without exposing MongoDB's _id.
    return {
        "emp_code": emp_code,
        "date": date,
        "status": new_values["status"],
        "punch_in": to_epoch_ms(new_values["punch_in"]),
        "punch_out": to_epoch_ms(new_values["punch_out"]),
        "work_hours": new_values["work_hours"],
        "late_minutes": new_values["late_minutes"],
        "overtime_minutes": new_values["overtime_minutes"],
        "half_day": new_values["half_day"],
        "history": history + [history_entry],
    }




@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    month: str,
):
    # 1. Validate the month format.
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    if parsed_month.strftime("%Y-%m") != month:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    # 2. Find the employee.
    emp = db.employees.find_one({"emp_code": emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # 3. Determine the calendar month boundaries.
    month_start = parsed_month.date().replace(day=1)

    if parsed_month.month == 12:
        next_month = parsed_month.replace(
            year=parsed_month.year + 1,
            month=1,
            day=1,
        ).date()
    else:
        next_month = parsed_month.replace(
            month=parsed_month.month + 1,
            day=1,
        ).date()

    month_end = next_month - timedelta(days=1)

    # 4. A mid-month joiner is eligible only from joined_on.
    joined_on = datetime.strptime(
        emp["joined_on"], "%Y-%m-%d"
    ).date()

    effective_start = max(month_start, joined_on)
    
    # An employee who joined after the requested month has no eligible days.
    if effective_start > month_end:
        return {
            "emp_code": emp_code,
            "month": month,
            "working_days": 0,
            "present_days": 0,
            "leave_days": 0,
            "late_count": 0,
            "attendance_pct": None,
        }


    # 5. Calculate eligible weekdays and aggregate attendance
    # in MongoDB, without looping over dates in Python.
    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": effective_start.isoformat(),
                    "$lte": month_end.isoformat(),
                },
            }
        },
        {
            "$set": {
                "_attendance_date": {
                    "$dateFromString": {
                        "dateString": "$date",
                        "format": "%Y-%m-%d",
                    }
                }
            }
        },
        {
            "$set": {
                "_weekday": {
                    "$dayOfWeek": "$_attendance_date"
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {"$gte": ["$_weekday", 2]},
                                    {"$lte": ["$_weekday", 6]},
                                ]
                            },
                            {
                                "$cond": [
                                    "$half_day",
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    if results:
        summary = results[0]
        present_days = summary["present_days"]
        leave_days = summary["leave_days"]
        late_count = summary["late_count"]
    else:
        present_days = 0
        leave_days = 0
        late_count = 0

    # 6. Calculate the number of eligible weekdays in MongoDB.
    # Generate one calendar date per day, then count Mon-Fri.
    working_days_pipeline = [
        {
            "$documents": [
                {
                    "start": datetime.combine(
                        effective_start,
                        datetime.min.time(),
                    ),
                    "end": datetime.combine(
                        month_end,
                        datetime.min.time(),
                    ),
                }
            ]
        },
        {
            "$project": {
                "dates": {
                    "$map": {
                        "input": {
                            "$range": [
                                0,
                                {
                                    "$add": [
                                        {
                                            "$dateDiff": {
                                                "startDate": "$start",
                                                "endDate": "$end",
                                                "unit": "day",
                                            }
                                        },
                                        1,
                                    ]
                                },
                            ]
                        },
                        "as": "offset",
                        "in": {
                            "$dateAdd": {
                                "startDate": "$start",
                                "unit": "day",
                                "amount": "$$offset",
                            }
                        },
                    }
                }
            }
        },
        {"$unwind": "$dates"},
        {
            "$match": {
                "$expr": {
                    "$and": [
                        {"$gte": [{"$dayOfWeek": "$dates"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$dates"}, 6]},
                    ]
                }
            }
        },
        {"$count": "working_days"},
    ]

    working_results = list(
        db.command({
            "aggregate": 1,
            "pipeline": working_days_pipeline,
            "cursor": {},
        })["cursor"]["firstBatch"]
    )

    working_days = (
        working_results[0]["working_days"]
        if working_results
        else 0
    )

    # 7. Calculate attendance percentage with half-up rounding.
    if working_days == 0:
        attendance_pct = None
    else:
        attendance_pct = float(
            (
                Decimal(str(present_days))
                / Decimal(working_days)
                * Decimal("100")
            ).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "attendance_pct": attendance_pct,
    }



@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: Optional[str] = None,
):
    # 1. Validate month format.
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    if parsed_month.strftime("%Y-%m") != month:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    # 2. Calculate the month's date boundaries.
    month_start = parsed_month.date().replace(day=1)

    if parsed_month.month == 12:
        next_month = parsed_month.replace(
            year=parsed_month.year + 1,
            month=1,
            day=1,
        ).date()
    else:
        next_month = parsed_month.replace(
            month=parsed_month.month + 1,
            day=1,
        ).date()

    month_end = next_month - timedelta(days=1)

    # 3. Start with employees who joined by month-end.
    employee_match = {
        "joined_on": {"$lte": month_end.isoformat()}
    }

    if department is not None:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},

        # 4. Fetch each employee's attendance for this month.
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$emp_code",
                                            "$$employee_code",
                                        ]
                                    },
                                    {
                                        "$gte": [
                                            "$date",
                                            month_start.isoformat(),
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            "$date",
                                            month_end.isoformat(),
                                        ]
                                    },
                                ]
                            }
                        }
                    },
                    {
                        "$set": {
                            "_weekday": {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date",
                                        "format": "%Y-%m-%d",
                                    }
                                }
                            }
                        }
                    },
                ],
                "as": "logs",
            }
        },

        # 5. Calculate attendance metrics for each employee.
        {
            "$project": {
                "department": 1,
                "emp_code": 1,
                "headcount": {"$literal": 1},

                "present_days": {
                    "$sum": {
                        "$map": {
                            "input": "$logs",
                            "as": "log",
                            "in": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {
                                                "$in": [
                                                    "$$log.status",
                                                    [
                                                        "PRESENT",
                                                        "WFH",
                                                        "ON_DUTY",
                                                    ],
                                                ]
                                            },
                                            {
                                                "$gte": [
                                                    "$$log._weekday", 2
                                                ]
                                            },
                                            {
                                                "$lte": [
                                                    "$$log._weekday", 6
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        "$cond": [
                                            {
                                                "$eq": [
                                                    "$$log.half_day",
                                                    True,
                                                ]
                                            },
                                            0.5,
                                            1,
                                        ]
                                    },
                                    0,
                                ]
                            },
                        }
                    }
                },

                "work_hours_values": {
                    "$map": {
                        "input": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$$log.status",
                                                [
                                                    "PRESENT",
                                                    "WFH",
                                                    "ON_DUTY",
                                                ],
                                            ]
                                        },
                                        {
                                            "$ne": [
                                                "$$log.work_hours",
                                                None,
                                            ]
                                        },
                                    ]
                                },
                            }
                        },
                        "as": "log",
                        "in": "$$log.work_hours",
                    }
                },

                "late_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {
                                "$gt": [
                                    {"$ifNull": [
                                        "$$log.late_minutes", 0
                                    ]},
                                    0,
                                ]
                            },
                        }
                    }
                },

                "total_late_minutes": {
                    "$sum": {
                        "$map": {
                            "input": "$logs",
                            "as": "log",
                            "in": {
                                "$cond": [
                                    {
                                        "$gt": [
                                            {"$ifNull": [
                                                "$$log.late_minutes", 0
                                            ]},
                                            0,
                                        ]
                                    },
                                    "$$log.late_minutes",
                                    0,
                                ]
                            },
                        }
                    }
                },

                "leave_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {
                                "$eq": ["$$log.status", "LEAVE"]
                            },
                        }
                    }
                },

                "on_duty_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {
                                "$eq": ["$$log.status", "ON_DUTY"]
                            },
                        }
                    }
                },
            }
        },

        # 6. Combine employee metrics by department.
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": "$headcount"},
                "present_days": {"$sum": "$present_days"},
                "all_work_hours": {
                    "$push": "$work_hours_values"
                },
                "late_count": {"$sum": "$late_count"},
                "total_late_minutes": {
                    "$sum": "$total_late_minutes"
                },
                "leave_count": {"$sum": "$leave_count"},
                "on_duty_count": {"$sum": "$on_duty_count"},
            }
        },

        # 7. Flatten the work-hour arrays.
        {
            "$set": {
                "all_work_hours": {
                    "$reduce": {
                        "input": "$all_work_hours",
                        "initialValue": [],
                        "in": {
                            "$concatArrays": [
                                "$$value",
                                "$$this",
                            ]
                        },
                    }
                }
            }
        },

        # 8. Calculate the average over individual records.
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "avg_work_hours": {
                    "$cond": [
                        {"$gt": [
                            {"$size": "$all_work_hours"}, 0
                        ]},
                        {"$avg": "$all_work_hours"},
                        None,
                    ]
                },
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },

        {"$sort": {"department": 1}},
    ]

    results = list(db.employees.aggregate(pipeline))

    # 9. Apply half-up rounding to average work hours.
    for item in results:
        average = item["avg_work_hours"]

        if average is not None:
            item["avg_work_hours"] = float(
                Decimal(str(average)).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            )

    return {
        "month": month,
        "items": results,
    }




@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = Query(default=10, ge=1, le=50),
    department: Optional[str] = None,
):
    # 1. Validate the month.
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    if parsed_month.strftime("%Y-%m") != month:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    # 2. Calculate the month boundaries.
    month_start = parsed_month.date().replace(day=1)

    if parsed_month.month == 12:
        next_month = parsed_month.replace(
            year=parsed_month.year + 1,
            month=1,
            day=1,
        ).date()
    else:
        next_month = parsed_month.replace(
            month=parsed_month.month + 1,
            day=1,
        ).date()

    month_end = next_month - timedelta(days=1)

    # 3. Aggregate attendance by employee.
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lte": month_end.isoformat(),
                },
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {
            "$match": {
                "total_late_minutes": {"$gt": 0}
            }
        },

        # 4. Attach employee information.
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    # Filter by department before ranking.
    if department is not None:
        pipeline.append({
            "$match": {
                "employee.department": department
            }
        })

    # 5. Rank by total late minutes.
    # Equal totals receive equal ranks.
    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1
                },
                "output": {
                    "rank": {"$rank": {}}
                },
            }
        },

        # Include all employees tied at the cutoff rank.
        {
            "$match": {
                "rank": {"$lte": limit}
            }
        },

        # Stable output order for tied employees.
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1,
            }
        },

        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items,
    }





@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    start_date: str,
    end_date: str
):
    # Validate date format and values
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if start.isoformat() != start_date or end.isoformat() != end_date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD format"
        )

    if start > end:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date"
        )

    # Include six preceding calendar days for the moving average
    calculation_start = start - timedelta(days=6)

    # Canonical UTC-midnight labels for calendar dates
    calculation_start_utc = datetime.combine(
        calculation_start, datetime.min.time(), tzinfo=timezone.utc
    )
    start_day_utc = datetime.combine(
        start, datetime.min.time(), tzinfo=timezone.utc
    )
    end_day_utc = datetime.combine(
        end, datetime.min.time(), tzinfo=timezone.utc
    )

    pipeline = [
        # Seed the extended calculation range
        {
            "$documents": [
                {
                    "date": calculation_start_utc,
                    "present_days": 0,
                    "late_count": 0
                }
            ]
        },
        {
            "$unionWith": {
                "coll": "attendance_logs",
                "pipeline": [
                    # MongoDB stores attendance date as YYYY-MM-DD string
                    {
                        "$match": {
                            "date": {
                                "$gte": calculation_start.isoformat(),
                                "$lte": end.isoformat()
                            }
                        }
                    },
                    # Keep records belonging to the requested department
                    {
                        "$lookup": {
                            "from": "employees",
                            "let": {"employee_code": "$emp_code"},
                            "pipeline": [
                                {
                                    "$match": {
                                        "$expr": {
                                            "$eq": [
                                                "$emp_code",
                                                "$$employee_code"
                                            ]
                                        },
                                        "department": department
                                    }
                                },
                                {
                                    "$project": {
                                        "_id": 0,
                                        "emp_code": 1
                                    }
                                }
                            ],
                            "as": "employee"
                        }
                    },
                    {"$unwind": "$employee"},
                    # Convert the calendar-date string into a date label
                    {
                        "$addFields": {
                            "day": {
                                "$dateFromString": {
                                    "dateString": "$date",
                                    "format": "%Y-%m-%d",
                                    "timezone": "UTC"
                                }
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": "$day",
                            "present_days": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        ["PRESENT", "WFH", "ON_DUTY"]
                                                    ]
                                                },
                                                {
                                                    "$in": [
                                                        {
                                                            "$dayOfWeek": {
                                                                "date": "$day",
                                                                "timezone": "UTC"
                                                            }
                                                        },
                                                        [2, 3, 4, 5, 6]
                                                    ]
                                                }
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$eq": ["$half_day", True]},
                                                0.5,
                                                1
                                            ]
                                        },
                                        0
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {"$ifNull": ["$late_minutes", 0]},
                                                0
                                            ]
                                        },
                                        1,
                                        0
                                    ]
                                }
                            }
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "date": "$_id",
                            "present_days": 1,
                            "late_count": 1
                        }
                    }
                ]
            }
        },
        # Combine seed and attendance aggregates by calendar date
        {
            "$group": {
                "_id": "$date",
                "present_days": {"$sum": "$present_days"},
                "late_count": {"$sum": "$late_count"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "present_days": 1,
                "late_count": 1
            }
        },
        # Densify from six days before the requested start date
        {
            "$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [
                        calculation_start_utc,
                        end_day_utc + timedelta(days=1)
                    ]
                }
            }
        },
        {
            "$set": {
                "present_days": {"$ifNull": ["$present_days", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]}
            }
        },
        # Calculate moving average using current day + six preceding days
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_present_days": {
                        "$avg": "$present_days",
                        "window": {"documents": [-6, 0]}
                    }
                }
            }
        },
        # Return only the originally requested date range
        {
            "$match": {
                "date": {
                    "$gte": start_day_utc,
                    "$lte": end_day_utc
                }
            }
        },
        {"$sort": {"date": 1}}
    ]

    try:
        results = list(db.aggregate(pipeline))
    except Exception as exc:
        print(f"Department trend aggregation failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Unable to calculate department attendance trend"
        )

    items = []

    for row in results:
        items.append({
            "date": row["date"].date().isoformat(),
            "present_days": float(
                Decimal(str(row.get("present_days", 0))).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )
            ),
            "late_count": int(row.get("late_count", 0)),
            "moving_avg_present_days": float(
                Decimal(str(row.get("moving_avg_present_days", 0))).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )
            )
        })

    return {
        "department": department,
        "start_date": start_date,
        "end_date": end_date,
        "items": items
    }





@app.get("/admin/explain/{endpoint}")
def explain_query(
    endpoint: Literal[
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    ],
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None
):
    # Validate month when supplied
    if month is not None:
        try:
            parsed_month = datetime.strptime(month, "%Y-%m")
            if parsed_month.strftime("%Y-%m") != month:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format"
            )
    # Build the query to explain
    if endpoint == "attendance_list":
        match = {}
        if emp_code:
            match["emp_code"] = emp_code
        if status:
            match["status"] = status
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            match["date"] = date_filter
        target_collection = db.attendance_logs
        pipeline = [
            {"$match": match},
            {"$sort": {"date": -1, "emp_code": 1}}
        ]
    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required"
            )
        target_collection = db.attendance_logs
        parsed_month = datetime.strptime(month, "%Y-%m")
        month_start = parsed_month.date().replace(day=1)
        if parsed_month.month == 12:
            next_month = parsed_month.replace(
                year=parsed_month.year + 1,
                month=1,
                day=1,
            ).date()
        else:
            next_month = parsed_month.replace(
                month=parsed_month.month + 1,
                day=1,
            ).date()
        month_end = next_month - timedelta(days=1)
        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": month_start.isoformat(),
                        "$lte": month_end.isoformat(),
                    }
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "records": {"$sum": 1},
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {
                                            "$in": [
                                                {"$dayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$date",
                                                        "format": "%Y-%m-%d",
                                                        "timezone": "UTC"
                                                    }
                                                  }
                                                },
                                                [2,3,4,5,6]
                                            ]
                                        }
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    }
                }
            }
        ]
    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required",
            )
        parsed_month = datetime.strptime(month, "%Y-%m")
        if parsed_month.strftime("%Y-%m") != month:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )
        month_start = parsed_month.date().replace(day=1)
        if parsed_month.month == 12:
            next_month = parsed_month.replace(
                year=parsed_month.year + 1,
                month=1,
                day=1,
            ).date()
        else:
            next_month = parsed_month.replace(
                month=parsed_month.month + 1,
                day=1,
            ).date()
        month_end = next_month - timedelta(days=1)

        employee_match = {"joined_on": {"$lte": month_end.isoformat()}}
        if department:
            employee_match["department"] = department

        target_collection = db.employees
        pipeline = [
            {"$match": employee_match},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"employee_code": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$emp_code", "$$employee_code"]},
                                        {"$gte": ["$date", month_start.isoformat()]},
                                        {"$lte": ["$date", month_end.isoformat()]},
                                    ]
                                }
                            }
                        },
                        {
                            "$set": {
                                "_weekday": {
                                    "$dayOfWeek": {
                                        "$dateFromString": {
                                            "dateString": "$date",
                                            "format": "%Y-%m-%d",
                                        }
                                    }
                                }
                            }
                        },
                    ],
                    "as": "logs",
                }
            },
            {
                "$project": {
                    "department": 1,
                    "emp_code": 1,
                    "headcount": {"$literal": 1},
                    "present_days": {
                        "$sum": {
                            "$map": {
                                "input": "$logs",
                                "as": "log",
                                "in": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$$log.status",
                                                        ["PRESENT", "WFH", "ON_DUTY"],
                                                    ]
                                                },
                                                {"$gte": ["$$log._weekday", 2]},
                                                {"$lte": ["$$log._weekday", 6]},
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$eq": ["$$log.half_day", True]},
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                },
                            }
                        }
                    },
                    "work_hours_values": {
                        "$map": {
                            "input": {
                                "$filter": {
                                    "input": "$logs",
                                    "as": "log",
                                    "cond": {
                                        "$and": [
                                            {
                                                "$in": [
                                                    "$$log.status",
                                                    ["PRESENT", "WFH", "ON_DUTY"],
                                                ]
                                            },
                                            {"$ne": ["$$log.work_hours", None]},
                                        ]
                                    },
                                }
                            },
                            "as": "log",
                            "in": "$$log.work_hours",
                        }
                    },
                    "late_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {
                                    "$gt": [
                                        {"$ifNull": ["$$log.late_minutes", 0]},
                                        0,
                                    ]
                                },
                            }
                        }
                    },
                    "total_late_minutes": {
                        "$sum": {
                            "$map": {
                                "input": "$logs",
                                "as": "log",
                                "in": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {"$ifNull": ["$$log.late_minutes", 0]},
                                                0,
                                            ]
                                        },
                                        "$$log.late_minutes",
                                        0,
                                    ]
                                },
                            }
                        }
                    },
                    "leave_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {"$eq": ["$$log.status", "LEAVE"]},
                            }
                        }
                    },
                    "on_duty_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {"$eq": ["$$log.status", "ON_DUTY"]},
                            }
                        }
                    },
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$sum": "$headcount"},
                    "present_days": {"$sum": "$present_days"},
                    "all_work_hours": {"$push": "$work_hours_values"},
                    "late_count": {"$sum": "$late_count"},
                    "total_late_minutes": {"$sum": "$total_late_minutes"},
                    "leave_count": {"$sum": "$leave_count"},
                    "on_duty_count": {"$sum": "$on_duty_count"},
                }
            },
            {
                "$set": {
                    "all_work_hours": {
                        "$reduce": {
                            "input": "$all_work_hours",
                            "initialValue": [],
                            "in": {"$concatArrays": ["$$value", "$$this"]},
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": 1,
                    "present_days": 1,
                    "avg_work_hours": {
                        "$cond": [
                            {"$gt": [{"$size": "$all_work_hours"}, 0]},
                            {"$avg": "$all_work_hours"},
                            None,
                        ]
                    },
                    "late_count": 1,
                    "total_late_minutes": 1,
                    "leave_count": 1,
                    "on_duty_count": 1,
                }
            },
            {"$sort": {"department": 1}},
        ]

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )
        target_collection = db.attendance_logs
        parsed_month = datetime.strptime(month, "%Y-%m")
        if parsed_month.strftime("%Y-%m") != month:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )
        month_start = parsed_month.date().replace(day=1)
        if parsed_month.month == 12:
            next_month = parsed_month.replace(
                year=parsed_month.year + 1,
                month=1,
                day=1,
            ).date()
        else:
            next_month = parsed_month.replace(
                month=parsed_month.month + 1,
                day=1,
            ).date()
        month_end = next_month - timedelta(days=1)
        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": month_start.isoformat(),
                        "$lte": month_end.isoformat(),
                    },
                    "late_minutes": {"$gt": 0}
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "late_count": {"$sum": 1}
                }
            },
            {
                "$setWindowFields": {
                    "sortBy": {"total_late_minutes": -1},
                    "output": {
                        "rank": {"$rank": {}}
                    }
                }
            },
            {"$sort": {"rank": 1, "_id": 1}}
        ]
    else:  # department_trend
        if not start_date or not end_date or not department:
            raise HTTPException(
                status_code=422,
                detail="department, start_date and end_date are required"
            )
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            if start.isoformat() != start_date or end.isoformat() != end_date:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Dates must use YYYY-MM-DD format"
            )
        if start > end:
            raise HTTPException(
                status_code=422,
                detail="start_date must be on or before end_date"
            )
        calculation_start = start - timedelta(days=6)
        calculation_start_utc = datetime.combine(
            calculation_start, datetime.min.time(), tzinfo=timezone.utc
        )
        start_day_utc = datetime.combine(
            start, datetime.min.time(), tzinfo=timezone.utc
        )
        end_day_utc = datetime.combine(
            end, datetime.min.time(), tzinfo=timezone.utc
        )
        # Match the department trend calculation, including its moving window.
        target_collection = db
        pipeline = [
            {
                "$documents": [{
                    "date": calculation_start_utc,
                    "present_days": 0,
                    "late_count": 0
                }]
            },
            {
                "$unionWith": {
                    "coll": "attendance_logs",
                    "pipeline": [
                        {
                            "$match": {
                                "date": {
                                    "$gte": calculation_start.isoformat(),
                                    "$lte": end.isoformat()
                                }
                            }
                        },
                        {
                            "$lookup": {
                                "from": "employees",
                                "let": {"employee_code": "$emp_code"},
                                "pipeline": [
                                    {
                                        "$match": {
                                            "$expr": {
                                                "$eq": [
                                                    "$emp_code",
                                                    "$$employee_code"
                                                ]
                                            },
                                            "department": department
                                        }
                                    },
                                    {
                                        "$project": {
                                            "_id": 0,
                                            "emp_code": 1
                                        }
                                    }
                                ],
                                "as": "employee"
                            }
                        },
                        {"$unwind": "$employee"},
                        {
                            "$addFields": {
                                "day": {
                                    "$dateFromString": {
                                        "dateString": "$date",
                                        "format": "%Y-%m-%d",
                                        "timezone": "UTC"
                                    }
                                }
                            }
                        },
                        {
                            "$group": {
                                "_id": "$day",
                                "present_days": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"]
                                                        ]
                                                    },
                                                    {
                                                        "$in": [
                                                            {
                                                                "$dayOfWeek": {
                                                                    "date": "$day",
                                                                    "timezone": "UTC"
                                                                }
                                                            },
                                                            [2, 3, 4, 5, 6]
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                "$cond": [
                                                    {"$eq": ["$half_day", True]},
                                                    0.5,
                                                    1
                                                ]
                                            },
                                            0
                                        ]
                                    }
                                },
                                "late_count": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$gt": [
                                                    {"$ifNull": ["$late_minutes", 0]},
                                                    0
                                                ]
                                            },
                                            1,
                                            0
                                        ]
                                    }
                                }
                            }
                        },
                        {
                            "$project": {
                                "_id": 0,
                                "date": "$_id",
                                "present_days": 1,
                                "late_count": 1
                            }
                        }
                    ]
                }
            },
            {
                "$group": {
                    "_id": "$date",
                    "present_days": {"$sum": "$present_days"},
                    "late_count": {"$sum": "$late_count"}
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": "$_id",
                    "present_days": 1,
                    "late_count": 1
                }
            },
            {
                "$densify": {
                    "field": "date",
                    "range": {
                        "step": 1,
                        "unit": "day",
                        "bounds": [
                            calculation_start_utc,
                            end_day_utc + timedelta(days=1)
                        ]
                    }
                }
            },
            {
                "$set": {
                    "present_days": {"$ifNull": ["$present_days", 0]},
                    "late_count": {"$ifNull": ["$late_count", 0]}
                }
            },
            {
                "$setWindowFields": {
                    "sortBy": {"date": 1},
                    "output": {
                        "moving_avg_present_days": {
                            "$avg": "$present_days",
                            "window": {"documents": [-6, 0]}
                        }
                    }
                }
            },
            {
                "$match": {
                    "date": {
                        "$gte": start_day_utc,
                        "$lte": end_day_utc
                    }
                }
            },
            {"$sort": {"date": 1}}
        ]
    try:
        if endpoint == "department_trend":
            explanation = db.command({
                "explain": {
                    "aggregate":1,
                    "pipeline": pipeline,
                    "cursor": {}
                },
                "verbosity": "executionStats"
            })
        else:
            explanation = db.command({
                "explain": {
                    "aggregate": target_collection.name,
                    "pipeline": pipeline,
                    "cursor": {}
                },
                "verbosity": "executionStats"
            })
    except Exception as exc:
        print(f"Explain failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Unable to explain query"
        )
    return explanation
