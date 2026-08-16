import os
import sqlite3
from datetime import date, datetime, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

DB_PATH = os.path.join(os.path.dirname(__file__), "salary_tracker.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                joining_date TEXT NOT NULL,
                daily_salary REAL NOT NULL CHECK(daily_salary >= 0),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS unpaid_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                leave_date TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, leave_date),
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS advances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                advance_date TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                category TEXT NOT NULL CHECK(category IN ('Small Advance', 'Large Advance')),
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()


def seed_sample_data():
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if count > 0:
            return

        today = date.today()
        samples = [
            ("Amit Sharma", today - timedelta(days=35), 850.0, 1),
            ("Priya Verma", today - timedelta(days=22), 1000.0, 1),
            ("Rakesh Kumar", today - timedelta(days=50), 725.0, 1),
            ("Sunita Devi", today - timedelta(days=15), 900.0, 1),
            ("Imran Khan", today - timedelta(days=80), 1100.0, 0),
        ]
        for name, joining, salary, active in samples:
            conn.execute(
                "INSERT INTO employees (name, joining_date, daily_salary, active) VALUES (?, ?, ?, ?)",
                (name, joining.isoformat(), salary, active),
            )
        conn.commit()

        ids = {
            row["name"]: row["id"]
            for row in conn.execute("SELECT id, name FROM employees").fetchall()
        }
        leaves = [
            (ids["Amit Sharma"], today - timedelta(days=10), "Unpaid leave"),
            (ids["Priya Verma"], today - timedelta(days=5), "Holiday"),
            (ids["Rakesh Kumar"], today - timedelta(days=20), "Personal leave"),
        ]
        for emp_id, d, note in leaves:
            conn.execute(
                "INSERT OR IGNORE INTO unpaid_days (employee_id, leave_date, note) VALUES (?, ?, ?)",
                (emp_id, d.isoformat(), note),
            )

        advs = [
            (ids["Amit Sharma"], today - timedelta(days=18), 2500.0, "Travel advance"),
            (ids["Amit Sharma"], today - timedelta(days=3), 7000.0, "Family expense"),
            (ids["Priya Verma"], today - timedelta(days=9), 3500.0, "Advance"),
            (ids["Rakesh Kumar"], today - timedelta(days=25), 5000.0, "Advance"),
            (ids["Sunita Devi"], today - timedelta(days=2), 1500.0, "Advance"),
        ]
        for emp_id, d, amount, note in advs:
            category = classify_advance(amount)
            conn.execute(
                "INSERT INTO advances (employee_id, advance_date, amount, category, note) VALUES (?, ?, ?, ?, ?)",
                (emp_id, d.isoformat(), amount, category, note),
            )
        conn.commit()


def classify_advance(amount):
    return "Small Advance" if float(amount) < 5000 else "Large Advance"


def rupee(value):
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, _, decimal = f"{value:.2f}".partition(".")
    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups + [last3])
    return f"{sign}₹{whole}.{decimal}"


def add_employee(name, joining_date, daily_salary, active=True):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO employees (name, joining_date, daily_salary, active) VALUES (?, ?, ?, ?)",
            (name.strip(), joining_date.isoformat(), float(daily_salary), int(active)),
        )
        conn.commit()


def update_employee(employee_id, name, joining_date, daily_salary, active):
    with get_connection() as conn:
        conn.execute(
            "UPDATE employees SET name=?, joining_date=?, daily_salary=?, active=? WHERE id=?",
            (name.strip(), joining_date.isoformat(), float(daily_salary), int(active), employee_id),
        )
        conn.commit()


def add_advance(employee_id, advance_date, amount, note=""):
    category = classify_advance(amount)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO advances (employee_id, advance_date, amount, category, note) VALUES (?, ?, ?, ?, ?)",
            (employee_id, advance_date.isoformat(), float(amount), category, note.strip()),
        )
        conn.commit()
    return category


def add_unpaid_day(employee_id, leave_date, note=""):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO unpaid_days (employee_id, leave_date, note) VALUES (?, ?, ?)",
            (employee_id, leave_date.isoformat(), note.strip()),
        )
        conn.commit()


def remove_unpaid_day(employee_id, leave_date):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM unpaid_days WHERE employee_id=? AND leave_date=?",
            (employee_id, leave_date.isoformat()),
        )
        conn.commit()


