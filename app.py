"""Local workspace for inspecting shipment support and comparing handling policies."""

from contextlib import contextmanager
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

import streamlit as st

from evaluator.analysis import DEFAULT_CONFIG, analyze_exports
from evaluator.exports import TABLES
from evaluator.reporting import format_measure, label, make_downloads, metric_basis, metric_rows, render_decision_brief, write_run_bundle
from evaluator.recommendation import VALUE_BASES, assess_recommendation, case_review_actions
from evaluator.upgrade_value import assess_error_loss_scenario, assess_upgrade
from evaluator.verification import _settings
from evaluator.grading import grade_enquiry
from input_quality_ui import render_input_quality
from intake_ui import IMPORTS, render_company_import


HERE = Path(__file__).resolve().parent
DATASETS = HERE / "datagen" / "datasets"
RUNS = HERE / "runs"
POLICY = HERE / "evaluator" / "policy.json"
MAX_UPLOAD = 100 * 1024**2
MAX_EXPANSION = 300 * 1024**2
EXPORT_FILES = {filename for filename, _ in TABLES.values()} | {
    "export_metadata.json", "ai_invoice.csv", "staffing.csv", "rollout_log.csv",
    "cost_parameters.json", "service_rules.yaml",
}
DEMONSTRATIONS = {
    "Three handling policies · clean demo": DATASETS / "release_1" / "demo" / "exports",
    "Tiny dataset": DATASETS / "release_1" / "tiny" / "exports",
    "Development dataset": DATASETS / "release_1" / "dev" / "exports",
    "Damaged exports": DATASETS / "release_1" / "damaged" / "exports",
    "Identical agent policies": DATASETS / "release_1" / "null_effect" / "exports",
    "Before and after rollout": DATASETS / "release_1" / "confounded" / "exports",
    "Staged regional rollout": DATASETS / "release_1" / "staged" / "exports",
    "S32 · Wrong container with human recovery": DATASETS / "scenarios" / "S32" / "exports",
    "S33 · Missed escalation with human recovery": DATASETS / "scenarios" / "S33" / "exports",
}
UPLOAD = "Upload an exports ZIP"


@contextmanager
def unpack_exports(payload):
    """Accept only direct, regular, recognized entries beneath exports/."""
    if len(payload) > MAX_UPLOAD:
        raise ValueError("The ZIP is larger than the 100 MiB upload limit.")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            members = {}
            expanded_size = 0
            for entry in archive.infolist():
                mode = stat.S_IFMT(entry.external_attr >> 16)
                name = entry.filename
                if entry.orig_filename != name or entry.flag_bits & 1:
                    raise ValueError("ZIP entries must be unencrypted and have valid names.")
                if name == "exports/" and entry.is_dir() and mode in (0, stat.S_IFDIR):
                    continue
                parts = name.split("/")
                if len(parts) != 2 or parts[0] != "exports" or parts[1] not in EXPORT_FILES:
                    raise ValueError("Place only supported export files directly inside the exports folder.")
                if mode not in (0, stat.S_IFREG) or entry.is_dir():
                    raise ValueError("ZIP entries must be regular files.")
                if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ValueError("Use a standard stored or deflated ZIP.")
                filename = parts[1]
                if filename in members:
                    raise ValueError(f"The ZIP repeats {filename}.")
                members[filename] = entry
                expanded_size += entry.file_size
                if expanded_size > MAX_EXPANSION:
                    raise ValueError("The expanded exports exceed the 300 MiB limit.")
            if not {"export_metadata.json", "enquiries.csv"} <= members.keys():
                raise ValueError("The ZIP must contain exports/export_metadata.json and exports/enquiries.csv.")
            with TemporaryDirectory(prefix="shipment-evaluation-") as temporary:
                root = Path(temporary) / "exports"
                root.mkdir()
                for filename, entry in members.items():
                    with archive.open(entry) as source, (root / filename).open("xb") as target:
                        shutil.copyfileobj(source, target, length=64 * 1024)
                    if (root / filename).stat().st_size != entry.file_size:
                        raise ValueError(f"The ZIP entry {filename} has an inconsistent size.")
                yield root
    except BadZipFile as error:
        raise ValueError("The uploaded file is not a valid ZIP archive.") from error


def _available_demos():
    datasets = {name: path for name, path in DEMONSTRATIONS.items() if path.is_dir()}
    prepared = st.session_state.get("shipment_import_path")
    if prepared:
        path = Path(prepared)
        if path.is_dir() and path.resolve().is_relative_to(IMPORTS.resolve()):
            datasets["Prepared company files"] = path
    return datasets


