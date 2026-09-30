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
    for dcol in ["recurring_start_date", "recurring_end_date"]:
        if dcol in epics.columns:
            epics[dcol] = pd.to_datetime(epics[dcol], errors="coerce", utc=True).dt.tz_localize(None)
    epics["client"] = epics["client"].fillna("Unknown")
    epics["assignee"] = epics["assignee"].fillna("Unassigned")
    epics["task_type"] = epics["task_type"].fillna("Other") if "task_type" in epics.columns else "Other"
    epics["frequency"] = epics["frequency"].fillna("one-time") if "frequency" in epics.columns else "one-time"

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
# Team Goals / KPI Targets  (seeded defaults — edit these values to match team commitments)
# ---------------------------------------------------------------------------
# These targets turn raw numbers into "compared to what?" insights. Every KPI on the
# Client Portfolio and Recurring Operations tabs is scored against one of these.
GOALS = {
    # Producing analysts only (Scott is a manager and is excluded from capacity math)
    "producing_analysts": ["Adam", "Brandon", "Dave"],
    "hours_per_week_per_person": 40,          # nominal weekly capacity per analyst

    # Throughput / flow
    "turnaround_days_target": 5,              # close within N business days (green if <=)
    "turnaround_days_warn": 8,                # yellow up to here, red beyond
    "net_backlog_target": 0,                  # created - closed per period; <=0 is healthy
    "completion_rate_target": 90,            # % of tasks closed (green if >=)
    "completion_rate_warn": 75,

    # Intake mix
    "rush_ratio_target_pct": 15,             # rush should be <= this % of intake
    "rush_ratio_warn_pct": 25,

    # Capacity allocation — the recurring "keep-the-lights-on" vs new-development story
    "recurring_hours_pct_target": 70,        # recurring should stay <= this % of total hours
    "recurring_hours_pct_warn": 85,
    "utilization_target_pct": 85,            # recurring load as % of capacity; green if <=
    "utilization_warn_pct": 100,
}


def status_color(value, target, warn=None, higher_is_better=False):
    """Return ('🟢'|'🟡'|'🔴', hex_color) scoring a value against a target.

    higher_is_better=False: lower is good (turnaround, rush%, utilization).
    higher_is_better=True:  higher is good (completion rate, throughput ratio).
    """
    green, yellow, red = "#2ecc71", "#f1c40f", "#e74c3c"
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "⚪", "#95a5a6"
    if higher_is_better:
        if value >= target:
            return "🟢", green
        if warn is not None and value >= warn:
            return "🟡", yellow
        return "🔴", red
    else:
        if value <= target:
            return "🟢", green
        if warn is not None and value <= warn:
            return "🟡", yellow
        return "🔴", red


def goal_gauge(value, target, title, warn=None, max_val=None, higher_is_better=False, suffix=""):
    """Build a Plotly gauge with a target threshold line and green/yellow/red zones."""
    badge, color = status_color(value, target, warn, higher_is_better)
    if max_val is None:
        max_val = max(value, target, warn or 0) * 1.4 or 1
    # Build the colored steps depending on direction
    if higher_is_better:
        lo = warn if warn is not None else target
        steps = [
            {"range": [0, lo], "color": "#fdecea"},
            {"range": [lo, target], "color": "#fef9e7"},
            {"range": [target, max_val], "color": "#eafaf1"},
        ]
    else:
        hi = warn if warn is not None else target
        steps = [
            {"range": [0, target], "color": "#eafaf1"},
            {"range": [target, hi], "color": "#fef9e7"},
            {"range": [hi, max_val], "color": "#fdecea"},
        ]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": suffix, "font": {"size": 26}},
        title={"text": f"{badge} {title}", "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, max_val]},
            "bar": {"color": color},
            "steps": steps,
            "threshold": {"line": {"color": "#2c3e50", "width": 3}, "thickness": 0.85, "value": target},
        },
    ))
    fig.update_layout(height=230, margin=dict(t=50, b=10, l=20, r=20))
    return fig