def update_advance(advance_id, advance_date, amount, note=""):
    category = classify_advance(amount)
    with get_connection() as conn:
        conn.execute(
            "UPDATE advances SET advance_date=?, amount=?, category=?, note=? WHERE id=?",
            (advance_date.isoformat(), float(amount), category, note.strip(), advance_id),
        )
        conn.commit()
    return category


def delete_advance(advance_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM advances WHERE id=?", (advance_id,))
        conn.commit()


def update_unpaid_day(unpaid_id, leave_date, note=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE unpaid_days SET leave_date=?, note=? WHERE id=?",
            (leave_date.isoformat(), note.strip(), unpaid_id),
        )
        conn.commit()


def delete_unpaid_day(unpaid_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM unpaid_days WHERE id=?", (unpaid_id,))
        conn.commit()


def get_employees():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM employees ORDER BY active DESC, name", conn)


def get_employee(employee_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        return dict(row) if row else None


def get_unpaid_days(employee_id=None):
    with get_connection() as conn:
        if employee_id is None:
            q = """
                SELECT u.id, u.employee_id, e.name, u.leave_date, u.note
                FROM unpaid_days u JOIN employees e ON e.id=u.employee_id
                ORDER BY u.leave_date DESC
            """
            return pd.read_sql_query(q, conn)
        return pd.read_sql_query(
            "SELECT * FROM unpaid_days WHERE employee_id=? ORDER BY leave_date DESC",
            conn,
            params=(employee_id,),
        )


def get_advances(employee_id=None):
    with get_connection() as conn:
        if employee_id is None:
            q = """
                SELECT a.id, a.employee_id, e.name, a.advance_date, a.amount, a.category, a.note
                FROM advances a JOIN employees e ON e.id=a.employee_id
                ORDER BY a.advance_date DESC, a.id DESC
            """
            return pd.read_sql_query(q, conn)
        return pd.read_sql_query(
            "SELECT * FROM advances WHERE employee_id=? ORDER BY advance_date DESC, id DESC",
            conn,
            params=(employee_id,),
        )


def employment_end_date(employee, as_of=None):
    as_of = as_of or date.today()
    joining = date.fromisoformat(employee["joining_date"])
    if as_of < joining:
        return None
    # Inactive status means no salary accrues after today; for historical tracking,
    # the app has no separate termination date, so calculations run through the selected as-of date.
    return as_of


def employee_daily_tracker(employee_id, as_of=None):
    employee = get_employee(employee_id)
    if not employee:
        return pd.DataFrame()
    as_of = as_of or date.today()
    joining = date.fromisoformat(employee["joining_date"])
    end = employment_end_date(employee, as_of)
    if end is None:
        return pd.DataFrame(columns=["Date", "Status", "Salary Earned", "Advance", "Advance Type", "Balance Change", "Running Balance"])

    unpaid_df = get_unpaid_days(employee_id)
    unpaid = {date.fromisoformat(d): n for d, n in zip(unpaid_df["leave_date"], unpaid_df["note"])} if not unpaid_df.empty else {}

    adv_df = get_advances(employee_id)
    adv_by_date = {}
    if not adv_df.empty:
        for _, row in adv_df.iterrows():
            d = date.fromisoformat(row["advance_date"])
            adv_by_date.setdefault(d, []).append((float(row["amount"]), row["category"], row.get("note", "")))

    rows = []
    running = 0.0
    current = joining
    while current <= end:
        salary = 0.0 if current in unpaid else float(employee["daily_salary"])
        advances = adv_by_date.get(current, [])
        advance_total = sum(x[0] for x in advances)
        types = ", ".join(sorted(set(x[1] for x in advances))) if advances else ""
        status = "Unpaid holiday/leave" if current in unpaid else "Salary counted"
        change = salary - advance_total
        running += change
        rows.append({
            "Date": current,
            "Status": status,
            "Salary Earned": salary,
            "Advance": advance_total,
            "Advance Type": types,
            "Balance Change": change,
            "Running Balance": running,
        })
        current += timedelta(days=1)
    return pd.DataFrame(rows)


def employee_totals(employee_id, as_of=None):
    tracker = employee_daily_tracker(employee_id, as_of)
    advances = get_advances(employee_id)
    salary = float(tracker["Salary Earned"].sum()) if not tracker.empty else 0.0
    worked_days = int((tracker["Status"] == "Salary counted").sum()) if not tracker.empty else 0
    small = float(advances.loc[advances["category"] == "Small Advance", "amount"].sum()) if not advances.empty else 0.0
    large = float(advances.loc[advances["category"] == "Large Advance", "amount"].sum()) if not advances.empty else 0.0
    total_adv = small + large
    return {
        "salary": salary,
        "worked_days": worked_days,
        "small": small,
        "large": large,
        "advances": total_adv,
        "owed": salary - total_adv,
    }


def dashboard_dataframe(as_of=None):
    employees = get_employees()
    rows = []
    for _, emp in employees.iterrows():
        totals = employee_totals(int(emp["id"]), as_of)
        rows.append({
            "ID": int(emp["id"]),
            "Employee": emp["name"],
            "Joining Date": emp["joining_date"],
            "Daily Salary": float(emp["daily_salary"]),
            "Status": "Active" if int(emp["active"]) else "Inactive",
            "Days Worked": totals["worked_days"],
            "Salary Earned": totals["salary"],
            "Small Advances": totals["small"],
            "Large Advances": totals["large"],
            "Salary Owed": totals["owed"],
        })
    return pd.DataFrame(rows)


def format_money_columns(df, columns):
    out = df.copy()
    for c in columns:
        if c in out.columns:
            out[c] = out[c].apply(rupee)
    return out


def to_excel_bytes(selected_employee_id=None):
    output = BytesIO()
    summary = dashboard_dataframe()
    employees = get_employees()
    advances = get_advances()
    unpaid = get_unpaid_days()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Overall Summary")
        employees.to_excel(writer, index=False, sheet_name="Employees")
        advances.to_excel(writer, index=False, sheet_name="All Advances")
        unpaid.to_excel(writer, index=False, sheet_name="Unpaid Days")

        if selected_employee_id:
            emp = get_employee(selected_employee_id)
            tracker = employee_daily_tracker(selected_employee_id)
            emp_adv = get_advances(selected_employee_id)
            emp_leave = get_unpaid_days(selected_employee_id)
            tracker.to_excel(writer, index=False, sheet_name="Employee Daily Tracker")
            emp_adv.to_excel(writer, index=False, sheet_name="Employee Advances")
            emp_leave.to_excel(writer, index=False, sheet_name="Employee Unpaid Days")

    output.seek(0)
    return output.getvalue()


def app_header():
    st.title("₹ Salary Tracker")
    st.caption("Every calendar day earns salary unless you mark that date as unpaid.")


def employee_choices(employees):
    return {f"{r['name']}": int(r["id"]) for _, r in employees.iterrows()}


def quick_actions(employees, key_prefix="home"):
    if employees.empty:
        st.info("Add an employee first.")
        return

    choices = employee_choices(employees)
    st.subheader("Quick Entry")
    action = st.radio("What do you want to add?", ["Advance", "Unpaid day"], horizontal=True, key=f"{key_prefix}_action")

    if action == "Advance":
        with st.form(f"{key_prefix}_advance", clear_on_submit=True):
            employee_name = st.selectbox("Employee", list(choices), key=f"{key_prefix}_adv_emp")
            emp = get_employee(choices[employee_name])
            joining = date.fromisoformat(emp["joining_date"])
            advance_date = st.date_input(
                "Advance date",
                value=date.today(),
                min_value=joining,
                max_value=date.today(),
                help="You can choose an earlier date if you forgot to enter the advance when it happened.",
                key=f"{key_prefix}_adv_date",
            )
            amount = st.number_input("Amount (₹)", min_value=1.0, step=100.0, key=f"{key_prefix}_adv_amount")
            note = st.text_input("Note (optional)", key=f"{key_prefix}_adv_note")
            if st.form_submit_button("Save Advance", type="primary", use_container_width=True):
                category = add_advance(choices[employee_name], advance_date, amount, note)
                st.success(f"Advance saved for {advance_date.strftime('%d %b %Y')} as {category}.")
                st.rerun()
    else:
        with st.form(f"{key_prefix}_leave", clear_on_submit=True):
            employee_name = st.selectbox("Employee", list(choices), key=f"{key_prefix}_leave_emp")
            emp = get_employee(choices[employee_name])
            joining = date.fromisoformat(emp["joining_date"])
            leave_date = st.date_input(
                "Unpaid date",
                value=date.today(),
                min_value=joining,
                max_value=date.today(),
                key=f"{key_prefix}_leave_date",
            )
            note = st.text_input("Reason / note (optional)", key=f"{key_prefix}_leave_note")
            if st.form_submit_button("Save Unpaid Day", type="primary", use_container_width=True):
                add_unpaid_day(choices[employee_name], leave_date, note)
                st.success(f"{leave_date.strftime('%d %b %Y')} marked unpaid.")
                st.rerun()


def dashboard_page():
    app_header()
    employees = get_employees()
    df = dashboard_dataframe()

    if df.empty:
        st.info("No employees yet. Choose 'Add Employee' from the left menu.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Employees", len(df))
    c2.metric("Small Advances", rupee(df["Small Advances"].sum()))
    c3.metric("Large Advances", rupee(df["Large Advances"].sum()))
    c4.metric("Total Salary Owed", rupee(df["Salary Owed"].sum()))

    st.subheader("Employee Balances")
    shown = df[["Employee", "Days Worked", "Daily Salary", "Status", "Salary Earned", "Small Advances", "Large Advances", "Salary Owed"]].copy()
    shown = format_money_columns(shown, ["Daily Salary", "Salary Earned", "Small Advances", "Large Advances", "Salary Owed"])
    st.dataframe(shown, use_container_width=True, hide_index=True)

    st.divider()
    quick_actions(employees, "dashboard")

    st.divider()
    st.download_button(
        "Download Everything to Excel",
        data=to_excel_bytes(),
        file_name=f"salary_tracker_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def add_employee_page():
    app_header()
    st.subheader("Add Employee")
    with st.form("add_employee", clear_on_submit=True):
        name = st.text_input("Name")
        joining_date = st.date_input("Joining date", value=date.today(), max_value=date.today())
        daily_salary = st.number_input("Daily salary (₹)", min_value=0.0, step=50.0)
        active = st.checkbox("Active", value=True)
        if st.form_submit_button("Add Employee", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Enter the employee name.")
            elif daily_salary <= 0:
                st.error("Daily salary must be more than ₹0.")
            else:
                add_employee(name, joining_date, daily_salary, active)
                st.success(f"{name.strip()} added.")
                st.rerun()


def employee_page():
    app_header()
    employees = get_employees()
    if employees.empty:
        st.info("No employees available.")
        return

    choices = employee_choices(employees)
    selected_name = st.selectbox("Employee", list(choices))
    employee_id = choices[selected_name]
    emp = get_employee(employee_id)
    totals = employee_totals(employee_id)

    c1, c2, c3 = st.columns(3)
    c1.metric("Salary Earned", rupee(totals["salary"]))
    c2.metric("Total Advances", rupee(totals["advances"]))
    c3.metric("Salary Owed", rupee(totals["owed"]))

    st.caption(f"Small advances: {rupee(totals['small'])}  •  Large advances: {rupee(totals['large'])}")

    tabs = st.tabs(["Add Entry", "Daily Tracker", "Advances", "Unpaid Days", "Edit Employee", "Export"])

    with tabs[0]:
        quick_actions(employees[employees["id"] == employee_id], f"employee_{employee_id}")

    with tabs[1]:
        tracker = employee_daily_tracker(employee_id)
        if tracker.empty:
            st.info("No salary days yet.")
        else:
            display = tracker.sort_values("Date", ascending=False).copy()
            display["Date"] = pd.to_datetime(display["Date"]).dt.strftime("%d %b %Y")
            display = format_money_columns(display, ["Salary Earned", "Advance", "Balance Change", "Running Balance"])
            st.dataframe(display, use_container_width=True, hide_index=True)

    with tabs[2]:
        advances = get_advances(employee_id)
        if advances.empty:
            st.info("No advances recorded.")
        else:
            display = advances[["advance_date", "amount", "category", "note"]].copy()
            display["advance_date"] = pd.to_datetime(display["advance_date"]).dt.strftime("%d %b %Y")
            display["amount"] = display["amount"].apply(rupee)
            display.columns = ["Date", "Amount", "Type", "Note"]
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.markdown("**Change or delete an advance**")
            options = {
                f"{date.fromisoformat(r['advance_date']).strftime('%d %b %Y')} — {rupee(r['amount'])} — {r['category']}": int(r["id"])
                for _, r in advances.iterrows()
            }
            selected = st.selectbox("Choose advance", list(options), key=f"edit_adv_{employee_id}")
            adv_id = options[selected]
            row = advances[advances["id"] == adv_id].iloc[0]
            joining = date.fromisoformat(emp["joining_date"])
            with st.form(f"change_adv_form_{adv_id}"):
                new_date = st.date_input("Date", value=date.fromisoformat(row["advance_date"]), min_value=joining, max_value=date.today())
                new_amount = st.number_input("Amount (₹)", min_value=1.0, step=100.0, value=float(row["amount"]))
                new_note = st.text_input("Note", value=row["note"] or "")
                save = st.form_submit_button("Save Changes", type="primary", use_container_width=True)
                if save:
                    update_advance(adv_id, new_date, new_amount, new_note)
                    st.success("Advance updated.")
                    st.rerun()
            if st.button("Delete This Advance", key=f"delete_adv_{adv_id}", use_container_width=True):
                delete_advance(adv_id)
                st.success("Advance deleted.")
                st.rerun()

    with tabs[3]:
        leaves = get_unpaid_days(employee_id)
        if leaves.empty:
            st.info("No unpaid days recorded.")
        else:
            display = leaves[["leave_date", "note"]].copy()
            display["leave_date"] = pd.to_datetime(display["leave_date"]).dt.strftime("%d %b %Y")
            display.columns = ["Date", "Note"]
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.markdown("**Change or remove an unpaid day**")
            options = {
                f"{date.fromisoformat(r['leave_date']).strftime('%d %b %Y')} — {r['note'] or 'No note'}": int(r["id"])
                for _, r in leaves.iterrows()
            }
            selected = st.selectbox("Choose unpaid day", list(options), key=f"edit_leave_{employee_id}")
            leave_id = options[selected]
            row = leaves[leaves["id"] == leave_id].iloc[0]
            joining = date.fromisoformat(emp["joining_date"])
            with st.form(f"change_leave_form_{leave_id}"):
                new_date = st.date_input("Date", value=date.fromisoformat(row["leave_date"]), min_value=joining, max_value=date.today())
                new_note = st.text_input("Note", value=row["note"] or "", key=f"leave_note_{leave_id}")
                if st.form_submit_button("Save Changes", type="primary", use_container_width=True):
                    try:
                        update_unpaid_day(leave_id, new_date, new_note)
                        st.success("Unpaid day updated.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("That employee already has an unpaid entry for this date.")
            if st.button("Remove This Unpaid Day", key=f"delete_leave_{leave_id}", use_container_width=True):
                delete_unpaid_day(leave_id)
                st.success("Unpaid day removed. Salary will count for that date again.")
                st.rerun()

    with tabs[4]:
        with st.form("edit_employee"):
            name = st.text_input("Name", value=emp["name"])
            joining = st.date_input("Joining date", value=date.fromisoformat(emp["joining_date"]), max_value=date.today())
            salary = st.number_input("Daily salary (₹)", min_value=0.0, step=50.0, value=float(emp["daily_salary"]))
            active = st.checkbox("Active", value=bool(emp["active"]))
            if st.form_submit_button("Save Employee Changes", type="primary", use_container_width=True):
                if not name.strip() or salary <= 0:
                    st.error("Name and a daily salary above ₹0 are required.")
                else:
                    update_employee(employee_id, name, joining, salary, active)
                    st.success("Employee details updated.")
                    st.rerun()
        st.caption("Changing the joining date or daily salary recalculates the employee's salary history using the new details.")

    with tabs[5]:
        st.download_button(
            "Download This Employee to Excel",
            data=to_excel_bytes(employee_id),
            file_name=f"{emp['name'].replace(' ', '_')}_salary_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def main():
    st.set_page_config(page_title="Salary Tracker", page_icon="₹", layout="wide")
    init_db()
    seed_sample_data()

    st.sidebar.title("₹ Salary Tracker")
    page = st.sidebar.radio("Menu", ["Home", "Employee", "Add Employee"])
    st.sidebar.caption(f"Today: {date.today().strftime('%d %b %Y')}")

    if page == "Home":
        dashboard_page()
    elif page == "Employee":
        employee_page()
    else:
        add_employee_page()


if __name__ == "__main__":
    main()
