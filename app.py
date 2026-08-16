from datetime import date, datetime, timedelta
from io import BytesIO
import hmac

import pandas as pd
import streamlit as st
from supabase import create_client, Client



@st.cache_resource
def get_supabase() -> Client:
    """Create one Supabase client using secrets stored in Streamlit Cloud."""
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except KeyError as exc:
        raise RuntimeError(
            "Missing Supabase secrets. Add SUPABASE_URL and SUPABASE_KEY "
            "in Streamlit Community Cloud → App settings → Secrets."
        ) from exc
    return create_client(url, key)


def _df(rows, columns=None):
    """Convert Supabase response rows to a DataFrame with stable columns."""
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=columns or [])


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
    get_supabase().table("employees").insert({
        "name": name.strip(),
        "joining_date": joining_date.isoformat(),
        "daily_salary": float(daily_salary),
        "active": bool(active),
    }).execute()


def update_employee(employee_id, name, joining_date, daily_salary, active):
    get_supabase().table("employees").update({
        "name": name.strip(),
        "joining_date": joining_date.isoformat(),
        "daily_salary": float(daily_salary),
        "active": bool(active),
    }).eq("id", int(employee_id)).execute()


def add_advance(employee_id, advance_date, amount, note=""):
    category = classify_advance(amount)
    get_supabase().table("advances").insert({
        "employee_id": int(employee_id),
        "advance_date": advance_date.isoformat(),
        "amount": float(amount),
        "category": category,
        "note": note.strip(),
    }).execute()
    return category


def add_unpaid_day(employee_id, leave_date, note=""):
    # employee_id + leave_date is unique in Supabase.
    # Upsert makes this behave like the old SQLite INSERT OR REPLACE.
    get_supabase().table("unpaid_days").upsert({
        "employee_id": int(employee_id),
        "leave_date": leave_date.isoformat(),
        "note": note.strip(),
    }, on_conflict="employee_id,leave_date").execute()


def add_unpaid_range(employee_id, start_date, end_date, note=""):
    """Mark every calendar day from start_date through end_date as unpaid."""
    if end_date < start_date:
        raise ValueError("End date cannot be before start date.")

    rows = []
    current = start_date
    while current <= end_date:
        rows.append({
            "employee_id": int(employee_id),
            "leave_date": current.isoformat(),
            "note": note.strip(),
        })
        current += timedelta(days=1)

    get_supabase().table("unpaid_days").upsert(
        rows, on_conflict="employee_id,leave_date"
    ).execute()
    return len(rows)


def remove_unpaid_day(employee_id, leave_date):
    (
        get_supabase()
        .table("unpaid_days")
        .delete()
        .eq("employee_id", int(employee_id))
        .eq("leave_date", leave_date.isoformat())
        .execute()
    )


def update_advance(advance_id, advance_date, amount, note=""):
    category = classify_advance(amount)
    get_supabase().table("advances").update({
        "advance_date": advance_date.isoformat(),
        "amount": float(amount),
        "category": category,
        "note": note.strip(),
    }).eq("id", int(advance_id)).execute()
    return category


def delete_advance(advance_id):
    get_supabase().table("advances").delete().eq("id", int(advance_id)).execute()


def update_unpaid_day(unpaid_id, leave_date, note=""):
    get_supabase().table("unpaid_days").update({
        "leave_date": leave_date.isoformat(),
        "note": note.strip(),
    }).eq("id", int(unpaid_id)).execute()


def delete_unpaid_day(unpaid_id):
    get_supabase().table("unpaid_days").delete().eq("id", int(unpaid_id)).execute()


def delete_employee(employee_id):
    employee_id = int(employee_id)

    # Delete related records first so no employee history is left behind.
    get_supabase().table("advances").delete().eq("employee_id", employee_id).execute()
    get_supabase().table("unpaid_days").delete().eq("employee_id", employee_id).execute()

    # Finally delete the employee record itself.
    get_supabase().table("employees").delete().eq("id", employee_id).execute()


def get_employees():
    response = (
        get_supabase()
        .table("employees")
        .select("*")
        .order("active", desc=True)
        .order("name")
        .execute()
    )
    return _df(
        response.data,
        ["id", "name", "joining_date", "daily_salary", "active", "created_at"],
    )


