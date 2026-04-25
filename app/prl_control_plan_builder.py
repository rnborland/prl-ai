import pandas as pd
import streamlit as st
from pathlib import Path

OUTPUT_PATH = "/srv/PRL-ui/control_plan.csv"

COLUMNS = [
    "asset_id", "asset_name", "process_mode",
    "tag_name", "display_name", "description",
    "data_source", "measurement", "field_name", "unit",
    "variable_role", "sampling_interval_sec",
    "lower_limit", "upper_limit", "warning_low", "warning_high",
    "target_value", "target_direction", "target_deadline_sec",
    "expected_rate_min", "expected_rate_max", "rate_unit",
    "process_stage", "stage_min", "stage_max",
    "allow_operator_override", "override_type",
    "priority", "expected_pattern",
    "reaction_plan", "document_reference",
    "missing_data_action", "enabled",
]

st.set_page_config(page_title="Control Plan Builder", layout="wide")

st.title("Control Plan CSV Builder")
st.caption("Create a customized control plan for any process, machine, facility, or installation.")

with st.sidebar:
    st.header("Application Defaults")

    asset_id = st.text_input("Asset ID", "demo_asset")
    asset_name = st.text_input("Asset Name", "Demo Process")
    process_mode = st.selectbox("Process Mode", ["steady_state", "transformation"])

    default_source = st.selectbox("Data Source", ["influx", "http", "mqtt"], index=0)
    default_field = st.text_input("Field Name", "value")

    row_count = st.number_input("Number of variables", min_value=1, max_value=20, value=10, step=1)

    st.divider()
    output_path = st.text_input("Save path", OUTPUT_PATH)

rows = []

for i in range(int(row_count)):
    st.subheader(f"Variable {i + 1}")

    c1, c2, c3 = st.columns(3)

    with c1:
        tag_name = st.text_input("Tag Name", f"tag_{i+1}", key=f"tag_{i}")
        display_name = st.text_input("Display Name", f"Variable {i+1}", key=f"display_{i}")
        description = st.text_area("Description", "", height=80, key=f"desc_{i}")

    with c2:
        measurement = st.text_input("Influx Measurement / Source Name", f"measurement_{i+1}", key=f"meas_{i}")
        unit = st.text_input("Unit", "", key=f"unit_{i}")
        variable_role = st.selectbox(
            "Variable Role",
            ["process_health", "trajectory", "outcome"],
            key=f"role_{i}",
        )
        sampling_interval_sec = st.number_input(
            "Sampling Interval Sec",
            min_value=1,
            value=300,
            step=60,
            key=f"sample_{i}",
        )

    with c3:
        priority = st.selectbox("Priority", ["low", "medium", "high", "critical"], index=1, key=f"priority_{i}")
        expected_pattern = st.selectbox(
            "Expected Pattern",
            ["steady", "cyclic", "declining", "increasing", "batch", "seasonal", "completion_check"],
            key=f"pattern_{i}",
        )
        enabled = st.selectbox("Enabled", ["yes", "no"], key=f"enabled_{i}")

    with st.expander("Limits / Warnings / Targets", expanded=False):
        l1, l2, l3, l4 = st.columns(4)

        with l1:
            lower_limit = st.text_input("Lower Limit", "", key=f"ll_{i}")
            upper_limit = st.text_input("Upper Limit", "", key=f"ul_{i}")

        with l2:
            warning_low = st.text_input("Warning Low", "", key=f"wl_{i}")
            warning_high = st.text_input("Warning High", "", key=f"wh_{i}")

        with l3:
            target_value = st.text_input("Target Value", "", key=f"target_{i}")
            target_direction = st.selectbox("Target Direction", ["", "increase", "decrease", "hold"], key=f"dir_{i}")

        with l4:
            target_deadline_sec = st.text_input("Target Deadline Sec", "", key=f"deadline_{i}")
            rate_unit = st.text_input("Rate Unit", "", key=f"rate_unit_{i}")

        r1, r2 = st.columns(2)
        with r1:
            expected_rate_min = st.text_input("Expected Rate Min", "", key=f"rate_min_{i}")
        with r2:
            expected_rate_max = st.text_input("Expected Rate Max", "", key=f"rate_max_{i}")

    with st.expander("Stages / Overrides / Actions", expanded=False):
        s1, s2, s3 = st.columns(3)

        with s1:
            process_stage = st.text_input("Process Stage", "", key=f"stage_{i}")
            stage_min = st.text_input("Stage Min", "", key=f"stage_min_{i}")
            stage_max = st.text_input("Stage Max", "", key=f"stage_max_{i}")

        with s2:
            allow_operator_override = st.selectbox("Allow Operator Override", ["yes", "no"], key=f"override_{i}")
            override_type = st.selectbox("Override Type", ["none", "temporary", "daily", "shift", "batch"], key=f"override_type_{i}")

        with s3:
            missing_data_action = st.text_area(
                "Missing Data Action",
                "Check sensor power or communications if no data for 2 intervals",
                height=100,
                key=f"missing_{i}",
            )

        reaction_plan = st.text_area(
            "Reaction Plan",
            "Check sensor; Verify process conditions; Review recent changes",
            height=90,
            key=f"reaction_{i}",
            help="Use semicolons between steps.",
        )

        document_reference = st.text_area(
            "Document Reference",
            "Process Manual",
            height=70,
            key=f"docref_{i}",
        )

    rows.append({
        "asset_id": asset_id,
        "asset_name": asset_name,
        "process_mode": process_mode,
        "tag_name": tag_name,
        "display_name": display_name,
        "description": description,
        "data_source": default_source,
        "measurement": measurement,
        "field_name": default_field,
        "unit": unit,
        "variable_role": variable_role,
        "sampling_interval_sec": sampling_interval_sec,
        "lower_limit": lower_limit,
        "upper_limit": upper_limit,
        "warning_low": warning_low,
        "warning_high": warning_high,
        "target_value": target_value,
        "target_direction": target_direction,
        "target_deadline_sec": target_deadline_sec,
        "expected_rate_min": expected_rate_min,
        "expected_rate_max": expected_rate_max,
        "rate_unit": rate_unit,
        "process_stage": process_stage,
        "stage_min": stage_min,
        "stage_max": stage_max,
        "allow_operator_override": allow_operator_override,
        "override_type": override_type,
        "priority": priority,
        "expected_pattern": expected_pattern,
        "reaction_plan": reaction_plan,
        "document_reference": document_reference,
        "missing_data_action": missing_data_action,
        "enabled": enabled,
    })

df = pd.DataFrame(rows, columns=COLUMNS)

st.divider()
st.subheader("Preview Control Plan")
st.dataframe(df, use_container_width=True)

csv_bytes = df.to_csv(index=False).encode("utf-8")

c1, c2 = st.columns(2)

with c1:
    st.download_button(
        "Download control_plan.csv",
        data=csv_bytes,
        file_name="control_plan.csv",
        mime="text/csv",
        use_container_width=True,
    )

with c2:
    if st.button("Save to server path", use_container_width=True):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        st.success(f"Saved control plan to {output_path}")