def _apply_theme():
    st.markdown(
        """<style>
        .stApp, [data-testid="stHeader"] { background: #fff; color: #171717; }
        [data-testid="stAppViewContainer"] { color: #171717; }
        [data-testid="stMainBlockContainer"] { max-width: 75rem; padding-top: 3.2rem; }
        h1, h2, h3 { color: #151515; letter-spacing: -.025em; }
        h1 { font-size: clamp(1.85rem, 5vw, 3rem); line-height: 1.13; }
        [data-testid="stCaptionContainer"] p { color: #484848; }
        [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
        [data-testid="stMetric"] { padding: .8rem 1rem; border: 1px solid #d8d8d8; border-radius: .35rem; }
        .stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {
          background: #202020; color: #fff; border-color: #202020;
        }
        [role="tab"][aria-selected="true"] { color: #171717; }
        [data-baseweb="tab-highlight"] { background: #171717; }
        [data-testid="stAlertContainer"] { background: #f1f1f1; color: #202020; }
        </style>""",
        unsafe_allow_html=True,
    )


def _metric_name(key):
    if key == "human_minutes_per_enquiry":
        return "Active human minutes per request"
    return label(key)


def _number(value):
    return str(value) if value is not None else "Unavailable"


def _timeline_detail(detail):
    if not isinstance(detail, dict):
        return detail or ""
    parts = []
    for field, value in detail.items():
        if value is None:
            continue
        if field == "steps":
            steps = []
            for step in value:
                success = step.get("success")
                status = "ok" if success is True else "failed" if success is False else "unconfirmed"
                if step.get("tool"):
                    steps.append(f"{step['tool']} ({status})")
            value = ", ".join(steps)
        parts.append(f"{label(field)} {value}")
    return " · ".join(parts)


def _readiness(result):
    data = result.get("data_readiness", {})
    groups = result.get("group_metrics", {})
    columns = st.columns(3)
    columns[0].metric("Eligible initial requests", data.get("eligible_roots", 0))
    columns[1].metric("Handling groups", sum(1 for group in groups.values() if group.get("n", 0)))
    quality = result.get("input_quality")
    notices = quality.get("issues", []) if quality else data.get("input_issues", [])
    columns[2].metric("Input issues", len(notices))
    if quality:
        render_input_quality(result)
    readiness = result.get("readiness_assessment", {})
    if readiness:
        st.subheader("What can we measure from these records?")
        st.table([
            {"Result": item["title"], "Evidence": label(item["status"]),
             "Share we can check": format_measure(item.get("coverage"), "rate"), "Evidence check": item["reason"]}
            for item in readiness["capabilities"]
        ])
        st.caption("The share includes both successes and failures we can verify. Pilot accuracy still needs review with the company.")
        with st.expander("Source fields, joins, and extraction gaps"):
            st.dataframe(readiness.get("joins", []), hide_index=True)
            st.json({"tables": readiness.get("tables", []), "issues": readiness.get("issues", [])})
    if data.get("study_period"):
        st.write("**Study period**  " + " to ".join(map(str, data["study_period"])))
    if data.get("data_cutoff"):
        st.write(f"**Evidence cutoff**  {data['data_cutoff']}")
    provenance = result.get("run_provenance", {})
    if provenance.get("policy_version"):
        st.write(f"**Applied grading policy**  {provenance['policy_version']}")
    if data.get("comparison_status"):
        st.write(f"**Comparison readiness**  {label(data['comparison_status'])}")
    exclusions = data.get("exclusion_counts", {})
    if exclusions:
        st.dataframe(
            [{"Exclusion": label(reason), "Initial requests": count} for reason, count in exclusions.items()],
            hide_index=True,
        )
    if data.get("files"):
        with st.expander("Input files and hashes"):
            st.dataframe(data["files"], hide_index=True)
    if not quality and data.get("input_issues"):
        with st.expander("Input issues"):
            st.json(data["input_issues"])
    if result.get("limitations"):
        with st.expander("Limits of the evidence", expanded=True):
            for item in result["limitations"]:
                st.write(item.get("message", item) if isinstance(item, dict) else item)