def get_employee(employee_id):
    response = (
        get_supabase()
        .table("employees")
        .select("*")
        .eq("id", int(employee_id))
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def get_unpaid_days(employee_id=None):
    query = get_supabase().table("unpaid_days").select("*").order("leave_date", desc=True)
    if employee_id is not None:
        query = query.eq("employee_id", int(employee_id))

    response = query.execute()
    df = _df(
        response.data,
        ["id", "employee_id", "leave_date", "note", "created_at"],
    )

    if employee_id is None and not df.empty:
        employees = get_employees()
        if not employees.empty:
            names = employees[["id", "name"]].rename(columns={"id": "employee_id"})
            df = df.merge(names, on="employee_id", how="left")
            ordered = ["id", "employee_id", "name", "leave_date", "note"]
            df = df[[c for c in ordered if c in df.columns]]
    return df


def get_advances(employee_id=None):
    query = (
        get_supabase()
        .table("advances")
        .select("*")
        .order("advance_date", desc=True)
        .order("id", desc=True)
    )
    if employee_id is not None:
        query = query.eq("employee_id", int(employee_id))

    response = query.execute()
    df = _df(
        response.data,
        ["id", "employee_id", "advance_date", "amount", "category", "note", "created_at"],
    )

    if employee_id is None and not df.empty:
        employees = get_employees()
        if not employees.empty:
            names = employees[["id", "name"]].rename(columns={"id": "employee_id"})
            df = df.merge(names, on="employee_id", how="left")
            ordered = ["id", "employee_id", "name", "advance_date", "amount", "category", "note"]
            df = df[[c for c in ordered if c in df.columns]]
    return df


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
    action = st.radio("What do you want to add?", ["Advance", "Unpaid day / range"], horizontal=True, key=f"{key_prefix}_action")

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

            c1, c2 = st.columns(2)
            with c1:
                start_date = st.date_input(
                    "Start date",
                    value=date.today(),
                    min_value=joining,
                    key=f"{key_prefix}_leave_start",
                )
            with c2:
                end_date = st.date_input(
                    "End date",
                    value=date.today(),
                    min_value=joining,
                    key=f"{key_prefix}_leave_end",
                )

            st.caption("For a single unpaid day, choose the same Start date and End date.")
            note = st.text_input("Reason / note (optional)", key=f"{key_prefix}_leave_note")

            if st.form_submit_button("Save Unpaid Holiday", type="primary", use_container_width=True):
                if end_date < start_date:
                    st.error("End date cannot be before the start date.")
                else:
                    days_added = add_unpaid_range(choices[employee_name], start_date, end_date, note)
                    if days_added == 1:
                        st.success(f"{start_date.strftime('%d %b %Y')} marked unpaid.")
                    else:
                        st.success(
                            f"{days_added} days marked unpaid: "
                            f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}."
                        )
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
                    except Exception as exc:
                        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                            st.error("That employee already has an unpaid entry for this date.")
                        else:
                            st.error(f"Could not update unpaid day: {exc}")
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

        st.divider()
        st.warning(
            "Deleting an employee is permanent and will also delete all of their "
            "advances and unpaid-day records."
        )
        confirm_delete = st.checkbox(
            f"I confirm that I want to permanently delete {emp['name']}",
            key=f"confirm_delete_employee_{employee_id}",
        )
        if st.button(
            "🗑️ Delete Employee",
            type="secondary",
            use_container_width=True,
            disabled=not confirm_delete,
            key=f"delete_employee_{employee_id}",
        ):
            delete_employee(employee_id)
            st.success(f"{emp['name']} has been deleted.")
            st.rerun()

    with tabs[5]:
        st.download_button(
            "Download This Employee to Excel",
            data=to_excel_bytes(employee_id),
            file_name=f"{emp['name'].replace(' ', '_')}_salary_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )



def check_password():
    """Require the shared app password before showing any salary data."""
    if st.session_state.get("password_correct", False):
        return True

    st.title("🔒 Salary Tracker")
    st.caption("Enter the password to access this app.")

    password = st.text_input("Password", type="password")

    if st.button("Login", type="primary", use_container_width=True):
        try:
            expected_password = st.secrets["APP_PASSWORD"]
        except KeyError:
            st.error(
                "APP_PASSWORD is missing. Add it in Streamlit Community Cloud "
                "→ App settings → Secrets."
            )
            return False

        if hmac.compare_digest(password, expected_password):
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False


def main():
    st.set_page_config(page_title="Salary Tracker", page_icon="₹", layout="wide")

    if not check_password():
        st.stop()

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
