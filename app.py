"""
CRS Jira Dashboard — Team Workload & Client Portfolio
Streamlit app that reads the Jira CSV exports and provides interactive views.

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import platform
import os

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="CRS Jira Dashboard", layout="wide", page_icon="📊")

# Custom CSS for aligned metrics
st.markdown("""
<style>
[data-testid="stMetric"] {
    min-height: 120px;
}
[data-testid="stMetric"] p {
    margin-bottom: 0;
}
[data-testid="stMetricDeltaIcon-neutral"] {
    display: none;
}
</style>
""", unsafe_allow_html=True)

# Data source: local OneDrive sync or GitHub (for Streamlit Cloud deployment)
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/Sharecare/CRS_JIRA_REPO/main"

if platform.system() == "Windows":
    SHAREPOINT_DIR = os.path.join(os.path.expanduser("~"),
        "OneDrive - Sharecare, Inc", "Custom Reporting Analysts - Jira")
else:
    SHAREPOINT_DIR = os.path.expanduser(
        "~/Library/CloudStorage/OneDrive-Sharecare,Inc/Custom Reporting Analysts - Jira"
    )

# If app.py is in the SharePoint folder itself, use that directory
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "crs_jira_export.csv")):
    SHAREPOINT_DIR = os.path.dirname(os.path.abspath(__file__))

TASKS_CSV = os.path.join(SHAREPOINT_DIR, "crs_jira_export.csv")
EPICS_CSV = os.path.join(SHAREPOINT_DIR, "crs_jira_export_epics.csv")

# If local files not found, try repo data folder, then GitHub raw (Streamlit Cloud)
USE_GITHUB = False
if not os.path.exists(TASKS_CSV):
    # Try relative data folder (when deployed from repo)
    repo_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "crs_jira_export.csv")
    if os.path.exists(repo_data):
        TASKS_CSV = repo_data
        EPICS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "crs_jira_export_epics.csv")
    else:
        TASKS_CSV = f"{GITHUB_RAW_BASE}/projects/CRS/jira_dashboard/data/crs_jira_export.csv"
        EPICS_CSV = f"{GITHUB_RAW_BASE}/projects/CRS/jira_dashboard/data/crs_jira_export_epics.csv"
        USE_GITHUB = True


# ---------------------------------------------------------------------------
# Load Data
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_data():
    tasks = pd.read_csv(TASKS_CSV)
    epics = pd.read_csv(EPICS_CSV)

    # Parse dates
    tasks["created"] = pd.to_datetime(tasks["created"], errors="coerce", utc=True).dt.tz_localize(None)
    tasks["closed_date"] = pd.to_datetime(tasks["closed_date"], errors="coerce", utc=True).dt.tz_localize(None)

    # Turnaround time (days) — business days only (Mon-Fri)
    tasks["turnaround_days"] = tasks.apply(
        lambda row: len(pd.bdate_range(row["created"], row["closed_date"])) - 1
        if pd.notna(row["created"]) and pd.notna(row["closed_date"]) else None,
        axis=1
    )

    # Age (days since created, for open tasks)
    tasks["age_days"] = (pd.Timestamp.now() - tasks["created"]).dt.days

    # Clean up
    tasks["client"] = tasks["client"].fillna("Unknown")
    tasks["assignee"] = tasks["assignee"].fillna("Unassigned")
    tasks["task_type"] = tasks["task_type"].fillna("Other")
    tasks["status"] = tasks["status"].fillna("Unknown")
    tasks["frequency"] = tasks["frequency"].fillna("one-time")

    # Recurring vs Adhoc
    tasks["work_type"] = tasks["frequency"].apply(
        lambda x: "Adhoc" if x == "one-time" else "Recurring"
    )

    epics["created"] = pd.to_datetime(epics["created"], errors="coerce", utc=True).dt.tz_localize(None)
    epics["client"] = epics["client"].fillna("Unknown")
    epics["assignee"] = epics["assignee"].fillna("Unassigned")

    return tasks, epics


tasks, epics = load_data()


def clean_turnaround(series):
    """Remove outliers and invalid values from turnaround before computing stats."""
    s = series.dropna()
    s = s[s >= 0]  # Remove negative values (closed before created)
    if len(s) < 4:
        return s
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return s[(s >= max(lower, 0)) & (s <= upper)]

# ---------------------------------------------------------------------------
# Sidebar Filters
# ---------------------------------------------------------------------------
st.sidebar.title("🔍 Filters")

# Date range (first)
min_date = tasks["created"].min().date()
max_date = tasks["created"].max().date()
default_start = max((pd.Timestamp.now() - timedelta(days=365)).date(), min_date)
date_range = st.sidebar.date_input("Date Range", value=(default_start, max_date))

st.sidebar.divider()

# Assignee filter
all_assignees = sorted(tasks["assignee"].unique())
default_assignees = [a for a in all_assignees if any(name in a for name in ["Adam", "Brandon", "Dave", "Scott"])]
selected_assignees = st.sidebar.multiselect("Assignee", all_assignees, default=default_assignees)

# Status filter
all_statuses = sorted(tasks["status"].unique())
selected_statuses = st.sidebar.multiselect("Status", all_statuses, default=[])

# Frequency filter
all_frequencies = sorted(tasks["frequency"].unique())
selected_frequencies = st.sidebar.multiselect("Frequency", all_frequencies, default=[])

# Rush filter
rush_filter = st.sidebar.radio("Rush", ["All", "Rush Only", "Non-Rush"], horizontal=True)

# Apply filters
filtered = tasks.copy()
if selected_assignees:
    filtered = filtered[filtered["assignee"].isin(selected_assignees)]
if selected_statuses:
    filtered = filtered[filtered["status"].isin(selected_statuses)]
if selected_frequencies:
    filtered = filtered[filtered["frequency"].isin(selected_frequencies)]
if rush_filter == "Rush Only":
    filtered = filtered[filtered["labels"].str.contains("Rush", case=False, na=False)]
elif rush_filter == "Non-Rush":
    filtered = filtered[~filtered["labels"].str.contains("Rush", case=False, na=False)]
if len(date_range) == 2:
    filtered = filtered[
        (filtered["created"].dt.date >= date_range[0]) &
        (filtered["created"].dt.date <= date_range[1])
    ]

# Closed tasks always filtered by closed_date within range (independent of created filter)
if len(date_range) == 2:
    closed_in_range = tasks.copy()
    if selected_assignees:
        closed_in_range = closed_in_range[closed_in_range["assignee"].isin(selected_assignees)]
    if selected_statuses:
        closed_in_range = closed_in_range[closed_in_range["status"].isin(selected_statuses)]
    if selected_frequencies:
        closed_in_range = closed_in_range[closed_in_range["frequency"].isin(selected_frequencies)]
    if rush_filter == "Rush Only":
        closed_in_range = closed_in_range[closed_in_range["labels"].str.contains("Rush", case=False, na=False)]
    elif rush_filter == "Non-Rush":
        closed_in_range = closed_in_range[~closed_in_range["labels"].str.contains("Rush", case=False, na=False)]
    closed_in_range = closed_in_range[
        (closed_in_range["status"] == "Done") &
        (closed_in_range["closed_date"].dt.date >= date_range[0]) &
        (closed_in_range["closed_date"].dt.date <= date_range[1])
    ]
else:
    closed_in_range = filtered[filtered["status"] == "Done"]

# ---------------------------------------------------------------------------
# Tab Layout
# ---------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📋 Team Workload", "🏢 Client Portfolio", "⏱️ Time & Capacity"])

# ===========================================================================
# TAB 1: Team Workload Dashboard
# ===========================================================================
with tab1:
    st.header("Team Workload Dashboard")

    # KPI row
    open_tasks = filtered[~filtered["status"].isin(["Done", "Cancelled"])]
    closed_tasks = closed_in_range  # Always based on closed_date within range
    rush_tasks = filtered[filtered["labels"].str.contains("Rush", case=False, na=False)]

    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    # Calculations
    now_ts = pd.Timestamp.now()
    created_last_7 = filtered[filtered["created"] >= (now_ts - timedelta(days=7))]
    created_prev_7 = filtered[(filtered["created"] >= (now_ts - timedelta(days=14))) &
                              (filtered["created"] < (now_ts - timedelta(days=7)))]
    delta_created_7d = len(created_last_7) - len(created_prev_7)
    pct_created = ((delta_created_7d / max(len(created_prev_7), 1)) * 100)

    last_7 = closed_tasks[closed_tasks["closed_date"] >= (now_ts - timedelta(days=7))]
    prev_7 = closed_tasks[(closed_tasks["closed_date"] >= (now_ts - timedelta(days=14))) &
                          (closed_tasks["closed_date"] < (now_ts - timedelta(days=7)))]
    delta_7d = len(last_7) - len(prev_7)
    pct_closed = ((delta_7d / max(len(prev_7), 1)) * 100)

    rush_last_7 = rush_tasks[rush_tasks["created"] >= (now_ts - timedelta(days=7))]
    rush_prev_7 = rush_tasks[(rush_tasks["created"] >= (now_ts - timedelta(days=14))) &
                             (rush_tasks["created"] < (now_ts - timedelta(days=7)))]
    delta_rush_7d = len(rush_last_7) - len(rush_prev_7)
    pct_rush = ((delta_rush_7d / max(len(rush_prev_7), 1)) * 100)

    hours_last_7 = closed_tasks[closed_tasks["closed_date"] >= (now_ts - timedelta(days=7))]["estimated_completion_time"].sum() / 60
    hours_prev_7 = closed_tasks[(closed_tasks["closed_date"] >= (now_ts - timedelta(days=14))) &
                                (closed_tasks["closed_date"] < (now_ts - timedelta(days=7)))]["estimated_completion_time"].sum() / 60
    delta_hours_7d = hours_last_7 - hours_prev_7
    pct_hours = ((delta_hours_7d / max(hours_prev_7, 0.1)) * 100)

    total_hours = filtered["estimated_completion_time"].sum() / 60

    # Hrs/Day
    last_45_closed = closed_tasks[closed_tasks["closed_date"] >= (now_ts - timedelta(days=45))]
    biz_days_range = pd.bdate_range(start=now_ts - timedelta(days=45), end=now_ts)
    working_days = len(biz_days_range)
    if len(last_45_closed) > 0 and filtered["assignee"].nunique() > 0:
        total_closed_hours_45d = last_45_closed["estimated_completion_time"].sum() / 60
        # Exclude Scott from headcount — he's a manager, not a producing analyst
        active_assignees = last_45_closed["assignee"].unique()
        n_assignees_active = len([a for a in active_assignees if "Scott" not in str(a)])
        n_assignees_active = max(n_assignees_active, 1)
        hrs_per_day = total_closed_hours_45d / (working_days * n_assignees_active)
    else:
        hrs_per_day = 0

    # Total Tasks (created 7d comparison)
    total_last_7 = len(created_last_7)
    total_prev_7 = len(created_prev_7)
    delta_total = total_last_7 - total_prev_7
    pct_total = ((delta_total / max(total_prev_7, 1)) * 100)
    col1.metric("Total Tasks", f"{len(filtered):,}",
                delta=f"{delta_total:+d} ({total_last_7} vs {total_prev_7}) 7d")

    # Open (no footnote)
    col2.metric("Open", f"{len(open_tasks):,}")

    # Closed (more closed = good → normal)
    col3.metric("Closed", f"{len(closed_tasks):,}",
                delta=f"{delta_7d:+d} ({len(last_7)} vs {len(prev_7)}) 7d")

    # Avg Turnaround (no arrow)
    if len(closed_tasks) > 0:
        turnaround = clean_turnaround(closed_tasks["turnaround_days"])
        raw_count = closed_tasks["turnaround_days"].dropna().count()
        outliers_removed = raw_count - len(turnaround)
        mode_val = turnaround.mode().iloc[0] if len(turnaround.mode()) > 0 else 0
        col4.metric("Avg Turnaround", f"{turnaround.mean():.0f} days",
                    delta=f"Median: {turnaround.median():.0f}d | Mode: {mode_val:.0f}d", delta_color="off")
    else:
        col4.metric("Avg Turnaround", "N/A")

    # Rush (more rush = bad → negate so Streamlit colors correctly)
    delta_rush_display = len(rush_last_7) - len(rush_prev_7)
    col5.metric("Rush Tickets", f"{len(rush_tasks):,}",
                delta=f"{delta_rush_display:+d} ({len(rush_last_7)} vs {len(rush_prev_7)}) 7d",
                delta_color="inverse")

    # Est. Hours
    col6.metric("Est. Hours", f"{total_hours:,.1f}h",
                delta=f"{delta_hours_7d:+.0f}h ({hours_last_7:.0f}h vs {hours_prev_7:.0f}h) 7d")

    # Hrs/Day (no arrow)
    col7.metric("Hrs/Day", f"{hrs_per_day:.1f}h",
                delta=f"{total_closed_hours_45d:.0f}h ÷ {working_days}d ÷ {n_assignees_active} people" if len(last_45_closed) > 0 else "no data",
                delta_color="off")

    # Info descriptions
    with st.expander("ℹ️ Metric Definitions"):
        st.markdown("""
        - **Total Tasks** — All tasks matching the sidebar filters. Footnote shows tickets *created* last 7 days vs prior 7 days with % change (green = fewer created, red = more created).
        - **Open** — Tasks where status is not Done or Cancelled. No footnote.
        - **Closed** — Tasks where status = Done. Footnote shows tickets *closed* last 7 days vs prior 7 days with % change (green = closing more).
        - **Avg Turnaround** — Mean business days from Created to Closed Date, with outliers removed using IQR method (values outside Q1-1.5×IQR / Q3+1.5×IQR and negative values excluded). Subtext shows median and mode.
        - **Rush Tickets** — Tasks with the "Rush" label. Footnote shows rush tickets created last 7 days vs prior 7 days with % change (green = fewer rush, red = more rush).
        - **Est. Hours** — Sum of "Time Spent in Minutes" field converted to hours across all filtered tasks. Footnote shows estimated hours completed (closed) last 7 days vs prior 7 days.
        - **Hrs/Day** — Total closed hours in the last 45 calendar days ÷ business days (Mon-Fri) ÷ active assignees. Shows the formula breakdown: `hours ÷ days ÷ people`.
        """)

    st.divider()

    # ---------------------------------------------------------------------------
    # Monthly Ticket Flow
    # ---------------------------------------------------------------------------
    st.subheader("Monthly Ticket Flow")

    # Legend and explanation
    st.markdown("""
    **Net (dashed line):** positive (+) = backlog growing, negative (-) = closing faster than new work arrives.
    """)

    flow_grain_col, flow_filter_col = st.columns([1, 2])
    with flow_grain_col:
        flow_view = st.radio("View by", ["Month", "Week of Month", "Day of Week"], horizontal=True, key="flow_view")
    with flow_filter_col:
        flow_assignee = st.radio("Assignee", ["All", "Brandon", "Dave", "Adam", "Scott"], horizontal=True, key="flow_assignee")

    flow_data = filtered.copy()
    if flow_assignee != "All":
        flow_data = flow_data[flow_data["assignee"].str.contains(flow_assignee, case=False, na=False)]

    # Determine period grouping
    if flow_view == "Month":
        flow_data["period"] = flow_data["created"].dt.strftime("%Y-%m")
        closed_flow = flow_data[flow_data["closed_date"].notna()].copy()
        closed_flow["closed_period"] = closed_flow["closed_date"].dt.strftime("%Y-%m")
    elif flow_view == "Week of Month":
        flow_data["period"] = flow_data["created"].dt.day.apply(lambda d: f"Week {min((d-1)//7+1, 5)}")
        closed_flow = flow_data[flow_data["closed_date"].notna()].copy()
        closed_flow["closed_period"] = closed_flow["closed_date"].dt.day.apply(lambda d: f"Week {min((d-1)//7+1, 5)}")
    else:
        day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        flow_data["period"] = pd.Categorical(flow_data["created"].dt.strftime("%a"), categories=day_order, ordered=True)
        closed_flow = flow_data[flow_data["closed_date"].notna()].copy()
        closed_flow["closed_period"] = pd.Categorical(closed_flow["closed_date"].dt.strftime("%a"), categories=day_order, ordered=True)

    created_counts = flow_data.groupby("period").size().reset_index(name="Created")
    created_counts.columns = ["Period", "Created"]
    created_recurring = flow_data[flow_data["work_type"] == "Recurring"].groupby("period").size().reset_index(name="Created_Recurring")
    created_recurring.columns = ["Period", "Created_Recurring"]
    created_adhoc = flow_data[flow_data["work_type"] == "Adhoc"].groupby("period").size().reset_index(name="Created_Adhoc")
    created_adhoc.columns = ["Period", "Created_Adhoc"]
    closed_counts = closed_flow.groupby("closed_period").size().reset_index(name="Closed")
    closed_counts.columns = ["Period", "Closed"]
    closed_recurring = closed_flow[closed_flow["work_type"] == "Recurring"].groupby("closed_period").size().reset_index(name="Closed_Recurring")
    closed_recurring.columns = ["Period", "Closed_Recurring"]
    closed_adhoc = closed_flow[closed_flow["work_type"] == "Adhoc"].groupby("closed_period").size().reset_index(name="Closed_Adhoc")
    closed_adhoc.columns = ["Period", "Closed_Adhoc"]

    monthly = created_counts.merge(closed_counts, on="Period", how="outer")
    monthly = monthly.merge(created_recurring, on="Period", how="left")
    monthly = monthly.merge(created_adhoc, on="Period", how="left")
    monthly = monthly.merge(closed_recurring, on="Period", how="left")
    monthly = monthly.merge(closed_adhoc, on="Period", how="left").fillna(0).sort_values("Period")
    monthly["Net"] = monthly["Created"] - monthly["Closed"]

    # Single grouped bar chart: Created (stacked recurring/adhoc), Closed, Net as a line
    if flow_assignee != "All":
        fig = go.Figure()
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Created_Recurring"], name="Created (Recurring)",
                             marker_color="#1a5276", text=monthly["Created_Recurring"].astype(int),
                             textposition="inside", textfont=dict(size=9)))
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Created_Adhoc"], name="Created (Adhoc)",
                             marker_color="#c0392b", text=monthly["Created_Adhoc"].astype(int),
                             textposition="inside", textfont=dict(size=9)))
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Closed_Recurring"], name="Closed (Recurring)",
                             marker_color="#5dade2", text=monthly["Closed_Recurring"].astype(int),
                             textposition="inside", textfont=dict(size=9)))
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Closed_Adhoc"], name="Closed (Adhoc)",
                             marker_color="#f1948a", text=monthly["Closed_Adhoc"].astype(int),
                             textposition="inside", textfont=dict(size=9)))
        fig.add_trace(go.Scatter(x=monthly["Period"], y=monthly["Net"], name="Net",
                                 mode="lines+markers+text", line=dict(color="#e74c3c", width=2, dash="dash"),
                                 text=[f"{int(n):+d}" if abs(n) > 3 else "" for n in monthly["Net"]],
                                 textposition="top center", textfont=dict(size=10, color="#e74c3c")))
        fig.update_layout(barmode="stack", height=400, yaxis_title="Tickets",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02),
                          hovermode="x unified", margin=dict(t=40))
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Combined team chart first
        fig = go.Figure()
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Created_Recurring"], name="Created (Recurring)",
                             marker_color="#1a5276"))
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Created_Adhoc"], name="Created (Adhoc)",
                             marker_color="#c0392b"))
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Closed_Recurring"], name="Closed (Recurring)",
                             marker_color="#5dade2"))
        fig.add_trace(go.Bar(x=monthly["Period"], y=monthly["Closed_Adhoc"], name="Closed (Adhoc)",
                             marker_color="#f1948a"))
        fig.add_trace(go.Scatter(x=monthly["Period"], y=monthly["Net"], name="Net",
                                 mode="lines+markers+text", line=dict(color="#e74c3c", width=2, dash="dash"),
                                 text=[f"{int(n):+d}" if abs(n) > 3 else "" for n in monthly["Net"]],
                                 textposition="top center", textfont=dict(size=10, color="#e74c3c")))
        fig.update_layout(barmode="stack", height=500, yaxis_title="Tickets", title="All Team",
                          legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                          hovermode="x unified", margin=dict(t=60, b=160))
        fig.update_xaxes(tickangle=-45, tickfont=dict(size=9))
        st.plotly_chart(fig, use_container_width=True)

        # Small multiples below
        st.caption("By team member:")
        from plotly.subplots import make_subplots

        team = ["Brandon", "Dave", "Adam", "Scott"]
        assignees = [a for a in filtered["assignee"].unique() if any(name in a for name in team)]
        n_assignees = len(assignees)
        cols = 2
        rows = (n_assignees + cols - 1) // cols

        fig = make_subplots(rows=rows, cols=cols, subplot_titles=assignees,
                            shared_yaxes=False, vertical_spacing=0.15, horizontal_spacing=0.08)

        for idx, person in enumerate(assignees):
            r = idx // cols + 1
            c = idx % cols + 1
            person_data = flow_data[flow_data["assignee"] == person]
            person_closed = closed_flow[closed_flow["assignee"] == person] if "assignee" in closed_flow.columns else pd.DataFrame()

            p_recurring = person_data[person_data["work_type"] == "Recurring"].groupby("period").size().reset_index(name="Recurring")
            p_recurring.columns = ["Period", "Recurring"]
            p_adhoc = person_data[person_data["work_type"] == "Adhoc"].groupby("period").size().reset_index(name="Adhoc")
            p_adhoc.columns = ["Period", "Adhoc"]
            p_closed_recurring = person_closed[person_closed["work_type"] == "Recurring"].groupby("closed_period").size().reset_index(name="Closed_Recurring") if len(person_closed) > 0 else pd.DataFrame(columns=["Period", "Closed_Recurring"])
            p_closed_recurring.columns = ["Period", "Closed_Recurring"]
            p_closed_adhoc = person_closed[person_closed["work_type"] == "Adhoc"].groupby("closed_period").size().reset_index(name="Closed_Adhoc") if len(person_closed) > 0 else pd.DataFrame(columns=["Period", "Closed_Adhoc"])
            p_closed_adhoc.columns = ["Period", "Closed_Adhoc"]

            p_monthly = p_recurring.merge(p_adhoc, on="Period", how="outer")
            p_monthly = p_monthly.merge(p_closed_recurring, on="Period", how="outer")
            p_monthly = p_monthly.merge(p_closed_adhoc, on="Period", how="outer").fillna(0).sort_values("Period")

            fig.add_trace(go.Bar(x=p_monthly["Period"], y=p_monthly["Recurring"],
                                 name="Created (Recurring)", marker_color="#1a5276",
                                 showlegend=(idx == 0)), row=r, col=c)
            fig.add_trace(go.Bar(x=p_monthly["Period"], y=p_monthly["Adhoc"],
                                 name="Created (Adhoc)", marker_color="#c0392b",
                                 showlegend=(idx == 0)), row=r, col=c)
            fig.add_trace(go.Bar(x=p_monthly["Period"], y=p_monthly["Closed_Recurring"],
                                 name="Closed (Recurring)", marker_color="#5dade2",
                                 showlegend=(idx == 0)), row=r, col=c)
            fig.add_trace(go.Bar(x=p_monthly["Period"], y=p_monthly["Closed_Adhoc"],
                                 name="Closed (Adhoc)", marker_color="#f1948a",
                                 showlegend=(idx == 0)), row=r, col=c)

        fig.update_layout(height=400 * rows, barmode="stack",
                          legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="center", x=0.5),
                          margin=dict(t=80, b=140))
        fig.update_xaxes(tickangle=-45, tickfont=dict(size=9))
        fig.update_annotations(font_size=14)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ---------------------------------------------------------------------------
    # Period Comparison
    # ---------------------------------------------------------------------------
    st.subheader("Period Comparison")
    st.caption("Select a lookback period — automatically compares to the same length period prior")

    period_days = st.radio("Lookback period (days)", [7, 14, 30, 60, 90, 120, 180], index=2, horizontal=True, key="period_radio")

    now = pd.Timestamp.now()
    p1_start = now - timedelta(days=period_days)
    p2_start = now - timedelta(days=period_days * 2)
    p2_end = p1_start

    p1_tasks = filtered[(filtered["created"] >= p1_start)]
    p2_tasks = filtered[(filtered["created"] >= p2_start) & (filtered["created"] < p2_end)]
    p1_closed = closed_in_range[closed_in_range["closed_date"] >= p1_start]
    p2_closed = closed_in_range[(closed_in_range["closed_date"] >= p2_start) & (closed_in_range["closed_date"] < p2_end)]
    p1_open = p1_tasks[~p1_tasks["status"].isin(["Done", "Cancelled"])]
    p2_open = p2_tasks[~p2_tasks["status"].isin(["Done", "Cancelled"])]
    p1_rush = p1_tasks[p1_tasks["labels"].str.contains("Rush", case=False, na=False)]
    p2_rush = p2_tasks[p2_tasks["labels"].str.contains("Rush", case=False, na=False)]

    st.markdown(f"**Last {period_days} days** vs **prior {period_days} days**")

    pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns(7)

    pc1.metric("Created", f"{len(p1_tasks):,}",
               delta=f"{len(p1_tasks) - len(p2_tasks):+d} ({len(p1_tasks)} vs {len(p2_tasks)})", delta_color="inverse")
    pc2.metric("Open", f"{len(p1_open):,}",
               delta=f"{len(p1_open) - len(p2_open):+d} ({len(p1_open)} vs {len(p2_open)})", delta_color="inverse")
    pc3.metric("Closed", f"{len(p1_closed):,}",
               delta=f"{len(p1_closed) - len(p2_closed):+d} ({len(p1_closed)} vs {len(p2_closed)})")

    p1_avg = clean_turnaround(p1_closed["turnaround_days"]).mean() if len(p1_closed) > 0 else 0
    p2_avg = clean_turnaround(p2_closed["turnaround_days"]).mean() if len(p2_closed) > 0 else 0
    pc4.metric("Avg Turnaround", f"{p1_avg:.0f}d",
               delta=f"{p1_avg - p2_avg:+.0f}d ({p1_avg:.0f}d vs {p2_avg:.0f}d)", delta_color="inverse")

    pc5.metric("Rush", f"{len(p1_rush):,}",
               delta=f"{len(p1_rush) - len(p2_rush):+d} ({len(p1_rush)} vs {len(p2_rush)})", delta_color="inverse")

    p1_hours = p1_closed["estimated_completion_time"].sum() / 60
    p2_hours = p2_closed["estimated_completion_time"].sum() / 60
    pc6.metric("Est. Hours", f"{p1_hours:,.1f}h",
               delta=f"{p1_hours - p2_hours:+.1f}h ({p1_hours:.0f}h vs {p2_hours:.0f}h)")

    # Hrs/Day for period comparison
    p1_biz_days = len(pd.bdate_range(start=p1_start, end=now))
    p2_biz_days = len(pd.bdate_range(start=p2_start, end=p2_end))
    p1_assignees = len([a for a in p1_closed["assignee"].unique() if "Scott" not in str(a)]) if len(p1_closed) > 0 else 1
    p2_assignees = len([a for a in p2_closed["assignee"].unique() if "Scott" not in str(a)]) if len(p2_closed) > 0 else 1
    p1_hrs_day = p1_hours / (max(p1_biz_days, 1) * max(p1_assignees, 1))
    p2_hrs_day = p2_hours / (max(p2_biz_days, 1) * max(p2_assignees, 1))
    pc7.metric("Hrs/Day", f"{p1_hrs_day:.1f}h",
               delta=f"{p1_hrs_day - p2_hrs_day:+.1f}h ({p1_hrs_day:.1f}h vs {p2_hrs_day:.1f}h)")

    st.divider()

    # ---------------------------------------------------------------------------
    # Rush vs Non-Rush | Recurring vs Adhoc (side by side)
    # ---------------------------------------------------------------------------
    comp_left, comp_right = st.columns(2)

    with comp_left:
        st.subheader("Rush vs Non-Rush")

        rush_all = filtered[filtered["labels"].str.contains("Rush", case=False, na=False)]
        non_rush_all = filtered[~filtered["labels"].str.contains("Rush", case=False, na=False)]
        rush_closed = closed_in_range[closed_in_range["labels"].str.contains("Rush", case=False, na=False)]
        non_rush_closed = closed_in_range[~closed_in_range["labels"].str.contains("Rush", case=False, na=False)]

        total_rush = len(rush_all)
        total_non = len(non_rush_all)
        pct_rush = total_rush / max(total_rush + total_non, 1) * 100

        rush_avg_turn = clean_turnaround(rush_closed["turnaround_days"]).mean() if len(rush_closed) > 0 else 0
        non_rush_avg_turn = clean_turnaround(non_rush_closed["turnaround_days"]).mean() if len(non_rush_closed) > 0 else 0
        rush_hours = rush_all["estimated_completion_time"].sum() / 60
        non_rush_hours = non_rush_all["estimated_completion_time"].sum() / 60
        rush_open = len(rush_all[~rush_all["status"].isin(["Done", "Cancelled"])])
        non_rush_open = len(non_rush_all[~non_rush_all["status"].isin(["Done", "Cancelled"])])

        comparison_data = {
            "Metric": ["Total Tasks", "Open", "Closed", "Avg Turnaround (days)", "Est. Hours"],
            "Rush": [total_rush, rush_open, len(rush_closed), f"{rush_avg_turn:.0f}", f"{rush_hours:.1f}"],
            "Non-Rush": [total_non, non_rush_open, len(non_rush_closed), f"{non_rush_avg_turn:.0f}", f"{non_rush_hours:.1f}"],
            "% Rush": [
                f"{pct_rush:.1f}%",
                f"{rush_open / max(rush_open + non_rush_open, 1) * 100:.1f}%",
                f"{len(rush_closed) / max(len(rush_closed) + len(non_rush_closed), 1) * 100:.1f}%",
                "—",
                f"{rush_hours / max(rush_hours + non_rush_hours, 1) * 100:.1f}%",
            ],
        }
        st.dataframe(pd.DataFrame(comparison_data), use_container_width=True, hide_index=True)

    with comp_right:
        st.subheader("Recurring vs Adhoc")

        recurring_all = filtered[filtered["work_type"] == "Recurring"]
        adhoc_all = filtered[filtered["work_type"] == "Adhoc"]
        recurring_closed = closed_in_range[closed_in_range["work_type"] == "Recurring"]
        adhoc_closed = closed_in_range[closed_in_range["work_type"] == "Adhoc"]

        total_recurring = len(recurring_all)
        total_adhoc = len(adhoc_all)
        pct_recurring = total_recurring / max(total_recurring + total_adhoc, 1) * 100

        recurring_avg_turn = clean_turnaround(recurring_closed["turnaround_days"]).mean() if len(recurring_closed) > 0 else 0
        adhoc_avg_turn = clean_turnaround(adhoc_closed["turnaround_days"]).mean() if len(adhoc_closed) > 0 else 0
        recurring_hours = recurring_all["estimated_completion_time"].sum() / 60
        adhoc_hours = adhoc_all["estimated_completion_time"].sum() / 60
        recurring_open = len(recurring_all[~recurring_all["status"].isin(["Done", "Cancelled"])])
        adhoc_open = len(adhoc_all[~adhoc_all["status"].isin(["Done", "Cancelled"])])

        freq_comparison_data = {
            "Metric": ["Total Tasks", "Open", "Closed", "Avg Turnaround (days)", "Est. Hours"],
            "Recurring": [total_recurring, recurring_open, len(recurring_closed), f"{recurring_avg_turn:.0f}", f"{recurring_hours:.1f}"],
            "Adhoc": [total_adhoc, adhoc_open, len(adhoc_closed), f"{adhoc_avg_turn:.0f}", f"{adhoc_hours:.1f}"],
            "% Recurring": [
                f"{pct_recurring:.1f}%",
                f"{recurring_open / max(recurring_open + adhoc_open, 1) * 100:.1f}%",
                f"{len(recurring_closed) / max(len(recurring_closed) + len(adhoc_closed), 1) * 100:.1f}%",
                "—",
                f"{recurring_hours / max(recurring_hours + adhoc_hours, 1) * 100:.1f}%",
            ],
        }
        st.dataframe(pd.DataFrame(freq_comparison_data), use_container_width=True, hide_index=True)

    st.divider()

    # ---------------------------------------------------------------------------
    # Team Performance by Assignee
    # ---------------------------------------------------------------------------
    st.subheader("Team Performance by Assignee")

    # Build assignee summary table
    assignee_open = filtered.groupby("assignee").agg(
        total=("key", "count"),
        open_count=("status", lambda x: (~x.isin(["Done", "Cancelled"])).sum()),
        recurring_count=("work_type", lambda x: (x == "Recurring").sum()),
        adhoc_count=("work_type", lambda x: (x == "Adhoc").sum()),
        rush_count=("labels", lambda x: x.str.contains("Rush", case=False, na=False).sum()),
        est_hours=("estimated_completion_time", lambda x: x.sum() / 60),
        avg_turnaround=("turnaround_days", lambda x: clean_turnaround(x).mean()),
    ).reset_index()
    assignee_closed_counts = closed_in_range.groupby("assignee").agg(
        closed_count=("key", "count"),
    ).reset_index()
    assignee_summary = assignee_open.merge(assignee_closed_counts, on="assignee", how="left")
    assignee_summary["closed_count"] = assignee_summary["closed_count"].fillna(0).astype(int)
    assignee_summary["completion_rate"] = (assignee_summary["closed_count"] / assignee_summary["total"] * 100).round(1)
    assignee_summary["avg_turnaround"] = assignee_summary["avg_turnaround"].round(1)
    assignee_summary["est_hours"] = assignee_summary["est_hours"].round(1)
    assignee_summary = assignee_summary.sort_values("total", ascending=False)

    # Scorecard table
    st.dataframe(
        assignee_summary.rename(columns={
            "assignee": "Assignee", "total": "Total", "open_count": "Open",
            "closed_count": "Closed", "recurring_count": "Recurring", "adhoc_count": "Adhoc",
            "rush_count": "Rush", "est_hours": "Est. Hours", "avg_turnaround": "Avg Turn (d)",
            "completion_rate": "% Complete"
        }),
        use_container_width=True, hide_index=True
    )

    # Charts
    st.divider()

    # ---------------------------------------------------------------------------
    # Ticket Drill-Down
    # ---------------------------------------------------------------------------
    st.subheader("Ticket Drill-Down")

    drill_col1, drill_col2, drill_col3 = st.columns(3)
    with drill_col1:
        drill_status = st.selectbox("Status", ["All", "Open", "Closed"] + sorted(filtered["status"].unique().tolist()), key="drill_status")
    with drill_col2:
        drill_assignee = st.selectbox("Assignee", ["All"] + sorted(filtered["assignee"].unique().tolist()), key="drill_assignee")
    with drill_col3:
        drill_client = st.selectbox("Client", ["All"] + sorted(filtered["client"].unique().tolist()), key="drill_client")

    drill_col4, drill_col5 = st.columns(2)
    with drill_col4:
        drill_type = st.selectbox("Task Type", ["All"] + sorted(filtered["task_type"].unique().tolist()), key="drill_type")
    with drill_col5:
        drill_work = st.selectbox("Work Type", ["All", "Recurring", "Adhoc"], key="drill_work")

    drill_df = filtered.copy()
    if drill_status == "Open":
        drill_df = drill_df[~drill_df["status"].isin(["Done", "Cancelled"])]
    elif drill_status == "Closed":
        drill_df = drill_df[drill_df["status"] == "Done"]
    elif drill_status != "All":
        drill_df = drill_df[drill_df["status"] == drill_status]
    if drill_assignee != "All":
        drill_df = drill_df[drill_df["assignee"] == drill_assignee]
    if drill_client != "All":
        drill_df = drill_df[drill_df["client"] == drill_client]
    if drill_type != "All":
        drill_df = drill_df[drill_df["task_type"] == drill_type]
    if drill_work != "All":
        drill_df = drill_df[drill_df["work_type"] == drill_work]

    st.caption(f"Showing {len(drill_df)} tickets")

    # Format the dataframe with Jira links
    display_df = drill_df[["key", "summary", "status", "assignee", "client",
                           "task_type", "frequency", "estimated_completion_time",
                           "created", "closed_date", "turnaround_days"]].copy()
    display_df["created"] = display_df["created"].dt.strftime("%Y-%m-%d")
    display_df["closed_date"] = display_df["closed_date"].dt.strftime("%Y-%m-%d")
    display_df = display_df.rename(columns={
        "key": "Key",
        "summary": "Summary",
        "status": "Status",
        "assignee": "Assignee",
        "client": "Client",
        "task_type": "Type",
        "frequency": "Frequency",
        "estimated_completion_time": "Est. Min",
        "created": "Created",
        "closed_date": "Closed",
        "turnaround_days": "Days to Close",
    })
    display_df = display_df.sort_values("Created", ascending=False).reset_index(drop=True)

    # Make Key a clickable Jira link
    JIRA_BASE = "https://arnoldmedia.jira.com/browse/"
    display_df["Key"] = display_df["Key"].apply(lambda x: f"{JIRA_BASE}{x}")

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Key": st.column_config.LinkColumn("Key", display_text=r"(CRS-\d+)"),
        }
    )


# ===========================================================================
# TAB 2: Client Portfolio View
# ===========================================================================
with tab2:
    st.header("Client Portfolio View")

    # KPI row
    col1, col2, col3 = st.columns(3)
    col1.metric("Unique Clients", filtered["client"].nunique())
    col1.caption("ℹ️ Distinct client values in filtered tasks")
    col2.metric("Active Epics", len(epics[epics["client"].isin(filtered["client"].unique())]))
    col2.caption("ℹ️ Epics whose client appears in filtered tasks")
    col3.metric("Avg Tasks/Client", f"{len(filtered) / max(filtered['client'].nunique(), 1):.1f}")
    col3.caption("ℹ️ Total filtered tasks ÷ unique clients")

    st.divider()

    # Tasks by client
    st.subheader("Tasks by Client")
    # Open tasks from filtered (by created date), closed tasks from closed_in_range (by closed date)
    client_open = filtered.groupby("client").agg(
        total_tasks=("key", "count"),
        open_tasks=("status", lambda x: (x.isin(["Backlog", "In Progress", "To Do"])).sum()),
        avg_turnaround=("turnaround_days", lambda x: clean_turnaround(x).mean()),
    ).reset_index()
    client_closed = closed_in_range.groupby("client").agg(
        closed_tasks=("key", "count"),
    ).reset_index()
    client_summary = client_open.merge(client_closed, on="client", how="left")
    client_summary["closed_tasks"] = client_summary["closed_tasks"].fillna(0).astype(int)
    client_summary["completion_rate"] = (
        client_summary["closed_tasks"] / client_summary["total_tasks"] * 100
    ).round(1)
    client_summary["avg_turnaround"] = client_summary["avg_turnaround"].round(1)
    client_summary = client_summary.sort_values("total_tasks", ascending=False)

    st.dataframe(client_summary, use_container_width=True, hide_index=True)

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Top 15 Clients by Task Volume")
        top_clients = client_summary.head(15)
        fig = px.bar(top_clients, x="client", y="total_tasks", color="completion_rate",
                     color_continuous_scale="RdYlGn", height=400)
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Completion Rate by Client")
        fig = px.bar(top_clients.sort_values("completion_rate"),
                     x="completion_rate", y="client", orientation="h",
                     color="completion_rate", color_continuous_scale="RdYlGn",
                     height=400)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Client drill-down
    st.subheader("Client Drill-Down")
    selected_client = st.selectbox("Select a client", sorted(filtered["client"].unique()))
    client_tasks = filtered[filtered["client"] == selected_client].sort_values("created", ascending=False)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Tasks", len(client_tasks))
    col1.caption("ℹ️ All tasks for this client")
    col2.metric("Open", len(client_tasks[~client_tasks["status"].isin(["Done", "Cancelled"])]))
    col2.caption("ℹ️ Not Done or Cancelled")
    col3.metric("Avg Turnaround",
                f"{clean_turnaround(client_tasks['turnaround_days']).mean():.0f}d" if client_tasks["turnaround_days"].notna().any() else "N/A")
    col3.caption("ℹ️ Mean days Created → Closed for this client")

    st.dataframe(
        client_tasks[["key", "summary", "status", "assignee", "task_type", "created", "closed_date", "frequency"]],
        use_container_width=True, hide_index=True
    )


# ===========================================================================
# TAB 3: Time & Capacity (Recurring vs Adhoc)
# ===========================================================================
with tab3:
    st.header("Time & Capacity — Recurring vs Adhoc")

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    recurring = filtered[filtered["work_type"] == "Recurring"]
    adhoc = filtered[filtered["work_type"] == "Adhoc"]
    total_est_mins = filtered["estimated_completion_time"].sum()

    col1.metric("Recurring Tasks", len(recurring))
    col1.caption("ℹ️ Frequency ≠ one-time (weekly, monthly, etc.)")
    col2.metric("Adhoc Tasks", len(adhoc))
    col2.caption("ℹ️ Frequency = one-time")
    col3.metric("Total Est. Minutes", f"{total_est_mins:,.0f}")
    col3.caption("ℹ️ Sum of 'Time Spent in Minutes' field")
    col4.metric("Total Est. Hours", f"{total_est_mins / 60:,.1f}")
    col4.caption("ℹ️ Total minutes ÷ 60")

    st.divider()

    # Per-member breakdown
    st.subheader("Estimated Time per Team Member (minutes)")
    member_time = filtered.groupby(["assignee", "work_type"]).agg(
        task_count=("key", "count"),
        total_minutes=("estimated_completion_time", "sum"),
    ).reset_index()

    fig = px.bar(member_time, x="assignee", y="total_minutes", color="work_type",
                 barmode="group", height=450, text="total_minutes",
                 color_discrete_map={"Recurring": "#3498db", "Adhoc": "#e74c3c"})
    fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
    fig.update_layout(xaxis_tickangle=-45, yaxis_title="Minutes")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Detailed table per member
    st.subheader("Member Summary")
    member_summary = filtered.groupby(["assignee", "work_type"]).agg(
        tasks=("key", "count"),
        total_minutes=("estimated_completion_time", "sum"),
        avg_minutes=("estimated_completion_time", "mean"),
    ).reset_index()
    member_summary["total_hours"] = (member_summary["total_minutes"] / 60).round(1)
    member_summary["avg_minutes"] = member_summary["avg_minutes"].round(1)
    member_summary = member_summary.sort_values(["assignee", "work_type"])

    st.dataframe(member_summary, use_container_width=True, hide_index=True)

    st.divider()

    # Frequency breakdown
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Tasks by Frequency")
        freq_counts = filtered["frequency"].value_counts().reset_index()
        freq_counts.columns = ["frequency", "count"]
        fig = px.bar(freq_counts, x="frequency", y="count", color="frequency", height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Est. Minutes by Frequency")
        freq_time = filtered.groupby("frequency")["estimated_completion_time"].sum().reset_index()
        freq_time.columns = ["frequency", "total_minutes"]
        freq_time = freq_time.sort_values("total_minutes", ascending=False)
        fig = px.bar(freq_time, x="frequency", y="total_minutes", color="frequency", height=350)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Weekly capacity view
    st.subheader("Weekly Recurring Load per Member")
    st.caption("Estimated minutes per week based on frequency cadence")

    # Convert frequency to weekly multiplier
    freq_to_weekly = {
        "daily": 5, "weekly": 1, "biweekly": 0.5,
        "monthly": 0.25, "quarterly": 0.083,
        "semiannual": 0.038, "annual": 0.019, "one-time": 0
    }
    recurring_load = recurring.copy()
    recurring_load["weekly_multiplier"] = recurring_load["frequency"].map(freq_to_weekly).fillna(0)
    recurring_load["weekly_minutes"] = recurring_load["estimated_completion_time"] * recurring_load["weekly_multiplier"]

    weekly_by_member = recurring_load.groupby("assignee")["weekly_minutes"].sum().reset_index()
    weekly_by_member["weekly_hours"] = (weekly_by_member["weekly_minutes"] / 60).round(1)
    weekly_by_member = weekly_by_member.sort_values("weekly_hours", ascending=False)

    fig = px.bar(weekly_by_member, x="assignee", y="weekly_hours", height=400,
                 text="weekly_hours", color="weekly_hours",
                 color_continuous_scale="OrRd")
    fig.update_traces(texttemplate="%{text:.1f}h", textposition="outside")
    fig.update_layout(xaxis_tickangle=-45, yaxis_title="Hours/Week (Recurring)")
    fig.add_hline(y=40, line_dash="dash", line_color="red",
                  annotation_text="40h/week", annotation_position="top right")
    st.plotly_chart(fig, use_container_width=True)


    st.divider()

    # ---------------------------------------------------------------------------
    # Trends: Tickets closed per member over time
    # ---------------------------------------------------------------------------
    st.subheader("Tickets Closed per Member (Weekly Trend)")
    closed_with_date = closed_in_range[closed_in_range["closed_date"].notna()].copy()
    if len(closed_with_date) > 0:
        closed_with_date["closed_week"] = closed_with_date["closed_date"].dt.to_period("W").dt.start_time
        weekly_closed = closed_with_date.groupby(["assignee", "closed_week"]).agg(
            tickets_closed=("key", "count"),
            total_minutes_closed=("estimated_completion_time", "sum"),
        ).reset_index()

        fig = px.line(weekly_closed, x="closed_week", y="tickets_closed", color="assignee",
                      height=400, markers=True)
        fig.update_layout(xaxis_title="Week", yaxis_title="Tickets Closed")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Estimated Minutes Completed per Member (Weekly Trend)")
        fig = px.line(weekly_closed, x="closed_week", y="total_minutes_closed", color="assignee",
                      height=400, markers=True)
        fig.update_layout(xaxis_title="Week", yaxis_title="Minutes Completed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No closed tasks in current filter.")

    st.divider()

    # ---------------------------------------------------------------------------
    # Member Capacity Snapshot
    # ---------------------------------------------------------------------------
    st.subheader("Member Capacity Snapshot")
    st.caption("Current open workload per team member with recurring/adhoc split and estimated time")

    open_filtered = filtered[~filtered["status"].isin(["Done", "Cancelled"])].copy()

    if len(open_filtered) > 0:
        capacity = open_filtered.groupby("assignee").agg(
            open_tasks=("key", "count"),
            recurring_open=("work_type", lambda x: (x == "Recurring").sum()),
            adhoc_open=("work_type", lambda x: (x == "Adhoc").sum()),
            total_open_minutes=("estimated_completion_time", "sum"),
        ).reset_index()
        capacity["total_open_hours"] = (capacity["total_open_minutes"] / 60).round(1)
        capacity["pct_recurring"] = (capacity["recurring_open"] / capacity["open_tasks"] * 100).round(1)

        # Add weekly recurring load
        recurring_open = open_filtered[open_filtered["work_type"] == "Recurring"].copy()
        recurring_open["weekly_multiplier"] = recurring_open["frequency"].map(freq_to_weekly).fillna(0)
        recurring_open["weekly_minutes"] = recurring_open["estimated_completion_time"] * recurring_open["weekly_multiplier"]
        weekly_load = recurring_open.groupby("assignee")["weekly_minutes"].sum().reset_index()
        weekly_load["recurring_hours_per_week"] = (weekly_load["weekly_minutes"] / 60).round(1)

        capacity = capacity.merge(weekly_load[["assignee", "recurring_hours_per_week"]], on="assignee", how="left")
        capacity["recurring_hours_per_week"] = capacity["recurring_hours_per_week"].fillna(0)
        capacity = capacity.sort_values("total_open_hours", ascending=False)

        # Display table
        st.dataframe(
            capacity[["assignee", "open_tasks", "recurring_open", "adhoc_open",
                      "total_open_hours", "recurring_hours_per_week", "pct_recurring"]].rename(columns={
                "assignee": "Team Member",
                "open_tasks": "Open Tasks",
                "recurring_open": "Recurring",
                "adhoc_open": "Adhoc",
                "total_open_hours": "Total Open (hrs)",
                "recurring_hours_per_week": "Recurring hrs/wk",
                "pct_recurring": "% Recurring",
            }),
            use_container_width=True, hide_index=True
        )

        st.divider()

        # Capacity bar chart
        st.subheader("Open Workload by Member")
        cap_melted = capacity.melt(
            id_vars=["assignee"],
            value_vars=["recurring_open", "adhoc_open"],
            var_name="type", value_name="count"
        )
        cap_melted["type"] = cap_melted["type"].map({"recurring_open": "Recurring", "adhoc_open": "Adhoc"})

        fig = px.bar(cap_melted, x="assignee", y="count", color="type",
                     barmode="stack", height=400,
                     color_discrete_map={"Recurring": "#3498db", "Adhoc": "#e74c3c"})
        fig.update_layout(xaxis_tickangle=-45, yaxis_title="Open Tasks")
        st.plotly_chart(fig, use_container_width=True)

        # Hours bubble chart
        st.subheader("Capacity Overview (Bubble = Total Open Hours)")
        fig = px.scatter(capacity, x="recurring_hours_per_week", y="adhoc_open",
                         size="total_open_hours", color="assignee",
                         hover_name="assignee", height=450,
                         labels={
                             "recurring_hours_per_week": "Recurring Hours/Week",
                             "adhoc_open": "Adhoc Open Tasks",
                             "total_open_hours": "Total Open Hours"
                         })
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No open tasks in current filter.")
