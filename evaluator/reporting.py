"""Create portable or on-disk results from the same analysis payload."""

import csv
from hashlib import sha256
from html import escape
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
import json
from pathlib import Path
from platform import python_version
from tempfile import TemporaryDirectory


ARM_NAMES = {
    "human_baseline": "Human handling",
    "agent_v1": "Agent v1",
    "agent_v2": "Agent v2",
}
METRIC_NAMES = {
    "verified_resolution_rate": "Verified resolutions",
    "first_answer_accuracy": "First answers matching the record",
    "critical_initial_failure_rate": "Critical initial failures",
    "unknown_rate": "Unknown outcomes",
    "human_minutes_per_request": "Active human minutes per request",
    "cost_per_request": "Cost per request",
    "cost_per_verified_resolution": "Cost per verified resolution",
}
SUMMARY_METRICS = tuple(METRIC_NAMES)


def label(key):
    return ARM_NAMES.get(key) or METRIC_NAMES.get(key) or str(key).replace("_", " ").capitalize()


def format_measure(value, unit):
    if value is None:
        return "Unavailable"
    if not isinstance(value, (int, float)):
        return str(value)
    if unit in {"fraction", "proportion", "rate"}:
        return f"{value:.1%}"
    if unit in {"percentage_points", "percentage points", "pp"}:
        return f"{value:+.2f} pp"
    suffix = f" {unit}" if unit else ""
    return f"{value:,.2f}{suffix}" if isinstance(value, float) else f"{value:,}{suffix}"