def _comparisons(result):
    groups = result.get("group_metrics", {})
    st.caption("Verified resolutions at the comparison checkpoint")
    overview = st.columns(3)
    for panel, (arm, metrics) in zip(overview, groups.items()):
        resolution = metrics["verified_resolution_rate"]
        panel.metric(label(arm), format_measure(resolution["value"], resolution["unit"]))
        panel.caption(f"{metrics['n']:,} eligible requests")
    selected_measurements = [
        "verified_resolution_rate", "first_answer_accuracy", "critical_initial_failure_rate",
        "unknown_rate", "human_minutes_per_request", "cost_per_request", "cost_per_verified_resolution",
    ]
    visible = st.toggle("Show all group measures")
    group_rows = []
    for row in metric_rows(result):
        if not visible and row["metric"] not in selected_measurements:
            continue
        value = format_measure(row["value"], row.get("unit"))
        basis = metric_basis(row)
        group_rows.append({
            "Group": label(row["arm"]), "Measure": _metric_name(row["metric"]), "Result": value,
            "Basis": basis, "Coverage": format_measure(row.get("coverage"), "fraction"),
            "Evidence gap": label(row["reason"]) if row.get("reason") else "",
        })
    st.subheader("Service quality, human effort, and costs")
    if group_rows and any(group.get("n") for group in groups.values()):
        st.dataframe(group_rows, hide_index=True, height=390)
    else:
        st.info("This input provides no eligible assigned groups. Individual evidence remains available.")
    st.subheader("Deployment comparisons")
    for comparison in result.get("comparisons", []):
        title = f"{label(comparison['treatment'])} versus {label(comparison['comparator'])}"
        has_groups = bool(comparison.get("comparator_n") and comparison.get("treatment_n"))
        with st.expander(title, expanded=has_groups):
            status = label(comparison.get("status", "unavailable"))
            reason = comparison.get("reason")
            st.write(f"**{status}**  {reason or ''}")
            rows = []
            confidence = result.get("analysis_config", {}).get("confidence_level", 0.95)
            for key, record in comparison.get("metrics", {}).items():
                unit = record.get("unit")
                interval = record.get("interval")
                spread = " to ".join(format_measure(bound, unit) for bound in interval) if interval else "Unavailable"
                bounds = record.get("identification_bounds")
                outer = " to ".join(format_measure(bound, unit) for bound in bounds) if bounds else ""
                rows.append({
                    "Measure": _metric_name(key),
                    "Difference": format_measure(record.get("estimate"), unit),
                    f"{confidence:.0%} sampling interval": spread,
                    "Bounds with unknown outcomes": outer,
                    "Interpretation": ("Randomized estimate" if record.get("causal_interpretation") else
                                       "Unavailable" if record.get("estimate") is None else "Descriptive"),
                    "Evidence gap": label(record["reason"]) if record.get("reason") else "",
                    "Interpretation limit": record.get("interpretation_limit") or "",
                })
            if rows:
                st.dataframe(rows, hide_index=True)
            hours = comparison.get("capacity_hours_per_1000")
            value = comparison.get("capacity_resource_value_per_1000")
            currency = result.get("cost_ledger", {}).get("currency")
            if hours is not None:
                st.write(f"**Capacity released per 1,000 enquiries**  {format_measure(hours, 'hours')}")
            if value is not None:
                st.write(f"**Estimated resource value per 1,000 enquiries**  {format_measure(value, currency)}")
            if comparison.get("diagnostics"):
                st.json(comparison["diagnostics"], expanded=False)
    if not result.get("comparisons"):
        st.info("Comparison results appear when the exports contain an eligible comparison population.")
    diagnostics = result.get("data_readiness", {})
    if diagnostics.get("monthly_trends") or diagnostics.get("rollout_records"):
        with st.expander("Rollout and monthly counts"):
            for field, title in (("monthly_trends", "Monthly results"), ("intake_mix", "Enquiry mix"),
                                 ("rollout_records", "Rollout records")):
                if diagnostics.get(field):
                    st.write(f"**{title}**")
                    st.dataframe(diagnostics[field], hide_index=True)


