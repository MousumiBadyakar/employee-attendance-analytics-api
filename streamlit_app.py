
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# --------------------------------------------------
# Configuration
# --------------------------------------------------

API_BASE_URL = "https://employee-attendance-analytics-api-6iom.onrender.com"

IST = timezone(timedelta(hours=5, minutes=30))

st.set_page_config(
    page_title="Employee Attendance Analytics",
    page_icon="📊",
    layout="wide"
)

# --------------------------------------------------
# API Helpers
# --------------------------------------------------

def api_get(endpoint, params=None):
    try:
        response = requests.get(
            f"{API_BASE_URL}{endpoint}",
            params=params,
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        st.error(f"API Error: {e}")
        return None


def api_post(endpoint, payload):
    try:
        response = requests.post(
            f"{API_BASE_URL}{endpoint}",
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        st.error(f"API Error: {e}")
        return None


def format_timestamp(value):
    if value is None:
        return "—"

    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc
    ).astimezone(IST).strftime("%d %b %Y, %I:%M %p")


# --------------------------------------------------
# Sidebar
# --------------------------------------------------

st.sidebar.title("🏢 Attendance System")
st.sidebar.caption("Employee Management & Analytics")

page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Employees",
        "Attendance",
        "Analytics",
        "Regularization"
    ]
)

st.sidebar.divider()
st.sidebar.caption("Powered by FastAPI + MongoDB")


# --------------------------------------------------
# Dashboard
# --------------------------------------------------

if page == "Dashboard":

    st.title("📊 Employee Attendance Dashboard")
    st.caption("Overview of employee attendance and workforce activity")

    health = api_get("/health")

    if health:
        st.success("Backend API Connected")
    else:
        st.error("Backend API unavailable")

    employees = api_get(
        "/employees",
        params={"page": 1, "page_size": 1}
    )

    attendance = api_get(
        "/attendance",
        params={"page": 1, "page_size": 1}
    )

    if employees and attendance:

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Total Employees",
            employees["total"]
        )

        col2.metric(
            "Attendance Records",
            attendance["total"]
        )

        col3.metric(
            "API Status",
            "Online" if health else "Offline"
        )

        st.divider()

        st.subheader("Recent Attendance Records")

        records = api_get(
            "/attendance",
            params={"page": 1, "page_size": 10}
        )

        if records and records["items"]:

            df = pd.DataFrame(records["items"])

            for field in ["punch_in", "punch_out"]:
                df[field] = df[field].apply(format_timestamp)

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No attendance records found.")


# --------------------------------------------------
# Employees
# --------------------------------------------------

elif page == "Employees":

    st.title("👥 Employee Management")

    tab1, tab2 = st.tabs(["Employee Directory", "Add Employee"])

    with tab1:

        department = st.text_input("Filter by Department")

        params = {"page": 1, "page_size": 100}

        if department:
            params["department"] = department

        data = api_get("/employees", params=params)

        if data:
            st.metric("Total Employees", data["total"])

            if data["items"]:
                st.dataframe(
                    pd.DataFrame(data["items"]),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No employees found.")

    with tab2:

        with st.form("add_employee_form"):

            emp_code = st.text_input("Employee Code (EMP0001)")
            name = st.text_input("Full Name")
            email = st.text_input("Email")
            dept = st.text_input("Department")

            col1, col2 = st.columns(2)

            with col1:
                shift_start = st.time_input(
                    "Shift Start",
                    value=datetime.strptime("09:30", "%H:%M").time()
                )

            with col2:
                shift_end = st.time_input(
                    "Shift End",
                    value=datetime.strptime("18:30", "%H:%M").time()
                )

            joined_on = st.date_input("Joining Date")

            submitted = st.form_submit_button(
                "Create Employee",
                use_container_width=True
            )

            if submitted:

                payload = {
                    "emp_code": emp_code.strip(),
                    "name": name.strip(),
                    "email": email.strip(),
                    "department": dept.strip(),
                    "shift_start": shift_start.strftime("%H:%M"),
                    "shift_end": shift_end.strftime("%H:%M"),
                    "joined_on": joined_on.isoformat()
                }

                result = api_post("/employees", payload)

                if result:
                    st.success("Employee created successfully!")
                    st.json(result)


# --------------------------------------------------
# Attendance
# --------------------------------------------------

elif page == "Attendance":

    st.title("📅 Attendance Management")

    tab1, tab2 = st.tabs(["Attendance Records", "Punch In / Out"])

    with tab1:

        emp_code = st.text_input("Filter by Employee Code")

        col1, col2 = st.columns(2)

        with col1:
            date_from = st.date_input(
                "From Date",
                value=None
            )

        with col2:
            date_to = st.date_input(
                "To Date",
                value=None
            )

        params = {"page": 1, "page_size": 100}

        if emp_code:
            params["emp_code"] = emp_code

        if date_from:
            params["date_from"] = date_from.isoformat()

        if date_to:
            params["date_to"] = date_to.isoformat()

        data = api_get("/attendance", params=params)

        if data and data["items"]:

            df = pd.DataFrame(data["items"])

            for field in ["punch_in", "punch_out"]:
                df[field] = df[field].apply(format_timestamp)

            st.metric("Total Matching Records", data["total"])

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )

        elif data:
            st.info("No attendance records found.")

    with tab2:

        st.subheader("Employee Punch In")

        with st.form("punch_in_form"):

            in_emp_code = st.text_input("Employee Code")
            status = st.selectbox(
                "Attendance Status",
                ["PRESENT", "WFH", "ON_DUTY"]
            )

            punch_in_submit = st.form_submit_button("Punch In")

            if punch_in_submit:

                result = api_post(
                    "/attendance/punch-in",
                    {
                        "emp_code": in_emp_code.strip(),
                        "status": status
                    }
                )

                if result:
                    st.success("Punch-in recorded!")
                    st.json(result)

        st.divider()

        st.subheader("Employee Punch Out")

        with st.form("punch_out_form"):

            out_emp_code = st.text_input("Employee Code")

            punch_out_submit = st.form_submit_button("Punch Out")

            if punch_out_submit:

                result = api_post(
                    "/attendance/punch-out",
                    {
                        "emp_code": out_emp_code.strip()
                    }
                )

                if result:
                    st.success("Punch-out recorded!")
                    st.json(result)


# --------------------------------------------------
# Analytics (Coming next)
# --------------------------------------------------

elif page == "Analytics":

    st.title("📈 Workforce Analytics")
    st.info("We'll build monthly reports, department summaries, late leaderboard and attendance trends here.")

# --------------------------------------------------
# Regularization (Coming next)
# --------------------------------------------------

elif page == "Regularization":

    st.title("📝 Attendance Regularization")
    st.info("We'll build the attendance correction form and audit history viewer here.")
