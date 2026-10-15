# Employee Attendance & Analytics API

A RESTful backend built with **FastAPI** and **MongoDB** for employee management, attendance tracking, attendance regularization, and workforce analytics.

## Features

- **Employee Management:** Create and list employees with department filtering and pagination.
- **Attendance Tracking:** Punch-in, punch-out, and retrieve attendance records.
- **Attendance Regularization:** Correct attendance records with validation and an append-only audit history.
- **Attendance Analytics:** Employee monthly reports, department summaries, late-arrival leaderboard, and daily department trends.
- **Concurrency Safety:** Protect against duplicate attendance records and conflicting simultaneous updates.
- **Database Performance:** Compound indexes and query execution statistics through the explain endpoint.
- **Input Validation:** Structured request validation and appropriate HTTP error responses.

## Tech Stack

- **Language:** Python
- **Framework:** FastAPI
- **Database:** MongoDB
- **Validation:** Pydantic
- **API Documentation:** Swagger UI and ReDoc
- **Testing:** HTTPX and concurrent request testing

## Prerequisites

- Python 3.12+
- MongoDB 6.0+
- Git

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/MousumiBadyakar/employee-attendance-analytics-api.git
cd employee-attendance-analytics-api
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Set the following environment variables in your terminal, or create a `.env` file if the application is configured to load one:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

For PowerShell, you can set them for the current session with:

```powershell
$env:MONGO_URI="mongodb://localhost:27017"
$env:MONGO_DB="attendance_db"
```

Use your own MongoDB connection URI if your database is hosted remotely. Never commit credentials or secrets.

### 5. Start the API

From the project root, run:

```bash
uvicorn app.main:app --reload
```

Ensure MongoDB is running and the configured connection URI is accessible.

The API will be available at:

- **Base URL:** http://127.0.0.1:8000
- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

## Documentation

Use Swagger UI to explore endpoints, inspect request and response schemas, and test API operations.

- `REVIEW.md` — Review findings, identified issues, and verification notes.
- `DECISIONS.md` — Key technical decisions and their rationale.
- `DATA_MODEL.md` — Data model and database design.
- `openapi.yaml` — API specification.

## Notes

- Calendar dates and shift times follow the assignment's Asia/Kolkata timezone rules.
- A unique employee-and-date constraint prevents duplicate attendance records.
- Database indexes are initialized by the application.
- API timestamps are represented as Unix epoch milliseconds.