def kpi_vs_goal(label, value, target, unit="", higher_is_better=False, warn=None, help_text=""):
    """Render a st.metric styled as value-vs-goal with a status badge and delta-to-goal."""
    badge, _ = status_color(value, target, warn, higher_is_better)
    if isinstance(value, float):
        val_str = f"{value:,.1f}{unit}"
        delta_val = value - target
        delta_str = f"{delta_val:+,.1f}{unit} vs goal {target:g}{unit}"
    else:
        val_str = f"{value:,}{unit}"
        delta_str = f"{value - target:+,}{unit} vs goal {target:g}{unit}"
    # For "lower is better" metrics, invert delta color so under-goal shows green
    delta_color = "normal" if higher_is_better else "inverse"
    st.metric(f"{badge} {label}", val_str, delta=delta_str, delta_color=delta_color,
              help=help_text or None)


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
tab1, tab2, tab3 = st.tabs(["📋 Team Workload", "🏢 Client Portfolio", "🔁 Recurring Operations"])

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
    st.caption("Where the team's effort lands across clients — and which clients are on- vs off-track against service goals.")

    # -----------------------------------------------------------------------
    # Build the client scorecard (used by KPIs, charts, and the table)
    # -----------------------------------------------------------------------
    client_open = filtered.groupby("client").agg(
        total_tasks=("key", "count"),
        open_tasks=("status", lambda x: (~x.isin(["Done", "Cancelled"])).sum()),
        rush_tasks=("labels", lambda x: x.str.contains("Rush", case=False, na=False).sum()),
        recurring_tasks=("work_type", lambda x: (x == "Recurring").sum()),
        est_minutes=("estimated_completion_time", "sum"),
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
    client_summary["est_hours"] = (client_summary["est_minutes"] / 60).round(1)
    client_summary["avg_turnaround"] = client_summary["avg_turnaround"].round(1)
    client_summary["rush_pct"] = (client_summary["rush_tasks"] / client_summary["total_tasks"] * 100).round(1)

    # Health score: on-track if turnaround <= target AND completion >= target
    def _client_health(row):
        t_ok = pd.isna(row["avg_turnaround"]) or row["avg_turnaround"] <= GOALS["turnaround_days_warn"]
        c_ok = row["completion_rate"] >= GOALS["completion_rate_warn"]
        t_good = pd.isna(row["avg_turnaround"]) or row["avg_turnaround"] <= GOALS["turnaround_days_target"]
        c_good = row["completion_rate"] >= GOALS["completion_rate_target"]
        if t_good and c_good:
            return "🟢 On-track"
        if t_ok and c_ok:
            return "🟡 Watch"
        return "🔴 Off-track"

    client_summary["health"] = client_summary.apply(_client_health, axis=1)
    client_summary = client_summary.sort_values("total_tasks", ascending=False)

    # -----------------------------------------------------------------------
    # Goal-aware KPI row
    # -----------------------------------------------------------------------
    total_tasks_all = len(filtered)
    n_clients = filtered["client"].nunique()
    portfolio_completion = (len(closed_in_range) / max(total_tasks_all, 1) * 100)
    portfolio_turnaround = clean_turnaround(closed_in_range["turnaround_days"]).mean() if len(closed_in_range) else float("nan")
    on_track = (client_summary["health"] == "🟢 On-track").sum()
    off_track = (client_summary["health"] == "🔴 Off-track").sum()
    pct_on_track = on_track / max(len(client_summary), 1) * 100

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        kpi_vs_goal("Portfolio Completion", portfolio_completion, GOALS["completion_rate_target"],
                    unit="%", higher_is_better=True, warn=GOALS["completion_rate_warn"],
                    help_text="Closed (in range) ÷ total filtered tasks. Goal is the team completion-rate target.")
    with k2:
        kpi_vs_goal("Avg Turnaround", portfolio_turnaround, GOALS["turnaround_days_target"],
                    unit="d", higher_is_better=False, warn=GOALS["turnaround_days_warn"],
                    help_text="Mean business days Created→Closed (IQR-cleaned). Goal is the turnaround target.")
    with k3:
        kpi_vs_goal("Clients On-Track", pct_on_track, 80,
                    unit="%", higher_is_better=True, warn=60,
                    help_text=f"{on_track} of {len(client_summary)} clients green. A client is on-track when turnaround and completion both beat target.")
    with k4:
        st.metric("Clients / Active Epics", f"{n_clients} / {len(epics[epics['client'].isin(filtered['client'].unique())])}",
                  help="Distinct clients in the current filter, and recurring epics tied to them.")

    if off_track > 0:
        worst = client_summary[client_summary["health"] == "🔴 Off-track"].sort_values("total_tasks", ascending=False).head(5)
        st.warning(f"**{off_track} client(s) off-track.** Biggest by volume: " +
                   ", ".join(f"{r.client} ({r.completion_rate:.0f}% done, {r.avg_turnaround:.0f}d)" for r in worst.itertuples()))

    st.divider()

    # -----------------------------------------------------------------------
    # Portfolio concentration — where does the work/effort actually go?
    # -----------------------------------------------------------------------
    st.subheader("Portfolio Concentration")
    st.caption("Leaders' first question: how concentrated is our work? A few clients often drive most of the load.")

    conc_left, conc_right = st.columns(2)
    with conc_left:
        # Pareto: cumulative % of tasks by client
        pareto = client_summary.sort_values("total_tasks", ascending=False).copy()
        pareto["cum_pct"] = (pareto["total_tasks"].cumsum() / pareto["total_tasks"].sum() * 100)
        top_n = pareto.head(15)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=top_n["client"], y=top_n["total_tasks"], name="Tasks",
                             marker_color="#3498db"))
        fig.add_trace(go.Scatter(x=top_n["client"], y=top_n["cum_pct"], name="Cumulative %",
                                 yaxis="y2", mode="lines+markers", line=dict(color="#e74c3c", width=2)))
        fig.add_hline(y=80, line_dash="dot", line_color="#e74c3c", yref="y2",
                      annotation_text="80% of work", annotation_position="top left")
        fig.update_layout(height=400, title="Task Volume by Client (Pareto)",
                          yaxis=dict(title="Tasks"),
                          yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105]),
                          xaxis_tickangle=-45, legend=dict(orientation="h", y=1.12),
                          margin=dict(t=60))
        st.plotly_chart(fig, use_container_width=True)
        clients_for_80 = (pareto["cum_pct"] <= 80).sum() + 1
        st.caption(f"**Insight:** ~{clients_for_80} client(s) account for 80% of all tasks in this filter.")

    with conc_right:
        # Effort (hours) treemap by client → work type
        eff = filtered.copy()
        eff_grp = eff.groupby(["client", "work_type"])["estimated_completion_time"].sum().reset_index()
        eff_grp["hours"] = (eff_grp["estimated_completion_time"] / 60).round(1)
        eff_grp = eff_grp[eff_grp["hours"] > 0]
        fig = px.treemap(eff_grp, path=["client", "work_type"], values="hours",
                         color="work_type",
                         color_discrete_map={"Recurring": "#3498db", "Adhoc": "#e74c3c", "(?)": "#95a5a6"},
                         height=400, title="Estimated Effort (hours) by Client & Work Type")
        fig.update_traces(textinfo="label+value")
        fig.update_layout(margin=dict(t=60))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("**Insight:** box size = estimated hours. Blue = recurring (keep-the-lights-on), red = adhoc/new work.")

    st.divider()

    # -----------------------------------------------------------------------
    # Client health quadrant — volume vs completion, colored by turnaround
    # -----------------------------------------------------------------------
    st.subheader("Client Health Map")
    st.caption("Top-right is ideal (high volume, high completion). Red points = slow turnaround. Watch the bottom-right: high-volume clients we're not closing.")
    quad = client_summary[client_summary["total_tasks"] >= 2].copy()
    fig = px.scatter(quad, x="total_tasks", y="completion_rate",
                     size="est_hours", color="avg_turnaround",
                     color_continuous_scale="RdYlGn_r", hover_name="client",
                     labels={"total_tasks": "Total Tasks", "completion_rate": "Completion %",
                             "avg_turnaround": "Avg Turn (d)", "est_hours": "Est. Hours"},
                     height=450)
    fig.add_hline(y=GOALS["completion_rate_target"], line_dash="dash", line_color="#2ecc71",
                  annotation_text=f"Completion goal {GOALS['completion_rate_target']}%")
    fig.update_layout(margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # -----------------------------------------------------------------------
    # Scorecard table (goal-scored)
    # -----------------------------------------------------------------------
    st.subheader("Client Scorecard")
    show_cols = client_summary[[
        "health", "client", "total_tasks", "open_tasks", "closed_tasks",
        "completion_rate", "avg_turnaround", "recurring_tasks", "rush_pct", "est_hours",
    ]].rename(columns={
        "health": "Health", "client": "Client", "total_tasks": "Total", "open_tasks": "Open",
        "closed_tasks": "Closed", "completion_rate": "% Complete", "avg_turnaround": "Avg Turn (d)",
        "recurring_tasks": "Recurring", "rush_pct": "Rush %", "est_hours": "Est. Hours",
    })
    st.dataframe(
        show_cols, use_container_width=True, hide_index=True,
        column_config={
            "% Complete": st.column_config.ProgressColumn(
                "% Complete", min_value=0, max_value=100, format="%.0f%%"),
            "Est. Hours": st.column_config.NumberColumn("Est. Hours", format="%.1f h"),
        },
    )

    st.divider()

    # -----------------------------------------------------------------------
    # Client drill-down
    # -----------------------------------------------------------------------
    st.subheader("Client Drill-Down")
    selected_client = st.selectbox("Select a client", sorted(filtered["client"].unique()))
    client_tasks = filtered[filtered["client"] == selected_client].sort_values("created", ascending=False)
    client_row = client_summary[client_summary["client"] == selected_client]

    c_turn = clean_turnaround(client_tasks["turnaround_days"]).mean() if client_tasks["turnaround_days"].notna().any() else float("nan")
    c_comp = client_row["completion_rate"].iloc[0] if len(client_row) else 0
    c_health = client_row["health"].iloc[0] if len(client_row) else "⚪"

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Health", c_health)
    d2.metric("Total Tasks", len(client_tasks),
              help="All tasks for this client in the current filter")
    with d3:
        kpi_vs_goal("Completion", float(c_comp), GOALS["completion_rate_target"], unit="%",
                    higher_is_better=True, warn=GOALS["completion_rate_warn"])
    with d4:
        kpi_vs_goal("Avg Turnaround", c_turn, GOALS["turnaround_days_target"], unit="d",
                    higher_is_better=False, warn=GOALS["turnaround_days_warn"])

    st.dataframe(
        client_tasks[["key", "summary", "status", "assignee", "task_type", "created", "closed_date", "frequency"]],
        use_container_width=True, hide_index=True
    )


# ===========================================================================
# TAB 3: Recurring Operations — the "keep-the-lights-on" engine vs new development
# ===========================================================================
with tab3:
    st.header("Recurring Operations")
    st.caption("How much of the team's capacity is spent on recurring 'keep-the-lights-on' work, "
               "when in the month it lands, and how it compares to new-development effort — all scored against goals.")

    # Frequency → occurrences-per-week (used to annualize recurring load into weekly capacity)
    freq_to_weekly = {
        "daily": 5, "weekly": 1, "biweekly": 0.5,
        "monthly": 0.25, "quarterly": 0.077,
        "semiannual": 0.038, "annual": 0.019, "one-time": 0,
    }

    recurring = filtered[filtered["work_type"] == "Recurring"].copy()
    adhoc = filtered[filtered["work_type"] == "Adhoc"].copy()

    rec_hours = recurring["estimated_completion_time"].sum() / 60
    adhoc_hours = adhoc["estimated_completion_time"].sum() / 60
    total_hours_wt = rec_hours + adhoc_hours
    recurring_hours_pct = (rec_hours / max(total_hours_wt, 0.01)) * 100

    # Steady-state weekly recurring load (occurrence-weighted) and utilization vs capacity
    recurring["weekly_minutes"] = recurring["estimated_completion_time"] * recurring["frequency"].map(freq_to_weekly).fillna(0)
    weekly_recurring_hours = recurring["weekly_minutes"].sum() / 60
    n_producing = len(GOALS["producing_analysts"])
    team_capacity_hpw = n_producing * GOALS["hours_per_week_per_person"]
    utilization_pct = (weekly_recurring_hours / max(team_capacity_hpw, 0.01)) * 100

    # -----------------------------------------------------------------------
    # Goal-aware KPI row
    # -----------------------------------------------------------------------
    g1, g2, g3, g4 = st.columns(4)
    with g1:
        kpi_vs_goal("Recurring Task Share", len(recurring) / max(len(filtered), 1) * 100,
                    100 - 0, unit="%", higher_is_better=False, warn=None,
                    help_text="Share of tasks that are recurring vs one-time. Context metric (no hard goal).")
        st.caption(f"{len(recurring):,} recurring · {len(adhoc):,} adhoc")
    with g2:
        kpi_vs_goal("Recurring % of Hours", recurring_hours_pct, GOALS["recurring_hours_pct_target"],
                    unit="%", higher_is_better=False, warn=GOALS["recurring_hours_pct_warn"],
                    help_text="Estimated recurring hours ÷ total estimated hours. Above target means keep-the-lights-on work is crowding out new development.")
    with g3:
        kpi_vs_goal("Recurring Utilization", utilization_pct, GOALS["utilization_target_pct"],
                    unit="%", higher_is_better=False, warn=GOALS["utilization_warn_pct"],
                    help_text=f"Steady-state recurring load ({weekly_recurring_hours:.0f} h/wk) ÷ team capacity ({team_capacity_hpw:.0f} h/wk from {n_producing} analysts). Over 100% means recurring alone exceeds capacity.")
    with g4:
        st.metric("New-Dev Capacity Left", f"{max(team_capacity_hpw - weekly_recurring_hours, 0):.0f} h/wk",
                  delta=f"of {team_capacity_hpw:.0f} h/wk total",
                  delta_color="off",
                  help="Weekly hours left for new development after steady-state recurring work is covered.")

    # Headline narrative
    badge, _ = status_color(recurring_hours_pct, GOALS["recurring_hours_pct_target"], GOALS["recurring_hours_pct_warn"], higher_is_better=False)
    st.markdown(
        f"{badge} **{recurring_hours_pct:.0f}%** of estimated effort is recurring "
        f"(**{rec_hours:,.0f} h** recurring vs **{adhoc_hours:,.0f} h** new/adhoc). "
        f"Goal: keep recurring **≤ {GOALS['recurring_hours_pct_target']}%** so the team preserves room for new development."
    )

    st.divider()

    # -----------------------------------------------------------------------
    # Recurring vs New Development — the effort split (gauges + trend)
    # -----------------------------------------------------------------------
    st.subheader("Recurring vs New Development")
    gauge_l, gauge_r = st.columns(2)
    with gauge_l:
        st.plotly_chart(
            goal_gauge(recurring_hours_pct, GOALS["recurring_hours_pct_target"],
                       "Recurring % of Hours", warn=GOALS["recurring_hours_pct_warn"],
                       max_val=100, higher_is_better=False, suffix="%"),
            use_container_width=True)
    with gauge_r:
        st.plotly_chart(
            goal_gauge(utilization_pct, GOALS["utilization_target_pct"],
                       "Recurring Utilization of Capacity", warn=GOALS["utilization_warn_pct"],
                       max_val=max(130, utilization_pct * 1.2), higher_is_better=False, suffix="%"),
            use_container_width=True)

    # Trend: recurring % of created-task effort by month (is toil creeping up?)
    trend = filtered.dropna(subset=["created"]).copy()
    if len(trend) > 0:
        trend["month"] = trend["created"].dt.strftime("%Y-%m")
        mix = trend.groupby(["month", "work_type"])["estimated_completion_time"].sum().unstack(fill_value=0)
        for col in ["Recurring", "Adhoc"]:
            if col not in mix.columns:
                mix[col] = 0
        mix["rec_pct"] = mix["Recurring"] / (mix["Recurring"] + mix["Adhoc"]).replace(0, pd.NA) * 100
        mix = mix.reset_index().dropna(subset=["rec_pct"])
        fig = go.Figure()
        fig.add_trace(go.Bar(x=mix["month"], y=mix["Recurring"] / 60, name="Recurring hrs", marker_color="#3498db"))
        fig.add_trace(go.Bar(x=mix["month"], y=mix["Adhoc"] / 60, name="New/Adhoc hrs", marker_color="#e74c3c"))
        fig.add_trace(go.Scatter(x=mix["month"], y=mix["rec_pct"], name="Recurring %",
                                 yaxis="y2", mode="lines+markers", line=dict(color="#2c3e50", width=2)))
        fig.add_hline(y=GOALS["recurring_hours_pct_target"], line_dash="dash", line_color="#2ecc71",
                      yref="y2", annotation_text=f"Goal {GOALS['recurring_hours_pct_target']}%",
                      annotation_position="top left")
        fig.update_layout(barmode="stack", height=420, title="Effort Mix by Month (created)",
                          yaxis=dict(title="Estimated Hours"),
                          yaxis2=dict(title="Recurring %", overlaying="y", side="right", range=[0, 100]),
                          xaxis_tickangle=-45, legend=dict(orientation="h", y=1.12),
                          margin=dict(t=60))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("**Insight:** the black line is the share of effort going to recurring work each month. "
                   "Rising above the green goal line means new development is getting squeezed.")

    st.divider()

    # -----------------------------------------------------------------------
    # WHEN in the month do recurring tasks land? (beginning / middle / end)
    # -----------------------------------------------------------------------
    st.subheader("Recurring Due Timing — When in the Month?")
    st.caption("Recurring child tasks are auto-created on their due cadence, so a task's created date is its due date. "
               "This shows the crunch periods to staff around.")

    rec_due = recurring.dropna(subset=["created"]).copy()
    if len(rec_due) > 0:
        rec_due["dom"] = rec_due["created"].dt.day

        def month_third(d):
            if d <= 10:
                return "Beginning (1–10)"
            if d <= 20:
                return "Middle (11–20)"
            return "End (21–31)"

        rec_due["third"] = rec_due["dom"].apply(month_third)
        third_order = ["Beginning (1–10)", "Middle (11–20)", "End (21–31)"]

        tl, tr = st.columns([1, 2])
        with tl:
            third_counts = rec_due["third"].value_counts().reindex(third_order).fillna(0).reset_index()
            third_counts.columns = ["Third", "Tasks"]
            third_hours = rec_due.groupby("third")["estimated_completion_time"].sum().reindex(third_order).fillna(0) / 60
            third_counts["Hours"] = third_counts["Third"].map(third_hours).round(1)
            fig = px.bar(third_counts, x="Third", y="Tasks", color="Third",
                         color_discrete_sequence=["#2ecc71", "#f39c12", "#e74c3c"],
                         text="Tasks", height=380, title="Recurring Tasks by Part of Month")
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False, margin=dict(t=50))
            st.plotly_chart(fig, use_container_width=True)
            busiest = third_counts.loc[third_counts["Tasks"].idxmax(), "Third"]
            st.caption(f"**Peak load: {busiest}** — {int(third_counts['Tasks'].max())} tasks, "
                       f"{third_counts.loc[third_counts['Tasks'].idxmax(), 'Hours']:.0f} est. hours.")
        with tr:
            dom_counts = rec_due.groupby("dom").size().reindex(range(1, 32), fill_value=0).reset_index()
            dom_counts.columns = ["Day", "Tasks"]
            fig = px.bar(dom_counts, x="Day", y="Tasks", height=380,
                         title="Recurring Tasks by Day of Month", color="Tasks",
                         color_continuous_scale="Blues")
            fig.update_layout(coloraxis_showscale=False, margin=dict(t=50),
                              xaxis=dict(dtick=1, tickfont=dict(size=9)))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("**Insight:** tall bars = recurring due-date clusters (often the 1st, 15th, and month-end). Plan capacity around them.")

        # Calendar-style heatmap: day-of-month (x) by frequency (y)
        st.markdown("**Due-date heatmap — day of month by cadence**")
        heat = rec_due.groupby(["frequency", "dom"]).size().reset_index(name="tasks")
        freq_row_order = [f for f in ["weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual", "daily"]
                          if f in heat["frequency"].unique()]
        heat_pivot = heat.pivot(index="frequency", columns="dom", values="tasks").reindex(
            index=freq_row_order, columns=range(1, 32)).fillna(0)
        fig = px.imshow(heat_pivot, aspect="auto", color_continuous_scale="YlOrRd",
                        labels=dict(x="Day of Month", y="Cadence", color="Tasks"),
                        height=300)
        fig.update_layout(margin=dict(t=20), xaxis=dict(dtick=1, tickfont=dict(size=9)))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No recurring tasks in the current filter.")

    st.divider()

    # -----------------------------------------------------------------------
    # Recurring workload as epics — the recurring "contracts" the team owns
    # -----------------------------------------------------------------------
    st.subheader("Recurring Work Defined as Epics")
    st.caption("Each recurring epic is a standing commitment (a report/extract the team owns). "
               "This shows the shape of that recurring book of work.")

    rec_epics = epics[epics["frequency"].fillna("one-time") != "one-time"].copy()
    if len(rec_epics) > 0:
        rec_epics["annual_occurrences"] = rec_epics["frequency"].map(
            {"daily": 260, "weekly": 52, "biweekly": 26, "monthly": 12,
             "quarterly": 4, "semiannual": 2, "annual": 1}).fillna(0)
        rec_epics["est_min"] = rec_epics["estimated_completion_time"].fillna(0)
        rec_epics["annual_hours"] = (rec_epics["annual_occurrences"] * rec_epics["est_min"] / 60).round(1)
        rec_epics["weekly_hours"] = (rec_epics["annual_hours"] / 52).round(2)

        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Recurring Epics", len(rec_epics), help="Epics with a recurring cadence (the standing book of work).")
        e2.metric("Annual Recurring Hours", f"{rec_epics['annual_hours'].sum():,.0f} h",
                  help="Sum of (occurrences/yr × est. time) across all recurring epics.")
        e3.metric("Implied FTEs", f"{rec_epics['annual_hours'].sum() / (GOALS['hours_per_week_per_person'] * 52):.2f}",
                  help=f"Annual recurring hours ÷ ({GOALS['hours_per_week_per_person']} h/wk × 52 wk). How many full-time people the recurring book consumes.")
        e4.metric("Distinct Clients", rec_epics["client"].nunique())

        ce_l, ce_r = st.columns(2)
        with ce_l:
            by_freq = rec_epics.groupby("frequency").agg(
                epics=("key", "count"), annual_hours=("annual_hours", "sum")).reset_index()
            by_freq = by_freq.sort_values("annual_hours", ascending=False)
            fig = px.bar(by_freq, x="frequency", y="annual_hours", color="frequency",
                         text="epics", height=380, title="Annual Recurring Hours by Cadence")
            fig.update_traces(texttemplate="%{text} epics", textposition="outside")
            fig.update_layout(showlegend=False, yaxis_title="Annual Hours", margin=dict(t=50))
            st.plotly_chart(fig, use_container_width=True)
        with ce_r:
            by_type = rec_epics.groupby("task_type").agg(annual_hours=("annual_hours", "sum")).reset_index()
            by_type = by_type[by_type["annual_hours"] > 0].sort_values("annual_hours", ascending=False)
            fig = px.pie(by_type, names="task_type", values="annual_hours", hole=0.45,
                         height=380, title="Annual Recurring Hours by Work Category")
            fig.update_traces(textinfo="label+percent")
            fig.update_layout(margin=dict(t=50))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Heaviest recurring commitments (by annual hours)**")
        top_epics = rec_epics.sort_values("annual_hours", ascending=False).head(20)[
            ["key", "summary", "client", "frequency", "est_min", "annual_occurrences", "annual_hours", "weekly_hours", "assignee"]
        ].rename(columns={
            "key": "Epic", "summary": "Summary", "client": "Client", "frequency": "Cadence",
            "est_min": "Min/Run", "annual_occurrences": "Runs/Yr", "annual_hours": "Hours/Yr",
            "weekly_hours": "Hours/Wk", "assignee": "Owner",
        })
        JIRA_BASE = "https://arnoldmedia.jira.com/browse/"
        top_epics["Epic"] = top_epics["Epic"].apply(lambda x: f"{JIRA_BASE}{x}")
        st.dataframe(
            top_epics, use_container_width=True, hide_index=True,
            column_config={
                "Epic": st.column_config.LinkColumn("Epic", display_text=r"(CRS-\d+)"),
                "Hours/Yr": st.column_config.NumberColumn("Hours/Yr", format="%.1f h"),
                "Hours/Wk": st.column_config.NumberColumn("Hours/Wk", format="%.2f h"),
            },
        )
    else:
        st.info("No recurring epics found in the epics export.")

    st.divider()

    # -----------------------------------------------------------------------
    # Per-member recurring load vs capacity (goal line)
    # -----------------------------------------------------------------------
    st.subheader("Recurring Load per Member vs Capacity")
    st.caption(f"Steady-state recurring hours/week per analyst. Goal: recurring stays under "
               f"{GOALS['recurring_hours_pct_target']}% of a {GOALS['hours_per_week_per_person']}h week "
               f"(~{GOALS['hours_per_week_per_person'] * GOALS['recurring_hours_pct_target'] / 100:.0f}h) to leave room for new dev.")

    if len(recurring) > 0:
        member_load = recurring.groupby("assignee")["weekly_minutes"].sum().reset_index()
        member_load["weekly_hours"] = (member_load["weekly_minutes"] / 60).round(1)
        member_load = member_load.sort_values("weekly_hours", ascending=False)
        rec_target_h = GOALS["hours_per_week_per_person"] * GOALS["recurring_hours_pct_target"] / 100

        fig = px.bar(member_load, x="assignee", y="weekly_hours", height=400,
                     text="weekly_hours", color="weekly_hours", color_continuous_scale="OrRd")
        fig.update_traces(texttemplate="%{text:.1f}h", textposition="outside")
        fig.add_hline(y=rec_target_h, line_dash="dash", line_color="#2ecc71",
                      annotation_text=f"Recurring goal ≤ {rec_target_h:.0f}h/wk", annotation_position="top right")
        fig.add_hline(y=GOALS["hours_per_week_per_person"], line_dash="dot", line_color="#e74c3c",
                      annotation_text=f"{GOALS['hours_per_week_per_person']}h/wk full capacity", annotation_position="bottom right")
        fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=-45, yaxis_title="Recurring Hours/Week")
        st.plotly_chart(fig, use_container_width=True)

        over = member_load[member_load["weekly_hours"] > rec_target_h]
        if len(over) > 0:
            st.warning("**Over recurring goal:** " +
                       ", ".join(f"{r.assignee} ({r.weekly_hours:.1f}h/wk)" for r in over.itertuples()) +
                       " — little room left for new development.")
    else:
        st.info("No recurring tasks in the current filter.")
