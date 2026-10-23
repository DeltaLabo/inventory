"""Read-only project reports from the separately persisted withdrawal ledger."""

from pathlib import Path

import pandas as pd
import streamlit as st

from github_inventory import GitHubError, GitHubInventory, MOVEMENT_COLUMNS, positive_integer, read_rows
from inventory import spreadsheet_csv


ROOT = Path(__file__).resolve().parent
LABELS = {
    "timestamp": "Withdrawn at (UTC)", "project": "Project", "code": "Code",
    "description": "Current description", "quantity": "Quantity withdrawn",
    "person": "Recorded by", "location": "Box", "sublocation": "Bag",
    "available_after": "Available after withdrawal", "id": "Movement ID",
}


@st.cache_data(ttl=15, max_entries=4, show_spinner=False)
def live_withdrawals(token, repository, branch):
    return GitHubInventory(token, repository, branch).withdrawal_snapshot()


def history_frame(rows, details):
    frame = pd.DataFrame(rows, columns=MOVEMENT_COLUMNS)
    # A lookup never multiplies movements, even if the catalog has duplicate IDs.
    unique = details[~details["code"].duplicated(keep=False)]
    descriptions = unique.set_index("code")["description"].to_dict()
    frame["description"] = frame["code"].map(lambda code: descriptions.get(code, ""))
    frame["quantity"] = frame["quantity"].map(positive_integer)
    dates = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce", format="mixed")
    frame = frame.assign(_date=dates).sort_values("_date", ascending=False, kind="stable").drop(columns="_date")
    return frame.reset_index(drop=True)


def project_rows(frame, project=None):
    return frame if project is None else frame[frame["project"].eq(project)]


def product_totals(frame):
    return (frame.groupby(["project", "code", "description"], as_index=False, dropna=False)["quantity"].sum()
            .rename(columns={"project": "Project", "code": "Code", "description": "Current description", "quantity": "Total withdrawn"}))


def withdrawal_history(client, config, details):
    st.subheader("Withdrawal history")
    st.caption("Withdrawals are stored separately from stock in GitHub. Filter by project to see totals and individual movements. Descriptions come from the current catalog.")
    try:
        if client:
            if st.button("Refresh withdrawal history"):
                live_withdrawals.clear()
                st.rerun()
            rows = live_withdrawals(config["token"], config["repository"], config["branch"])
        else:
            path = ROOT / "movements.csv"
            rows = read_rows(path.read_text(encoding="utf-8-sig"), MOVEMENT_COLUMNS)[1] if path.exists() else []
            st.info("Showing the local withdrawal-history snapshot. Connect to GitHub to see the latest withdrawals.")
        frame = history_frame(rows, details)
    except (GitHubError, ValueError, OSError, pd.errors.ParserError):
        st.error("Could not load withdrawal history. Refresh to try again; no stock was changed.")
        return
    projects = sorted(frame["project"].unique().tolist(), key=str.casefold)
    project = st.selectbox("Project", [None, *projects],
                           format_func=lambda value: "All projects" if value is None else (f"Project: {value}" if value else "No project recorded"))
    selected = project_rows(frame, project)
    st.caption(f"{len(selected)} movements")
    st.download_button("Download selected withdrawal history (CSV)",
                       spreadsheet_csv(selected[list(LABELS)].rename(columns=LABELS)),
                       file_name="withdrawal_history.csv", mime="text/csv")
    if selected.empty:
        st.info("No recorded withdrawals in this snapshot.")
        return
    if selected["project"].eq("").any():
        st.info("Some older withdrawals have no recorded project. Their original records are preserved.")
    st.subheader("Products withdrawn by project")
    st.dataframe(product_totals(selected), hide_index=True, width="stretch")
    st.subheader("Individual withdrawals")
    st.dataframe(selected[list(LABELS)].rename(columns=LABELS), hide_index=True, width="stretch")