@st.fragment
def _upgrade_value(result):
    pairs = [
        (item["comparator"], item["treatment"])
        for item in result.get("comparisons", [])
        if item.get("comparator_n") and item.get("treatment_n")
    ]
    if not pairs:
        st.info("Run an evaluation with two eligible handling policies to compare their value.")
        return

    priorities = {
        "verified_resolution_within_target": "Verified resolution within the time target",
        "verified_resolution": "Verified resolution by the end of follow-up",
        "first_answer_accuracy": "Verified correct first answer",
    }
    success_names = {
        "verified_resolution_within_target": "resolution within the time target",
        "verified_resolution": "verified resolution",
        "first_answer_accuracy": "verified correct first answer",
    }
    followup_minutes = result["analysis_config"]["comparison_followup_days"] * 1440
    currency = result.get("cost_ledger", {}).get("currency")
    left, right = st.columns(2)
    comparator, treatment = left.selectbox(
        "Compare handling policies", pairs, format_func=lambda pair: f"{label(pair[1])} vs {label(pair[0])}",
        key="upgrade_pair",
    )
    priority = right.selectbox("Business priority", tuple(priorities), format_func=priorities.get,
                               key="upgrade_priority")
    left, right = st.columns(2)
    target_minutes = left.number_input(
        "Resolution time target (minutes)", min_value=1, max_value=followup_minutes,
        value=60, step=1, key=f"upgrade_target_{followup_minutes}",
        help="Count requests whose resolution was verified and occurred within this many minutes of intake.",
    )
    value = right.number_input(
        f"Value of one additional success ({currency or 'currency'})", min_value=0.0, value=None,
        step=0.50, format="%.2f", placeholder="Optional", key=f"upgrade_value_{priority}_{currency}",
        disabled=currency is None,
        help=f"Enter what one extra {success_names[priority]} is worth beyond costs already in the ledger.",
    )
    assessments = {
        key: assess_upgrade(result, comparator, treatment, key,
                            target_hours=target_minutes / 60 if key == "verified_resolution_within_target" else None,
                            value_per_success=value if key == priority else None)
        for key in priorities
    }
    assessment = assessments[priority]
    change = assessment["success_difference"]
    cost = assessment["incremental_cost_per_request"]
    break_even = assessment["break_even_value_per_success"]
    loss_limit = assessment["max_value_per_lost_success"]
    difference, outcomes, threshold = st.columns(3)
    difference.metric("Cost change per request", format_measure(cost, currency))
    outcomes.metric("Change in verified successes per 1,000", f"{change * 1000:+.1f}" if change is not None else "Unavailable")
    threshold.metric("Break-even value per extra success" if loss_limit is None else "Break-even value per lost success",
                     format_measure(break_even if loss_limit is None else loss_limit, currency))
    decision_panel = st.container()

    if assessment["break_even_value_bounds"] is not None:
        lower, upper = assessment["break_even_value_bounds"]
        if upper is None:
            st.caption(f"Break-even starts at {format_measure(lower, currency)} in the most favorable case. "
                       "The gain could disappear once the unknown outcomes are resolved.")
        else:
            st.caption(f"The break-even range from missing outcomes is {format_measure(lower, currency)} to "
                       f"{format_measure(upper, currency)} per extra success.")
    if loss_limit is not None:
        st.caption("The treatment cost less and had fewer verified successes. The threshold is the most one lost "
                   "success could be worth before it outweighs the modeled savings at the observed rates.")
    elif cost is not None and change is not None and cost > 0 and change <= 0:
        st.caption("The verified results show higher cost without a gain on this priority.")
    elif cost is not None and change is not None and cost <= 0 and change >= 0:
        st.caption("The verified results show no extra cost and no loss on this priority.")
    if cost is None:
        st.warning("A cost comparison needs complete costs in one currency for both handling policies.")
    elif assessment["estimated_costs"]:
        st.caption("Cost includes modeled resource use or allocations. Use the ledger to check those assumptions.")
    if assessment["comparison_status"] != "randomized_assignment":
        st.caption("The comparison describes the observed groups. Check the study design before attributing a difference to the upgrade.")

    net = assessment["net_value_per_request"]
    if net is not None:
        st.write(f"**Illustrative net value per request**  {format_measure(net, currency)}")
        lower, upper = assessment["net_value_bounds"]
        st.caption(f"Possible range with the same costs and value assumption: {format_measure(lower, currency)} "
                   f"to {format_measure(upper, currency)} per request.")
        if assessment["status"] == "inconclusive_missing_evidence":
            st.warning("The unknown outcomes leave the cost justification uncertain at the value entered.")
        elif assessment["status"] == "modeled_benefit_exceeds_cost":
            st.write("The treatment yields higher modeled value on this priority throughout the range.")
        elif assessment["status"] == "modeled_cost_exceeds_benefit":
            st.write("The treatment yields lower modeled value on this priority throughout the range.")
        elif assessment["status"] == "modeled_break_even":
            st.write("The two policies break even on this priority at the value entered.")
    elif cost is not None:
        st.caption("Enter your value per success to see how it compares with the change in cost.")

    rows = []
    for key, item in assessments.items():
        delta_bounds = item["success_difference_bounds"]
        rows.append({
            "Outcome": priorities[key],
            **{
                label(arm): (f"{data['successes']:,}/{data['eligible']:,} verified · {data['unknown']:,} unknown")
                for arm, data in item["metrics"].items()
            },
            "Change with unknowns": (" to ".join(format_measure(endpoint * 100, "pp") for endpoint in delta_bounds)
                                     if delta_bounds is not None else "Unavailable"),
        })
    st.dataframe(rows, hide_index=True)
    st.caption("Each row uses all eligible requests. The ranges show how missing outcomes could change the "
               "comparison. Sampling uncertainty and the value of other outcomes are outside those ranges.")
    critical_checks = []
    for arm in (comparator, treatment):
        failures = result["group_metrics"][arm].get("critical_initial_failure_rate", {})
        if failures.get("denominator"):
            critical_checks.append(f"{label(arm)} {failures['numerator']}/{failures['denominator']}")
    if critical_checks:
        st.caption("Critical first failures among assessable requests · " + " · ".join(critical_checks))
    with st.expander("Financial downside of wrong answers"):
        st.write("Test what happens if wrong answers lead to extra charges, such as a failed truck trip or compensation.")
        loss = st.number_input(
            f"Assumed additional loss per 1,000 enquiries ({currency or 'currency'})",
            min_value=0.0, value=None, step=100.0, placeholder="Optional", disabled=cost is None,
            key=f"error_loss_{comparator}_{treatment}_{currency}",
            help="Enter the extra loss for the selected policy relative to the comparator. Count only costs outside the ledger and the entered value per success.",
        )
        if loss is not None and cost is not None:
            scenario = assess_error_loss_scenario(assessment, loss)
            assessment["error_loss_scenario"] = scenario
            st.metric("Cost change per request with assumed loss",
                      format_measure(scenario["cost_change_with_loss_per_request"], currency))
            if scenario["net_value_with_loss_bounds"] is not None:
                st.metric("Illustrative net value per request with assumed loss",
                          format_measure(scenario["net_value_with_loss_per_request"], currency))
                low, high = scenario["net_value_with_loss_bounds"]
                st.caption(f"Range with missing service outcomes {format_measure(low, currency)} to "
                           f"{format_measure(high, currency)} per request.")
            st.caption("The entered amount is hypothetical. If it could erase a favorable result, the recommendation asks for evidence before expanding.")
        elif cost is None:
            st.caption("Comparable scoped costs are needed to calculate this scenario.")
    with decision_panel:
        _render_decision(result, assessment, additional_loss_per_1000=loss if cost is not None else None)
    st.download_button("Download value assessment", json.dumps(assessment, indent=2, allow_nan=False),
                       file_name="upgrade_value.json", mime="application/json", on_click="ignore")