def render_decision_brief(decision):
    """Create a print-ready summary without copying enquiry transcripts."""
    from .recommendation import VALUE_BASES

    value = decision["value_assessment"]
    risk = decision["critical_check"]
    interval = decision["net_uncertainty"]
    currency = value["currency"]
    risk_text = " to ".join(format_measure(item, "rate") for item in risk["bounds"] or ()) or "Unavailable"
    uncertainty = decision["uncertainty_gap"] or "Unavailable for the selected evidence and assumptions"
    if interval:
        bounds = " to ".join(format_measure(item, currency) for item in interval["bounds"])
        uncertainty = f"{bounds} per request · {interval['confidence_level']:.0%} clustered bootstrap range"
    facts = [
        ("Policies", f"{label(value['treatment'])} compared with {label(value['comparator'])}"),
        ("Business priority", label(value["priority"])),
        ("Resolution target", f"{value['target_hours'] * 60:g} minutes" if value["target_hours"] else "Not selected"),
        ("Critical cases", f"{risk['verified_failures']} verified, {risk['unknown']} unknown, {risk['eligible']} eligible"),
        ("Possible critical failure rate in this sample", risk_text),
        ("Sample critical failure limit", format_measure(risk["limit"], "rate")),
        ("Cost change per request", format_measure(value["incremental_cost_per_request"], currency)),
        ("Break-even per additional success", format_measure(value["break_even_value_per_success"], currency)),
        ("Value per additional success", format_measure(value["value_per_success"], currency)),
        ("Basis for business value", VALUE_BASES.get(decision["value_basis"], "Not supplied")),
        ("Modeled net value range", uncertainty),
    ]
    if decision.get("value_evidence"):
        facts.insert(-1, ("Value evidence supplied by reviewer", decision["value_evidence"]))
    loss_scenario = decision.get("downstream_loss_scenario")
    if loss_scenario:
        facts.append(("Assumed additional loss per 1,000 enquiries",
                      format_measure(loss_scenario["additional_loss_per_1000_requests"], currency)))
        if loss_scenario["sampling_net_value_bounds"] is not None:
            adjusted_range = " to ".join(format_measure(amount, currency)
                                         for amount in loss_scenario["sampling_net_value_bounds"])
            facts.append(("Modeled net value after assumed loss", f"{adjusted_range} per request"))
    review = decision.get("input_quality_review")
    if review and review.get("required"):
        facts.append(("Unresolved data",
                      f"{review['population_issues']} rows affecting eligibility, "
                      f"{review['unresolved_critical_issues']} rows that could change a critical check. "
                      "See the data issues register before expanding."))
    table = "".join(f"<tr><th scope='row'>{escape(name)}</th><td>{escape(item)}</td></tr>" for name, item in facts)
    action_details = "".join(
        f"<p><strong>{heading}</strong> {escape(decision[key])}</p>"
        for key, heading in (("suggested_reviewer", "Suggested reviewers"),
                             ("reconsider_when", "What would change the recommendation")) if decision.get(key)
    )
    failure_reviews = []
    for finding in decision.get("failure_reviews", []):
        cases = finding["cases"]
        examples = ", ".join(case["enquiry_id"] for case in cases[:5])
        case_count = f"{len(cases):,} {'enquiry' if len(cases) == 1 else 'enquiries'}"
        failure_reviews.append(f"<li><strong>{escape(finding['finding'])} ({case_count})</strong> "
                               f"{escape(finding['action'])} {escape(finding['retest'])} "
                               f"Example enquiries {escape(examples)}.</li>")
    failure_summary = ("<h2>Critical findings and proposed retests</h2><ul>" + "".join(failure_reviews) + "</ul>"
                       if failure_reviews else "")
    origin = decision["dataset_origin"]
    notice = "Synthetic demonstration. The example does not measure company performance." if origin == "synthetic" else f"Dataset origin declared as {origin}."
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shipment AI evaluation decision</title><style>
body {{max-width: 50rem; margin: 2.5rem auto; padding: 0 1.5rem; color: #171717; font: 1rem/1.45 system-ui, sans-serif}}
h1 {{line-height: 1.1}} h2 {{margin-bottom: .4rem}} table {{width: 100%; border-collapse: collapse}}
th, td {{text-align: left; padding: .45rem; vertical-align: top; border-bottom: 1px solid #b8b8b8}}
th {{width: 43%}} small {{display: block; margin-top: 1.1rem}}
@page {{margin: 17mm}} @media print {{body {{max-width: none; margin: 0; padding: 0; font-size: 10pt}}}}
</style><body><header><h1>Shipment AI evaluation decision</h1><p>{escape(notice)}</p></header>
<main><h2>{escape(decision['title'])}</h2><p>{escape(decision['reason'])}</p><p>{escape(decision['next_step'])}</p>
{action_details}{failure_summary}<table>{table}</table><small>Analysis run {escape(str(decision['source_run_id'] or 'unavailable'))}. The value range uses the supplied value and existing cost scope. The critical failure check applies to this sample. A service owner reviews the recommendation.</small>
</main></body></html>""".encode("utf-8")


def _json(payload):
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    return (body + "\n").encode("utf-8")


def _csv_cell(value):
    if isinstance(value, (list, tuple, dict)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv(rows, leading_fields):
    buffer = StringIO(newline="")
    extra = sorted({key for row in rows for key in row}.difference(leading_fields))
    writer = csv.DictWriter(buffer, fieldnames=[*leading_fields, *extra])
    writer.writeheader()
    writer.writerows({key: _csv_cell(value) for key, value in row.items()} for row in rows)
    return buffer.getvalue().encode("utf-8-sig")


def input_quality_csv(result):
    """List affected locations with source and export denominators kept separate."""
    return _csv(result.get("input_quality", {}).get("issues", ()),
                ("basis", "filename", "row_number", "record_id", "kind", "field",
                 "impact", "enquiry_ids", "source_ref", "detail", "table"))


def metric_rows(result):
    rows = []
    for arm, metrics in result.get("group_metrics", {}).items():
        for key, record in metrics.items():
            if isinstance(record, dict) and "value" in record:
                rows.append({"arm": arm, "metric": key, **record})
    return rows


def metric_basis(row):
    """Describe the aggregate using the same units as its displayed value."""
    numerator, denominator = row.get("numerator"), row.get("denominator")
    if numerator is None or denominator is None:
        return "Unavailable" if denominator is None else str(denominator)
    if row.get("metric") in {
        "human_minutes_per_request", "human_minutes_per_request_assessable", "mean_elapsed_resolution_minutes",
    }:
        return f"{numerator / 60:,.2f} minutes / {denominator:,} requests"
    if row.get("metric") in {"cost_per_request", "cost_per_verified_resolution"}:
        return f"{numerator:,.2f} {row.get('unit', '')} / {denominator:,}"
    return f"{numerator} / {denominator}"


def _html_table(headers, rows):
    head = "".join(f"<th scope='col'>{escape(str(value))}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _summary_html(result):
    readiness = result.get("data_readiness", {})
    config = result.get("analysis_config", {})
    provenance = result.get("run_provenance", {})
    origin = readiness.get("dataset_origin")
    origin_label = "Synthetic demonstration" if origin == "synthetic" else "Imported exports"
    period = readiness.get("study_period") or []
    period_label = " to ".join(map(str, period)) if len(period) == 2 else "Unavailable"
    summary_rows = []
    for row in metric_rows(result):
        if row["metric"] not in SUMMARY_METRICS:
            continue
        basis = metric_basis(row)
        summary_rows.append((
            label(row["arm"]), label(row["metric"]), format_measure(row["value"], row.get("unit")),
            basis if basis is not None else "Unavailable", row.get("reason") or "",
        ))

    comparison_rows = []
    for comparison in result.get("comparisons", []):
        name = f"{label(comparison['treatment'])} vs {label(comparison['comparator'])}"
        for metric, record in comparison.get("metrics", {}).items():
            if metric not in SUMMARY_METRICS:
                continue
            unit = record.get("unit")
            interval = record.get("interval")
            limits = " to ".join(format_measure(bound, unit) for bound in interval) if interval else "Unavailable"
            bounds = record.get("identification_bounds")
            coverage_bounds = " to ".join(format_measure(bound, unit) for bound in bounds) if bounds else ""
            estimate = record.get("estimate")
            interpretation = (
                "Randomized estimate" if record.get("causal_interpretation") else
                "Unavailable" if estimate is None else "Descriptive"
            )
            reason = " ".join(label(value) for value in (
                record.get("reason") or comparison.get("reason"), record.get("interpretation_limit"),
            ) if value)
            comparison_rows.append((
                name, label(metric), format_measure(estimate, unit), limits, coverage_bounds, interpretation, reason,
            ))
    ledger = result.get("cost_ledger", {})
    capabilities = result.get("readiness_assessment", {}).get("capabilities", [])
    evidence_table = _html_table(("Result", "Evidence", "Coverage", "Review needed"), [
        (item["title"], label(item["status"]), format_measure(item.get("coverage"), "rate"),
         " ".join(item.get("next_steps", []))) for item in capabilities
    ]) if capabilities else ""
    quality = result.get("input_quality", {})
    quality_summary = quality.get("summary", {})
    review = quality.get("review_required", {})
    quality_html = ""
    if quality_summary:
        quality_html = ("<h2>Input data quality</h2><p>"
                        f"{quality_summary['affected_rows']:,} of {quality_summary['input_rows']:,} delivered rows "
                        f"had issues ({format_measure(quality_summary['affected_fraction'], 'rate')}). "
                        "The denominator excludes records that were never supplied.</p>")
        if review.get("required"):
            quality_html += "<p>Review the listed records before considering expansion.</p>"
    cash = ledger.get("realized_cash_savings")
    if isinstance(cash, dict):
        cash_text = format_measure(cash.get("value"), ledger.get("currency"))
    else:
        cash_text = format_measure(cash, ledger.get("currency"))
    confidence = config.get("confidence_level", 0.95)
    comparison_headings = (
        "Comparison", "Measure", "Difference", f"{confidence:.0%} sampling interval",
        "Bounds with unknown outcomes", "Interpretation", "Reason",
    )
    limitations = "".join(
        f"<li>{escape(str(item.get('message', item)) if isinstance(item, dict) else str(item))}</li>"
        for item in result.get("limitations", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shipment AI value evaluation</title>
<style>
body {{ max-width: 72rem; margin: 2rem auto; padding: 0 1.2rem; color: #151515;
  background: #fff; font: 15px/1.5 system-ui, sans-serif; }}
h1 {{ font-size: clamp(1.6rem, 4vw, 2.5rem); margin-bottom: .25rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid #d4d4d4; text-align: left; padding: .45rem .55rem; vertical-align: top; }}
th {{ color: #fff; background: #222; }}
.table {{ overflow: auto; }}
@media print {{ body {{ margin: 0; padding: 0; font-size: 11pt; }}
  th {{ color: #151515; background: #fff; }} tr {{ break-inside: avoid; }} }}
</style>
</head>
<body>
<main>
<h1>Shipment AI value evaluation</h1>
<p><strong>{origin_label}</strong></p>
<p>Study period {escape(period_label)}. Follow-up {escape(str(config.get('comparison_followup_days', 'unavailable')))} days.
Eligible initial requests {escape(str(readiness.get('eligible_roots', 'unavailable')))}.</p>
<p>Analysis {escape(str(provenance.get('run_id') or 'unavailable'))}.
Grading policy {escape(str(provenance.get('policy_version') or 'unavailable'))}.</p>
{f'<h2>Evidence readiness</h2><div class="table">{evidence_table}</div>' if evidence_table else ''}
{quality_html}
<h2>Service quality, human effort, and cost</h2>
<div class="table">{_html_table(('Group', 'Measure', 'Result', 'Basis', 'Evidence gap'), summary_rows)}</div>
<h2>Deployment comparisons</h2>
<p>Differences are treatment minus comparator. Bounds show how missing outcomes can change the difference.</p>
<div class="table">{_html_table(comparison_headings, comparison_rows)}</div>
<p>Realized cash savings {escape(cash_text)}.</p>
{f'<h2>Limits of the evidence</h2><ul>{limitations}</ul>' if limitations else ''}
</main>
</body>
</html>
"""


def make_downloads(result):
    """Render the same analysis for machine use, a spreadsheet, and review."""
    ledger = result.get("cost_ledger", {})
    entries = ledger.get("entries", [])
    downloads = {
        "analysis.json": _json(result),
        "group_metrics.csv": _csv(
            metric_rows(result), ("arm", "metric", "value", "unit", "numerator", "denominator", "coverage"),
        ),
        "cost_ledger.csv": _csv(
            entries, ("period", "category", "currency", "amount", "root_enquiry_id", "scope", "refs"),
        ),
        "summary.html": _summary_html(result).encode("utf-8"),
    }
    if "input_quality" in result:
        downloads["input_quality.csv"] = input_quality_csv(result)
    return downloads


def _dependencies():
    runtime = {"python": python_version()}
    for package in ("numpy", "scipy", "streamlit", "pydantic", "PyYAML", "tzdata"):
        try:
            runtime[package] = version(package)
        except PackageNotFoundError:
            continue
    return runtime


def write_run_bundle(output_dir, result, policy):
    """Publish a complete, content-addressed bundle with an atomic directory rename."""
    parent = Path(output_dir)
    parent.mkdir(parents=True, exist_ok=True)
    artifacts = make_downloads(result)
    artifacts["policy.json"] = _json(policy)
    artifacts["analysis_config.json"] = _json(result.get("analysis_config", {}))
    manifest = {
        "schema_version": result.get("schema_version"),
        "provenance": result.get("run_provenance", {}),
        "dependencies": _dependencies(),
        "report_metadata": {"summary": "summary.html", "analysis_scope": result.get("limitations", [])},
        "test_metadata": result.get("test_metadata", {}),
        "artifacts": {name: sha256(content).hexdigest() for name, content in artifacts.items()},
    }
    manifest_content = _json(manifest)
    bundle_id = sha256(manifest_content).hexdigest()[:24]
    artifacts["manifest.json"] = manifest_content
    destination = parent / f"run-{bundle_id}"

    def verify_existing():
        if destination.is_symlink() or not destination.is_dir():
            raise FileExistsError(f"The bundle destination is occupied: {destination}")
        actual_names = {path.name for path in destination.iterdir()}
        if actual_names != set(artifacts):
            raise FileExistsError(f"Existing bundle contents differ: {destination}")
        for name, expected in artifacts.items():
            artifact = destination / name
            if artifact.is_symlink() or not artifact.is_file() or artifact.read_bytes() != expected:
                raise FileExistsError(f"Existing bundle content differs: {artifact}")

    if destination.exists() or destination.is_symlink():
        verify_existing()
        return destination
    with TemporaryDirectory(dir=parent, prefix=".staging-") as temporary:
        staged = Path(temporary) / "bundle"
        staged.mkdir()
        for name, content in artifacts.items():
            (staged / name).write_bytes(content)
        try:
            staged.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            verify_existing()
    return destination
