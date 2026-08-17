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


def add_employee(name, joining_date, daily_salary, end_date=None):
    get_supabase().table("employees").insert({
        "name": name.strip(),
        "joining_date": joining_date.isoformat(),
        "daily_salary": float(daily_salary),
        "end_date": end_date.isoformat() if end_date else None,
    }).execute()


def update_employee(employee_id, name, joining_date, daily_salary, end_date=None):
    get_supabase().table("employees").update({
        "name": name.strip(),
        "joining_date": joining_date.isoformat(),
        "daily_salary": float(daily_salary),
        "end_date": end_date.isoformat() if end_date else None,
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
    get_supabase().table("unpaid_days").upsert({
        "employee_id": int(employee_id),
        "leave_date": leave_date.isoformat(),
        "note": note.strip(),
    }, on_conflict="employee_id,leave_date").execute()


def add_unpaid_range(employee_id, start_date, end_date, note=""):
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


def add_payment(employee_id, payment_date, amount, payment_type, note=""):
    get_supabase().table("payments").insert({
        "employee_id": int(employee_id),
        "payment_date": payment_date.isoformat(),
        "amount": float(amount),
        "payment_type": payment_type,
        "note": note.strip(),
    }).execute()


def update_payment(payment_id, payment_date, amount, payment_type, note=""):
    get_supabase().table("payments").update({
        "payment_date": payment_date.isoformat(),
        "amount": float(amount),
        "payment_type": payment_type,
        "note": note.strip(),
    }).eq("id", int(payment_id)).execute()


def delete_payment(payment_id):
    get_supabase().table("payments").delete().eq("id", int(payment_id)).execute()


def update_unpaid_day(unpaid_id, leave_date, note=""):
    get_supabase().table("unpaid_days").update({
        "leave_date": leave_date.isoformat(),
        "note": note.strip(),
    }).eq("id", int(unpaid_id)).execute()


def delete_unpaid_day(unpaid_id):
    get_supabase().table("unpaid_days").delete().eq("id", int(unpaid_id)).execute()


def delete_employee(employee_id):
    employee_id = int(employee_id)
    get_supabase().table("advances").delete().eq("employee_id", employee_id).execute()
    get_supabase().table("payments").delete().eq("employee_id", employee_id).execute()
    get_supabase().table("unpaid_days").delete().eq("employee_id", employee_id).execute()
    get_supabase().table("employees").delete().eq("id", employee_id).execute()


def get_employees():
    response = (
        get_supabase()
        .table("employees")
        .select("*")
        .order("name")
        .execute()
    )
    return _df(
        response.data,
        ["id", "name", "joining_date", "daily_salary", "end_date", "created_at"],
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


def get_payments(employee_id=None):
    query = (
        get_supabase()
        .table("payments")
        .select("*")
        .order("payment_date", desc=True)
        .order("id", desc=True)
    )
    if employee_id is not None:
        query = query.eq("employee_id", int(employee_id))

    response = query.execute()
    df = _df(
        response.data,
        ["id", "employee_id", "payment_date", "amount", "payment_type", "note", "created_at"],
    )

    if employee_id is None and not df.empty:
        employees = get_employees()
        if not employees.empty:
            names = employees[["id", "name"]].rename(columns={"id": "employee_id"})
            df = df.merge(names, on="employee_id", how="left")
            ordered = ["id", "employee_id", "name", "payment_date", "amount", "payment_type", "note"]
            df = df[[c for c in ordered if c in df.columns]]
    return df


def employment_end_date(employee, as_of=None):
    as_of = as_of or date.today()
    joining = date.fromisoformat(employee["joining_date"])
    if as_of < joining:
        return None
    
    end_date_str = employee.get("end_date")
    if pd.notna(end_date_str) and str(end_date_str).strip() and str(end_date_str).lower() != "nan":
        emp_end = date.fromisoformat(str(end_date_str))
        return min(as_of, emp_end)
        
    return as_of


def employee_daily_tracker(employee_id, as_of=None):
    employee = get_employee(employee_id)
    if not employee:
        return pd.DataFrame()
    as_of = as_of or date.today()
    joining = date.fromisoformat(employee["joining_date"])
    end = employment_end_date(employee, as_of)
    if end is None:
        return pd.DataFrame(columns=["Date", "Status", "Salary Earned", "Advance", "Advance Type", "Payment", "Balance Change", "Running Balance"])

    unpaid_df = get_unpaid_days(employee_id)
    unpaid = {date.fromisoformat(d): n for d, n in zip(unpaid_df["leave_date"], unpaid_df["note"])} if not unpaid_df.empty else {}

    adv_df = get_advances(employee_id)
    adv_by_date = {}
    if not adv_df.empty:
        for _, row in adv_df.iterrows():
            d = date.fromisoformat(row["advance_date"])
            adv_by_date.setdefault(d, []).append((float(row["amount"]), row["category"], row.get("note", "")))

    payment_df = get_payments(employee_id)
    payments_by_date = {}
    if not payment_df.empty:
        for _, row in payment_df.iterrows():
            d = date.fromisoformat(row["payment_date"])
            payments_by_date.setdefault(d, []).append(float(row["amount"]))

    rows = []
    running = 0.0
    current = joining
    while current <= end:
        salary = 0.0 if current in unpaid else float(employee["daily_salary"])
        advances = adv_by_date.get(current, [])
        advance_total = sum(x[0] for x in advances)
        types = ", ".join(sorted(set(x[1] for x in advances))) if advances else ""
        payment_total = sum(payments_by_date.get(current, []))
        status = "Unpaid holiday/leave" if current in unpaid else "Salary counted"
        change = salary - advance_total - payment_total
        running += change
        rows.append({
            "Date": current,
            "Status": status,
            "Salary Earned": salary,
            "Advance": advance_total,
            "Advance Type": types,
            "Payment": payment_total,
            "Balance Change": change,
            "Running Balance": running,
        })
        current += timedelta(days=1)
    return pd.DataFrame(rows)


def employee_totals(employee_id, as_of=None):
    tracker = employee_daily_tracker(employee_id, as_of)
    salary = float(tracker["Salary Earned"].sum()) if not tracker.empty else 0.0
    worked_days = int((tracker["Status"] == "Salary counted").sum()) if not tracker.empty else 0
    total_adv = float(tracker["Advance"].sum()) if not tracker.empty else 0.0
    total_payments = float(tracker["Payment"].sum()) if not tracker.empty else 0.0

    advances = get_advances(employee_id)
    if as_of is not None and not advances.empty:
        advances = advances[pd.to_datetime(advances["advance_date"]).dt.date <= as_of]
    small = float(advances.loc[advances["category"] == "Small Advance", "amount"].sum()) if not advances.empty else 0.0
    large = float(advances.loc[advances["category"] == "Large Advance", "amount"].sum()) if not advances.empty else 0.0

    return {
        "salary": salary,
        "worked_days": worked_days,
        "small": small,
        "large": large,
        "advances": total_adv,
        "payments": total_payments,
        "owed": salary - total_adv - total_payments,
    }


def dashboard_dataframe(as_of=None):
    employees = get_employees()
    rows = []
    today = date.today()
    for _, emp in employees.iterrows():
        totals = employee_totals(int(emp["id"]), as_of)
        
        end_str = emp.get("end_date")
        if pd.notna(end_str) and str(end_str).strip() and str(end_str).lower() != "nan":
            is_active = "No" if date.fromisoformat(str(end_str)) <= (as_of or today) else "Yes"
        else:
            is_active = "Yes"
            
        rows.append({
            "ID": int(emp["id"]),
            "Employee": emp["name"],
            "Active?": is_active,
            "Joining Date": emp["joining_date"],
            "Daily Salary": float(emp["daily_salary"]),
            "Days Worked": totals["worked_days"],
            "Salary Earned": totals["salary"],
            "Small Advances": totals["small"],
            "Large Advances": totals["large"],
            "Payments": totals["payments"],
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
    payments = get_payments()
    unpaid = get_unpaid_days()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Overall Summary")
        employees.to_excel(writer, index=False, sheet_name="Employees")
        advances.to_excel(writer, index=False, sheet_name="All Advances")
        payments.to_excel(writer, index=False, sheet_name="All Payments")
        unpaid.to_excel(writer, index=False, sheet_name="Unpaid Days")

        if selected_employee_id:
            emp = get_employee(selected_employee_id)
            tracker = employee_daily_tracker(selected_employee_id)
            emp_adv = get_advances(selected_employee_id)
            emp_payments = get_payments(selected_employee_id)
            emp_leave = get_unpaid_days(selected_employee_id)
            tracker.to_excel(writer, index=False, sheet_name="Employee Daily Tracker")
            emp_adv.to_excel(writer, index=False, sheet_name="Employee Advances")
            emp_payments.to_excel(writer, index=False, sheet_name="Employee Payments")
            emp_leave.to_excel(writer, index=False, sheet_name="Employee Unpaid Days")

    output.seek(0)
    return output.getvalue()


def app_header():
    st.title("₹ Salary Tracker")
    st.caption("Every calendar day earns salary unless you mark that date as unpaid.")


def employee_choices(employees):
    return {f"{r['name']} (ID: {r['id']})": int(r["id"]) for _, r in employees.iterrows()}


def quick_actions(employees, key_prefix="home"):
    if employees.empty:
        st.info("Add an employee first.")
        return

    choices = employee_choices(employees)
    st.subheader("Quick Entry")
    action = st.radio(
        "What do you want to add?",
        ["Advance", "Payment", "Unpaid day / range"],
        horizontal=True,
        key=f"{key_prefix}_action",
    )

    if action == "Advance":
        with st.form(f"{key_prefix}_advance", clear_on_submit=True):
            employee_name = st.selectbox("Employee", list(choices), key=f"{key_prefix}_adv_emp")
            emp = get_employee(choices[employee_name])
            joining = date.fromisoformat(emp["joining_date"])
            
            emp_end_date = emp.get("end_date")
            is_valid_end = pd.notna(emp_end_date) and str(emp_end_date).strip() and str(emp_end_date).lower() != "nan"
            max_allowed_date = date.fromisoformat(str(emp_end_date)) if is_valid_end else date.today()
            max_allowed_date = max(joining, max_allowed_date)

            advance_date = st.date_input(
                "Advance date",
                value=max_allowed_date,
                min_value=joining,
                max_value=max_allowed_date,
                help="You can choose an earlier date if you forgot to enter the advance when it happened.",
                key=f"{key_prefix}_adv_date",
            )
            amount = st.number_input("Amount (₹)", min_value=1.0, step=100.0, key=f"{key_prefix}_adv_amount")
            note = st.text_input("Note (optional)", key=f"{key_prefix}_adv_note")
            if st.form_submit_button("Save Advance", type="primary", use_container_width=True):
                category = add_advance(choices[employee_name], advance_date, amount, note)
                st.success(f"Advance saved for {advance_date.strftime('%d %b %Y')} as {category}.")
                st.rerun()

    elif action == "Payment":
        employee_name = st.selectbox("Employee", list(choices), key=f"{key_prefix}_pay_emp")
        employee_id = choices[employee_name]
        emp = get_employee(employee_id)
        joining = date.fromisoformat(emp["joining_date"])
        
        # Payments can be processed anytime up to today, regardless of end_date
        payment_date = st.date_input(
            "Payment date",
            value=date.today(),
            min_value=joining,
            max_value=date.today(),
            key=f"{key_prefix}_pay_date",
        )
        payment_type = st.radio(
            "Payment type",
            ["Partial payment", "Full settlement"],
            horizontal=True,
            key=f"{key_prefix}_pay_type",
        )
        balance_on_date = employee_totals(employee_id, payment_date)["owed"]
        st.info(f"Salary owed on {payment_date.strftime('%d %b %Y')}: {rupee(balance_on_date)}")

        with st.form(f"{key_prefix}_payment", clear_on_submit=True):
            if payment_type == "Partial payment":
                amount = st.number_input("Payment amount (₹)", min_value=1.0, step=100.0, key=f"{key_prefix}_pay_amount")
            else:
                amount = max(float(balance_on_date), 0.0)
                st.metric("Full settlement amount", rupee(amount))
                st.caption("This pays the entire outstanding salary through the selected payment date. Salary earned after this date starts building again from ₹0.")

            note = st.text_input("Note (optional)", key=f"{key_prefix}_pay_note")
            if st.form_submit_button("Save Payment", type="primary", use_container_width=True):
                if amount <= 0:
                    st.error("There is no positive salary balance to settle on this date.")
                elif payment_type == "Partial payment" and amount > balance_on_date:
                    st.error(f"Payment cannot be more than the salary owed ({rupee(balance_on_date)}).")
                else:
                    add_payment(employee_id, payment_date, amount, payment_type, note)
                    if payment_type == "Full settlement":
                        st.success(f"Full settlement of {rupee(amount)} saved. Balance is ₹0.00 on {payment_date.strftime('%d %b %Y')}.")
                    else:
                        st.success(f"Payment of {rupee(amount)} saved.")
                    st.rerun()

    else:
        with st.form(f"{key_prefix}_leave", clear_on_submit=True):
            employee_name = st.selectbox("Employee", list(choices), key=f"{key_prefix}_leave_emp")
            emp = get_employee(choices[employee_name])
            joining = date.fromisoformat(emp["joining_date"])
            
            emp_end_date = emp.get("end_date")
            is_valid_end = pd.notna(emp_end_date) and str(emp_end_date).strip() and str(emp_end_date).lower() != "nan"
            max_allowed_date = date.fromisoformat(str(emp_end_date)) if is_valid_end else date.today()
            max_allowed_date = max(joining, max_allowed_date)

            c1, c2 = st.columns(2)
            with c1:
                start_date = st.date_input(
                    "Start date",
                    value=max_allowed_date,
                    min_value=joining,
                    max_value=max_allowed_date,
                    key=f"{key_prefix}_leave_start",
                )
            with c2:
                end_date = st.date_input(
                    "End date",
                    value=max_allowed_date,
                    min_value=joining,
                    max_value=max_allowed_date,
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

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Employees", len(df))
    c2.metric("Small Advances", rupee(df["Small Advances"].sum()))
    c3.metric("Large Advances", rupee(df["Large Advances"].sum()))
    c4.metric("Payments", rupee(df["Payments"].sum()))
    c5.metric("Total Salary Owed", rupee(df["Salary Owed"].sum()))

    st.subheader("Employee Balances")
    shown = df[["Employee", "Active?", "Days Worked", "Daily Salary", "Salary Earned", "Small Advances", "Large Advances", "Payments", "Salary Owed"]].copy()
    shown = format_money_columns(shown, ["Daily Salary", "Salary Earned", "Small Advances", "Large Advances", "Payments", "Salary Owed"])
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
    
    # We add completely unique widget keys here to guarantee Streamlit updates the UI instantly
    name = st.text_input("Name", key="add_new_emp_name")
    joining_date = st.date_input("Joining date", value=date.today(), max_value=date.today(), key="add_new_emp_join")
    
    has_left = st.checkbox("Employee has stopped working", key="add_new_emp_has_left")
    if has_left:
        end_date = st.date_input("End date", value=date.today(), max_value=date.today(), key="add_new_emp_end")
    else:
        end_date = None
        
    daily_salary = st.number_input("Daily salary (₹)", min_value=0.0, step=50.0, key="add_new_emp_salary")
    
    if st.button("Add Employee", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Enter the employee name.")
        elif daily_salary <= 0:
            st.error("Daily salary must be more than ₹0.")
        elif has_left and end_date < joining_date:
            st.error("End date cannot be before joining date.")
        else:
            add_employee(name, joining_date, daily_salary, end_date)
            st.success(f"{name.strip()} added successfully.")
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Salary Earned", rupee(totals["salary"]))
    c2.metric("Total Advances", rupee(totals["advances"]))
    c3.metric("Payments Made", rupee(totals["payments"]))
    c4.metric("Salary Owed", rupee(totals["owed"]))

    st.caption(f"Small advances: {rupee(totals['small'])}  •  Large advances: {rupee(totals['large'])}")

    tabs = st.tabs(["Add Entry", "Daily Tracker", "Advances", "Payments", "Unpaid Days", "Edit Employee", "Export"])

    with tabs[0]:
        quick_actions(employees[employees["id"] == employee_id], f"employee_{employee_id}")

    with tabs[1]:
        tracker = employee_daily_tracker(employee_id)
        if tracker.empty:
            st.info("No salary days yet.")
        else:
            display = tracker.sort_values("Date", ascending=False).copy()
            display["Date"] = pd.to_datetime(display["Date"]).dt.strftime("%d %b %Y")
            display = format_money_columns(display, ["Salary Earned", "Advance", "Payment", "Balance Change", "Running Balance"])
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
                emp_end_date = emp.get("end_date")
                is_valid_end = pd.notna(emp_end_date) and str(emp_end_date).strip() and str(emp_end_date).lower() != "nan"
                max_adv_date = date.fromisoformat(str(emp_end_date)) if is_valid_end else date.today()
                max_adv_date = max(joining, max_adv_date)
                
                new_date = st.date_input("Date", value=date.fromisoformat(row["advance_date"]), min_value=joining, max_value=max_adv_date)
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
        payments = get_payments(employee_id)
        if payments.empty:
            st.info("No salary payments recorded.")
        else:
            display = payments[["payment_date", "amount", "payment_type", "note"]].copy()
            display["payment_date"] = pd.to_datetime(display["payment_date"]).dt.strftime("%d %b %Y")
            display["amount"] = display["amount"].apply(rupee)
            display.columns = ["Date", "Amount", "Type", "Note"]
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.markdown("**Change or delete a payment**")
            options = {
                f"{date.fromisoformat(r['payment_date']).strftime('%d %b %Y')} — {rupee(r['amount'])}": int(r["id"])
                for _, r in payments.iterrows()
            }
            selected = st.selectbox("Choose payment", list(options), key=f"edit_payment_{employee_id}")
            payment_id = options[selected]
            row = payments[payments["id"] == payment_id].iloc[0]
            joining = date.fromisoformat(emp["joining_date"])
            with st.form(f"change_payment_form_{payment_id}"):
                new_date = st.date_input("Date", value=date.fromisoformat(row["payment_date"]), min_value=joining, max_value=date.today())
                new_amount = st.number_input("Amount (₹)", min_value=1.0, step=100.0, value=float(row["amount"]))
                existing_type = row.get("payment_type") or "Partial payment"
                new_type = st.selectbox(
                    "Type",
                    ["Partial payment", "Full settlement"],
                    index=0 if existing_type == "Partial payment" else 1,
                )
                new_note = st.text_input("Note", value=row["note"] or "", key=f"payment_note_{payment_id}")
                if st.form_submit_button("Save Changes", type="primary", use_container_width=True):
                    update_payment(payment_id, new_date, new_amount, new_type, new_note)
                    st.success("Payment updated.")
                    st.rerun()
            if st.button("Delete This Payment", key=f"delete_payment_{payment_id}", use_container_width=True):
                delete_payment(payment_id)
                st.success("Payment deleted.")
                st.rerun()

    with tabs[4]:
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
                emp_end_date = emp.get("end_date")
                is_valid_end = pd.notna(emp_end_date) and str(emp_end_date).strip() and str(emp_end_date).lower() != "nan"
                max_leave_date = date.fromisoformat(str(emp_end_date)) if is_valid_end else date.today()
                max_leave_date = max(joining, max_leave_date)
                
                # I completed the cut-off code here for you!
                new_date = st.date_input("Date", value=date.fromisoformat(row["leave_date"]), min_value=joining, max_value=max_leave_date)
                new_note = st.text_input("Note", value=row["note"] or "")
                
                if st.form_submit_button("Save Changes", type="primary", use_container_width=True):
                    update_unpaid_day(leave_id, new_date, new_note)
                    st.success("Unpaid day updated.")
                    st.rerun()

            if st.button("Delete This Unpaid Day", key=f"delete_leave_{leave_id}", use_container_width=True):
                delete_unpaid_day(leave_id)
                st.success("Unpaid day deleted.")
                st.rerun()

    with tabs[5]:
        # Edit Employee section with the form wrapper completely removed and custom keys attached
        st.subheader("Edit Employee Details")
        
        edit_name = st.text_input("Name", value=emp["name"], key=f"edit_name_{employee_id}")
        edit_joining = st.date_input("Joining date", value=date.fromisoformat(emp["joining_date"]), max_value=date.today(), key=f"edit_join_{employee_id}")
        
        existing_end_date = emp.get("end_date")
        is_valid_end = pd.notna(existing_end_date) and str(existing_end_date).strip() and str(existing_end_date).lower() != "nan"
        
        edit_has_left = st.checkbox("Employee stopped working", value=is_valid_end, key=f"edit_left_{employee_id}")
        
        if edit_has_left:
            default_end = date.fromisoformat(str(existing_end_date)) if is_valid_end else date.today()
            edit_end_date = st.date_input("End date", value=default_end, max_value=date.today(), key=f"edit_end_{employee_id}")
        else:
            edit_end_date = None
            
        edit_salary = st.number_input("Daily salary (₹)", min_value=0.0, step=50.0, value=float(emp["daily_salary"]), key=f"edit_salary_{employee_id}")
        
        if st.button("Save Employee Changes", type="primary", use_container_width=True, key=f"save_emp_{employee_id}"):
            if not edit_name.strip() or edit_salary <= 0:
                st.error("Name and a daily salary above ₹0 are required.")
            elif edit_has_left and edit_end_date < edit_joining:
                st.error("End date cannot be before joining date.")
            else:
                valid_to_save = True
                if edit_has_left and edit_end_date:
                    advances_df = get_advances(employee_id)
                    if not advances_df.empty:
                        adv_max = pd.to_datetime(advances_df["advance_date"]).dt.date.max()
                        if pd.notna(adv_max) and edit_end_date < adv_max:
                            st.error(f"Cannot set end date to {edit_end_date.strftime('%d %b %Y')} because an advance was given on {adv_max.strftime('%d %b %Y')}. Please edit the advance date first.")
                            valid_to_save = False

                if valid_to_save:
                    update_employee(employee_id, edit_name, edit_joining, edit_salary, edit_end_date)
                    st.success("Employee details updated.")
                    st.rerun()
                    
        st.caption("Changing the joining date or daily salary recalculates the employee's salary history using the new details.")

        st.divider()
        st.warning(
            "Deleting an employee is permanent and will also delete all of their "
            "advances, payments, and unpaid-day records."
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

    with tabs[6]:
        st.subheader("Export Data")
        st.download_button(
            f"Download {emp['name']}'s Data to Excel",
            data=to_excel_bytes(selected_employee_id=employee_id),
            file_name=f"{emp['name'].replace(' ', '_')}_salary_data_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def main():
    st.set_page_config(page_title="Salary Tracker", layout="centered")
    
    st.sidebar.title("Navigation")
    menu = ["Dashboard", "Add Employee", "Manage Employees"]
    choice = st.sidebar.radio("Go to", menu)
    
    if choice == "Dashboard":
        dashboard_page()
    elif choice == "Add Employee":
        add_employee_page()
    elif choice == "Manage Employees":
        employee_page()

if __name__ == "__main__":
    main()