def _render_decision(result, assessment, *, additional_loss_per_1000=None):
    st.subheader("Decision and next action")
    if (result.get("input_quality") or {}).get("review_required", {}).get("required"):
        st.warning("Data issues need review before expansion. See Data readiness for the affected records.")
    left, right = st.columns(2)
    limit = left.number_input("Maximum critical failure rate (%)", min_value=0.0, max_value=100.0,
                              value=None, step=0.5, key="decision_critical_limit", placeholder="Set a limit",
                              help="Use the limit agreed with the service owner. Unknown results can increase the possible failure rate.")
    basis = right.selectbox("Basis for the value per success", list(VALUE_BASES),
                            format_func=VALUE_BASES.get, key="decision_value_basis",
                            disabled=assessment["value_per_success"] is None)
    value_evidence = None
    if basis != "illustrative" and assessment["value_per_success"] is not None:
        value_evidence = st.text_input("Source or assumption for this business value", max_chars=280,
                                       key="decision_value_evidence",
                                       help="Give a short reference to the finance record or approved estimate. Leave out private details.")
    decision = assess_recommendation(
        result, assessment["comparator"], assessment["treatment"], assessment["priority"],
        target_hours=assessment["target_hours"], value_per_success=assessment["value_per_success"],
        value_basis=basis if assessment["value_per_success"] is not None else None,
        value_evidence=value_evidence,
        max_critical_rate=limit / 100 if limit is not None else None,
        additional_loss_per_1000=additional_loss_per_1000,
    )
    st.markdown(f"**{decision['title']}**")
    st.write(decision["reason"])
    st.write(decision["next_step"])
    st.write(f"**Suggested reviewers**  {decision['suggested_reviewer']}")
    st.write(f"**What would change the recommendation**  {decision['reconsider_when']}")
    failure_reviews = decision["failure_reviews"]
    if failure_reviews:
        st.markdown(f"**What failed under {label(assessment['treatment'])}**")
        for review in failure_reviews:
            count = len(review["cases"])
            st.write(f"**{review['finding']} · {count:,} {'enquiry' if count == 1 else 'enquiries'}**")
            st.write(review["action"])
            st.caption(review["retest"])
    if decision["unclassified_failure_episode_ids"]:
        st.caption("Some verified critical failures still need a case-level review to identify what to retest.")
    critical = decision["critical_check"]
    if critical["bounds"]:
        lower, upper = (format_measure(value, "rate") for value in critical["bounds"])
        st.caption(f"Possible critical failure rate in this sample: {lower} to {upper}. "
                   f"{critical['verified_failures']:,} verified, {critical['unknown']:,} unknown, {critical['eligible']:,} eligible.")
    if decision["net_uncertainty"]:
        interval = decision["net_uncertainty"]
        lower, upper = (format_measure(value, assessment["currency"]) for value in interval["bounds"])
        st.caption(f"Modeled net value range with sampling and missing outcomes: {lower} to {upper} per request "
                   f"({interval['confidence_level']:.0%} clustered bootstrap).")
        if interval["critical_upper"] is not None:
            st.caption(f"Upper critical failure estimate including unknowns and sampling: "
                       f"{format_measure(interval['critical_upper'], 'rate')}.")
        st.caption("The range holds the selected value and cost allocation rules fixed.")
    elif decision["uncertainty_gap"]:
        st.caption(decision["uncertainty_gap"])
    loss_scenario = decision["downstream_loss_scenario"]
    if loss_scenario and loss_scenario["sampling_net_value_bounds"] is not None:
        lower, upper = (format_measure(value, assessment["currency"]) for value in loss_scenario["sampling_net_value_bounds"])
        st.caption(f"With the assumed downstream loss, the modeled range is {lower} to {upper} per request.")
    st.caption("The service owner reviews the recommendation. Synthetic examples illustrate the decision rules.")
    with st.expander("Decision evidence and downloads"):
        if critical["failure_episode_ids"]:
            examples = critical["failure_episode_ids"][:8]
            st.write("**Verified critical enquiry IDs**  " + ", ".join(examples))
            st.caption("Find an ID in Enquiry evidence. The result file includes the full list.")
        if critical["unknown_episode_ids"]:
            st.write("**Enquiry IDs with unknown critical checks**  " + ", ".join(critical["unknown_episode_ids"][:8]))
        if failure_reviews:
            st.dataframe([
                {"Finding": review["finding"], "Enquiry": case["enquiry_id"], "Source records": ", ".join(case["refs"])}
                for review in failure_reviews for case in review["cases"][:5]
            ], hide_index=True)
        left, right = st.columns(2)
        left.download_button("Download decision brief", render_decision_brief(decision),
                             file_name="shipment_ai_decision.html", mime="text/html", on_click="ignore")
        right.download_button("Download decision evidence", json.dumps(decision, indent=2, allow_nan=False),
                              file_name="shipment_ai_decision.json", mime="application/json", on_click="ignore")


