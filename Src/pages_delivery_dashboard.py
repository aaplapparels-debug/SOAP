"""Delivery & Dispatch Management Dashboard"""

from datetime import date
from config_loader import load_config
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import streamlit as st


@st.cache_resource
def get_engine():
    config = load_config()
    # NullPool prevents poisoned connection states across Streamlit reruns
    return create_engine(
        config["postgres"]["connection_string"],
        poolclass=NullPool,
    )


def show_delivery_dashboard():
    st.title("🚚 Delivery & Dispatch Operations")

    engine = get_engine()
    current_user = st.session_state.get("user_email", "Operations User")

    # ---------------------------------------------------------
    # 1. Search & Filter Bar
    # ---------------------------------------------------------
    with st.expander("🔍 Search & Filter Deliveries", expanded=True):
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)

        with f_col1:
            date_range = st.date_input(
                "Document Date Range",
                value=[
                    date.today() - pd.Timedelta(days=15),
                    date.today(),
                ],
            )
        with f_col2:
            status_filter = st.selectbox(
                "Delivery Status",
                options=[
                    "All Pending (Open/Hold/Dispatched)",
                    "All",
                    "Open",
                    "Dispatched",
                    "Delivered",
                    "On Hold",
                    "Reversed/Returned",
                ],
                index=0,
            )
        with f_col3:
            # Use engine.connect() for read-only SELECT queries
            with engine.connect() as conn:
                divs = pd.read_sql(
                    text(
                        "SELECT DISTINCT division FROM sales WHERE"
                        " source_system = 'shoper' ORDER BY division"
                    ),
                    conn,
                )
            division_list = ["All"] + divs["division"].tolist()
            selected_division = st.selectbox("Division", options=division_list)

        with f_col4:
            search_query = st.text_input(
                "Search Doc No / Prefix / Customer", value=""
            )

    # Safe date handling for incomplete user clicks
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_dt, end_dt = date_range
    elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
        start_dt = end_dt = date_range[0]
    else:
        start_dt = end_dt = date.today()

    # ---------------------------------------------------------
    # 2. Build Query Clauses (Type-Safe for integer doc_no)
    # ---------------------------------------------------------
    status_clause = ""
    if status_filter == "All Pending (Open/Hold/Dispatched)":
        status_clause = (
            "AND COALESCE(d.status, 'Open') IN ('Open', 'Dispatched', 'On"
            " Hold')"
        )
    elif status_filter != "All":
        status_clause = f"AND COALESCE(d.status, 'Open') = '{status_filter}'"

    division_clause = (
        f"AND s.division = '{selected_division}'"
        if selected_division != "All"
        else ""
    )
    search_clause = ""
    if search_query.strip():
        q = search_query.strip()
        search_clause = f"""
            AND (
                CAST(s.doc_no AS TEXT) ILIKE '%%{q}%%' 
                OR CAST(s.doc_prefix AS TEXT) ILIKE '%%{q}%%' 
                OR CONCAT(s.doc_prefix, '-', s.doc_no) ILIKE '%%{q}%%'
                OR CAST(s.customer_code AS TEXT) ILIKE '%%{q}%%'
            )
        """

    fetch_sql = f"""
    SELECT 
        s.division,
        s.doc_prefix,
        s.doc_no,
        CONCAT(s.doc_prefix, '-', s.doc_no) AS full_doc_no,
        s.sale_date,
        s.customer_code,
        SUM(s.qty * COALESCE(s.sign_multiplier, 1)) AS total_qty,
        SUM(s.net_value * COALESCE(s.sign_multiplier, 1)) AS total_val,
        COALESCE(d.status, 'Open') AS status,
        COALESCE(d.transporter, '') AS transporter,
        COALESCE(d.tracking_no, '') AS tracking_no,
        d.dispatch_date,
        d.delivery_date,
        COALESCE(d.remarks, '') AS remarks,
        d.updated_by,
        d.updated_at
    FROM sales s
    LEFT JOIN delivery_status d 
        ON s.division = d.division 
        AND s.doc_prefix = d.doc_prefix
        AND CAST(s.doc_no AS VARCHAR) = d.doc_no
    WHERE s.source_system = 'shoper'
      AND s.sale_date BETWEEN CAST(:start_dt AS DATE) AND CAST(:end_dt AS DATE)
      {division_clause}
      {status_clause}
      {search_clause}
    GROUP BY 
        s.division, s.doc_prefix, s.doc_no, s.sale_date, s.customer_code,
        d.status, d.transporter, d.tracking_no, d.dispatch_date, d.delivery_date, 
        d.remarks, d.updated_by, d.updated_at
    ORDER BY s.sale_date DESC, s.doc_no DESC;
    """

    with engine.connect() as conn:
        df = pd.read_sql(
            text(fetch_sql), conn, params={"start_dt": start_dt, "end_dt": end_dt}
        )

    if df.empty:
        st.info("No records found matching the active filters.")
        return

    # ---------------------------------------------------------
    # 3. KPI Ribbon
    # ---------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents Listed", len(df))
    c2.metric("Pending Dispatch (Open)", len(df[df["status"] == "Open"]))
    c3.metric("In Transit (Dispatched)", len(df[df["status"] == "Dispatched"]))
    c4.metric(
        "Completed Deliveries", len(df[df["status"] == "Delivered"])
    )

    st.markdown("---")
    st.caption(
        "💡 Edit status, transporter details, or dates directly in the table"
        " below, then click **Commit Delivery Updates**."
    )

    # ---------------------------------------------------------
    # 4. Interactive Data Editor
    # ---------------------------------------------------------
    disabled_cols = [
        "division",
        "doc_prefix",
        "doc_no",
        "full_doc_no",
        "sale_date",
        "customer_code",
        "total_qty",
        "total_val",
        "updated_by",
        "updated_at",
    ]

    edited_df = st.data_editor(
        df,
        key="delivery_editor",
        disabled=disabled_cols,
        hide_index=True,
        use_container_width=True,
        column_order=[
            "division",
            "full_doc_no",
            "sale_date",
            "customer_code",
            "total_qty",
            "total_val",
            "status",
            "transporter",
            "tracking_no",
            "dispatch_date",
            "delivery_date",
            "remarks",
            "updated_by",
            "updated_at",
        ],
        column_config={
            "division": st.column_config.TextColumn("Division", width="small"),
            "full_doc_no": st.column_config.TextColumn(
                "Document No", width="medium"
            ),
            "sale_date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            "customer_code": st.column_config.TextColumn("Customer"),
            "total_qty": st.column_config.NumberColumn("Qty", format="%d"),
            "total_val": st.column_config.NumberColumn(
                "Net Value", format="₹%.2f"
            ),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=[
                    "Open",
                    "Dispatched",
                    "Delivered",
                    "On Hold",
                    "Reversed/Returned",
                ],
                required=True,
            ),
            "transporter": st.column_config.TextColumn(
                "Transporter / Courier"
            ),
            "tracking_no": st.column_config.TextColumn("Docket / LR No"),
            "dispatch_date": st.column_config.DateColumn(
                "Dispatch Date", format="DD/MM/YYYY"
            ),
            "delivery_date": st.column_config.DateColumn(
                "Delivery Date", format="DD/MM/YYYY"
            ),
            "remarks": st.column_config.TextColumn("Remarks / Reason"),
            "updated_by": st.column_config.TextColumn("Last Updated By"),
            "updated_at": st.column_config.DatetimeColumn(
                "Last Updated", format="DD/MM/YY HH:mm"
            ),
        },
    )

    # ---------------------------------------------------------
    # 5. Commit Updates & Audit Trail (Transaction block)
    # ---------------------------------------------------------
    if st.button("💾 Commit Delivery Updates", type="primary"):
        diff_mask = (
            (df["status"] != edited_df["status"])
            | (df["transporter"] != edited_df["transporter"])
            | (df["tracking_no"] != edited_df["tracking_no"])
            | (df["dispatch_date"] != edited_df["dispatch_date"])
            | (df["delivery_date"] != edited_df["delivery_date"])
            | (df["remarks"] != edited_df["remarks"])
        )

        changed_rows = edited_df[diff_mask]

        if changed_rows.empty:
            st.info("No modifications detected to commit.")
            return

        upsert_status_sql = text("""
            INSERT INTO delivery_status (
                division, doc_prefix, doc_no, customer_code, status, 
                transporter, tracking_no, dispatch_date, delivery_date, 
                remarks, updated_by, updated_at
            )
            VALUES (
                :division, :doc_prefix, :doc_no, :customer_code, :status, 
                :transporter, :tracking_no, :dispatch_date, :delivery_date, 
                :remarks, :updated_by, CURRENT_TIMESTAMP
            )
            ON CONFLICT (division, doc_prefix, doc_no) DO UPDATE SET
                status = EXCLUDED.status,
                transporter = EXCLUDED.transporter,
                tracking_no = EXCLUDED.tracking_no,
                dispatch_date = EXCLUDED.dispatch_date,
                delivery_date = EXCLUDED.delivery_date,
                remarks = EXCLUDED.remarks,
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP;
        """)

        audit_sql = text("""
            INSERT INTO delivery_status_history (
                division, doc_prefix, doc_no, previous_status, new_status, 
                transporter, tracking_no, remarks, changed_by
            )
            VALUES (
                :division, :doc_prefix, :doc_no, :prev_status, :new_status, 
                :transporter, :tracking_no, :remarks, :changed_by
            );
        """)

        with engine.begin() as conn:
            for idx, row in changed_rows.iterrows():
                original_status = df.loc[idx, "status"]

                # 1. Update/Insert the delivery state
                conn.execute(
                    upsert_status_sql,
                    {
                        "division": row["division"],
                        "doc_prefix": row["doc_prefix"],
                        "doc_no": str(row["doc_no"]),
                        "customer_code": row["customer_code"],
                        "status": row["status"],
                        "transporter": (
                            row["transporter"] if row["transporter"] else None
                        ),
                        "tracking_no": (
                            row["tracking_no"] if row["tracking_no"] else None
                        ),
                        "dispatch_date": (
                            row["dispatch_date"]
                            if pd.notna(row["dispatch_date"])
                            else None
                        ),
                        "delivery_date": (
                            row["delivery_date"]
                            if pd.notna(row["delivery_date"])
                            else None
                        ),
                        "remarks": row["remarks"] if row["remarks"] else None,
                        "updated_by": current_user,
                    },
                )

                # 2. Append to audit log
                conn.execute(
                    audit_sql,
                    {
                        "division": row["division"],
                        "doc_prefix": row["doc_prefix"],
                        "doc_no": str(row["doc_no"]),
                        "prev_status": original_status,
                        "new_status": row["status"],
                        "transporter": (
                            row["transporter"] if row["transporter"] else None
                        ),
                        "tracking_no": (
                            row["tracking_no"] if row["tracking_no"] else None
                        ),
                        "remarks": row["remarks"] if row["remarks"] else None,
                        "changed_by": current_user,
                    },
                )

        st.success(
            f"Successfully updated delivery status for {len(changed_rows)}"
            " document(s)!"
        )
        st.rerun()


if __name__ == "__main__":
    show_delivery_dashboard()