def _reply_details(verification):
    rows = []
    for key, phase in (("initial_reply", "First answer"), ("last_reply", "Latest answer")):
        reply = verification.get(key)
        if reply:
            actor = reply.get("actor_id") or label(reply.get("actor_type") or "unknown")
            rows.append({
                "Phase": phase,
                "Sent": reply.get("sent_at") or "Unknown",
                "Actor": actor,
                "Verdict": label(reply.get("verdict") or "unknown"),
                "Evidence": ", ".join(reply.get("refs", [])),
            })
    if rows:
        st.dataframe(rows, hide_index=True)


def _enquiry_evidence(result):
    enquiries = result.get("enquiries", [])
    if not enquiries:
        st.info("This input contains no enquiries to inspect.")
        return
    query = st.text_input("Find an enquiry", placeholder="Enter an enquiry ID")
    recovery_only = st.checkbox("Show verified human recoveries")
    matches = [
        record for record in enquiries
        if query.strip().casefold() in record["enquiry_id"].casefold()
        and (not recovery_only or record.get("verification", {}).get("human_recovery") is True)
    ]
    if not matches:
        st.info("No enquiries match these filters.")
        return
    by_id = {record["enquiry_id"]: record for record in matches}
    selected = st.selectbox("Enquiry", options=list(by_id))
    record = by_id[selected]
    checkpoint = record.get("checkpoint_result")
    episode = next((item for item in result.get("episodes", [])
                    if selected in item.get("all_contacts", item.get("contacts", []))), None)
    if episode and episode.get("assigned_arm"):
        st.caption(f"Assigned policy {label(episode['assigned_arm'])} · Initial enquiry {episode['root_enquiry_id']}")
    scope = st.radio("Observation", ["Latest available evidence", "Comparison checkpoint"], horizontal=True) if checkpoint else None
    assessment = checkpoint if scope == "Comparison checkpoint" else record
    verification = assessment.get("verification", {})
    outcome = assessment.get("outcome", {})
    columns = st.columns(3)
    columns[0].metric("Service outcome", label(outcome.get("state") or "unknown"))
    failure = assessment.get("initial_failure")
    first = verification.get("initial_reply") or {}
    identity = assessment.get("criteria", {}).get("shipment_identity", {})
    ai_identity_failure = (failure is True and first.get("actor_type") == "ai_agent"
                           and identity.get("passed") is False and identity.get("severity") == "critical")
    failure_label = "Initial AI critical failure" if ai_identity_failure else "Initial critical failure"
    columns[1].metric(failure_label, "Unknown" if failure is None else "Yes" if failure else "No")
    recovery = verification.get("human_recovery")
    columns[2].metric("Human recovery", "Unknown" if recovery is None else "Verified" if recovery else "No")
    if ai_identity_failure and recovery is True:
        st.warning("The AI made a critical error in its first answer. A human corrected it and resolved the enquiry. "
                   "The error still counts against the AI.")
    if outcome.get("reason"):
        st.caption(outcome["reason"])
    if outcome.get("refs"):
        st.write("**Outcome evidence**  " + ", ".join(outcome["refs"]))
    _reply_details(verification)
    checks = []
    for key, grade in assessment.get("criteria", {}).items():
        error = grade.get("eta_error_seconds")
        delay = grade.get("delay_seconds")
        checks.append({
            "Check": _metric_name(key),
            "Result": label(grade.get("status") or "unknown"),
            "Severity": label(grade.get("severity") or "unknown"),
            "ETA error (s)": error,
            "Overdue (s)": delay,
            "Reason": grade.get("reason") or "",
            "Source records": ", ".join(grade.get("refs", [])),
        })
    if checks:
        st.subheader("Verification checks")
        st.dataframe(checks, hide_index=True)
    actions = case_review_actions(assessment)
    if actions:
        st.subheader("What to review and retest")
        for action in actions:
            st.write(action["action"])
            st.caption(action["retest"])
            st.caption("Source records · " + ", ".join(action["refs"]))
    work = verification.get("human_work", {})
    if work:
        st.write(f"**Active human work**  {format_measure(work.get('active_seconds'), 'seconds')}")
        if work.get("active_seconds") is None and work.get("recorded_seconds") is not None:
            st.write(f"**Documented subtotal**  {format_measure(work['recorded_seconds'], 'seconds')}")
        if work.get("refs"):
            st.write("**Work records**  " + ", ".join(work["refs"]))
        if work.get("unmeasured_refs"):
            st.caption("These records do not establish active time. They are excluded from measured effort and labour cost. "
                       + ", ".join(work["unmeasured_refs"]))
    timeline = assessment.get("timeline") or (record.get("timeline") if scope != "Comparison checkpoint" else None)
    if timeline is None and episode and episode.get("checkpoint"):
        boundary = episode["checkpoint"]
        timeline = [event for event in record.get("timeline", []) if event["at"] <= boundary]
    if timeline:
        st.subheader("Evidence timeline")
        st.dataframe([
            {"When": event["at"], "Event": event["event"], "Actor": event.get("actor_id"),
             "Detail": _timeline_detail(event.get("detail")), "Source": event.get("ref")}
            for event in timeline
        ], hide_index=True)
    with st.expander("Full enquiry result"):
        st.json(assessment)


def _costs(result):
    ledger = result.get("cost_ledger", {})
    currency = ledger.get("currency")
    cash = ledger.get("realized_cash_savings")
    cash_measure = cash.get("value") if isinstance(cash, dict) else cash
    st.write(f"**Realized cash savings**  {format_measure(cash_measure, currency)}")
    cash_reason = cash.get("reason") if isinstance(cash, dict) else ledger.get("cash_savings_reason")
    if cash_reason:
        st.caption(cash_reason)
    entries = ledger.get("entries", [])
    if entries:
        summary = {}
        for entry in entries:
            key = (entry.get("category") or "unclassified", entry.get("currency") or "unknown",
                   entry.get("scope") or "unknown")
            if entry.get("amount") is not None:
                summary[key] = summary.get(key, Decimal(0)) + Decimal(str(entry["amount"]))
        st.dataframe(
            [{"Category": label(category), "Currency": unit, "Scope": label(scope),
              "Documented amount": f"{amount:,.2f}"}
             for (category, unit, scope), amount in sorted(summary.items())],
            hide_index=True,
        )
        st.caption(f"Showing {min(200, len(entries)):,} of {len(entries):,} entries. The download contains the full ledger.")
        display_entries = [{key: _number(value) if isinstance(value, (list, dict)) else value
                            for key, value in entry.items()} for entry in entries[:200]]
        st.dataframe(display_entries, hide_index=True)
    else:
        st.info("No attributable costs could be calculated from this input.")
    if ledger.get("reconciliation"):
        with st.expander("Invoice reconciliation"):
            st.json(ledger["reconciliation"])
    if ledger.get("staffing"):
        with st.expander("Recorded staffing"):
            st.dataframe(ledger["staffing"], hide_index=True)
    if ledger.get("issues"):
        with st.expander("Cost evidence gaps"):
            st.json(ledger["issues"])
    if ledger.get("full_deployment_scenario"):
        forecast = ledger["full_deployment_scenario"]
        st.write(f"**Full deployment forecast**  {format_measure(forecast.get('total_cost'), currency)}")
        if forecast.get("reason"):
            st.caption(forecast["reason"])
    assumptions = result.get("analysis_config", {})
    if assumptions:
        with st.expander("Analysis settings used"):
            st.json(assumptions)


def _render_downloads(result, policy):
    def prepare():
        st.session_state["shipment_downloads"] = make_downloads(result)

    formats = st.session_state.get("shipment_downloads")
    with st.expander("Download and save results", expanded=bool(formats)):
        st.button("Prepare downloads", on_click=prepare)
        if formats:
            for title, filename, mime in (
                ("Download full results", "analysis.json", "application/json"),
                ("Download group metrics", "group_metrics.csv", "text/csv"),
                ("Download cost ledger", "cost_ledger.csv", "text/csv"),
                ("Download summary", "summary.html", "text/html"),
            ):
                st.download_button(title, formats[filename], filename, mime, on_click="ignore")
        if st.button("Save run bundle"):
            try:
                destination = write_run_bundle(RUNS, result, policy)
                st.success(f"Saved {destination.name}.")
            except (OSError, ValueError) as error:
                st.error(str(error))


def main():
    st.set_page_config(page_title="Shipment AI value evaluator", layout="wide")
    _apply_theme()
    st.title("Shipment AI value evaluator")
    render_company_import()
    demos = _available_demos()
    settings = st.session_state.get("shipment_settings", DEFAULT_CONFIG)
    with st.form("shipment_analysis_controls"):
        source, horizon, resamples = st.columns([3, 1, 1], vertical_alignment="bottom")
        dataset = source.selectbox("Evidence source", [*demos, UPLOAD], key="shipment_source")
        days = horizon.number_input(
            "Follow-up days", min_value=1, max_value=365, value=settings["comparison_followup_days"], step=1,
            help="Observe each initial request for the same number of days before comparing the groups.",
        )
        samples = resamples.number_input(
            "Bootstrap samples", min_value=200, max_value=10000, value=settings["bootstrap_resamples"], step=100,
            help="Repeated draws of existing customers estimate sampling uncertainty. Each request keeps its assigned handling group.",
        )
        upload = st.file_uploader(
            "Optional exports ZIP", type=["zip"],
            help="Select Upload an exports ZIP as the evidence source to analyze an upload.",
        )
        with st.expander("Company service rules"):
            policy_upload = st.file_uploader("Grading policy (optional JSON)", type=["json"], key="company_policy")
            st.caption("Use the company-approved service rules for a pilot. The bundled rules are synthetic benchmark settings.")
        submitted = st.form_submit_button("Run evaluation", type="primary")
    if submitted:
        st.session_state.pop("shipment_analysis", None)
        st.session_state.pop("shipment_downloads", None)
        config = {**DEFAULT_CONFIG, "comparison_followup_days": int(days), "bootstrap_resamples": int(samples)}
        try:
            if policy_upload is not None and policy_upload.size > 2 * 1024**2:
                raise ValueError("The grading policy exceeds 2 MiB.")
            policy = json.loads(policy_upload.getvalue().decode("utf-8-sig")) if policy_upload is not None else json.loads(POLICY.read_text(encoding="utf-8"))
            _settings(policy)
            for profile in policy.get("profiles", {}):
                grade_enquiry(policy, {"enquiry_id": "policy-validation", "profile": profile})
            with st.spinner("Checking records and comparing handling policies"):
                if dataset == UPLOAD:
                    if upload is None:
                        raise ValueError("Choose an exports ZIP before running the evaluation.")
                    with unpack_exports(upload.getvalue()) as path:
                        result = analyze_exports(path, policy, config)
                else:
                    result = analyze_exports(demos[dataset], policy, config)
            st.session_state["shipment_analysis"] = (result, dataset, policy)
            st.session_state["shipment_settings"] = config
        except (OSError, ValueError, TypeError, OverflowError) as error:
            st.error(str(error))
    result_state = st.session_state.get("shipment_analysis")
    if result_state is None:
        st.write("Choose a demonstration dataset or upload operational exports to start.")
        return
    result, dataset_name, policy = result_state
    origin = result.get("data_readiness", {}).get("dataset_origin")
    if origin == "synthetic" or dataset_name in DEMONSTRATIONS:
        st.info("Synthetic demonstration. Results apply to the simulated workflow.")
    else:
        st.info("Imported exports. The evidence checks below show which comparisons are supported.")
    st.caption(f"{dataset_name} · {result.get('analysis_config', {}).get('comparison_followup_days', '?')} days of comparison follow-up")
    ready, compare, value, enquiry, costs = st.tabs([
        "Data readiness", "Comparison", "Upgrade value", "Enquiry evidence", "Costs and settings",
    ])
    with ready:
        _readiness(result)
    with compare:
        _comparisons(result)
    with value:
        _upgrade_value(result)
    with enquiry:
        _enquiry_evidence(result)
    with costs:
        _costs(result)
    _render_downloads(result, policy)


if __name__ == "__main__":
    main()
