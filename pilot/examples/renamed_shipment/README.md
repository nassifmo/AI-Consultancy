# Renamed shipment extracts

These synthetic files reproduce scenario S32 with renamed fields and alternative source formats. They exercise field and enum mapping, nested agent-tool logs, and line-delimited tracking records. The names illustrate a company export. No company schema or system access was used.

From the shipment benchmark directory, preview the mapped records and any issues.

```powershell
.venv/Scripts/python.exe -m pilot inspect --source pilot/examples/renamed_shipment/source --profile pilot/examples/renamed_shipment/profile.json
```

Publish a new immutable prepared bundle by supplying an output directory.

```powershell
.venv/Scripts/python.exe -m pilot import --source pilot/examples/renamed_shipment/source --profile pilot/examples/renamed_shipment/profile.json --output pilot_imports
```

Review the draft `exports` directory using `pilot inspect-exports`. Then use
`pilot approve` as described in the [intake guide](../../README.md) and give the
evaluator the approved exports path. The original bundle retains the `raw`
directory, mapping profile and preparation record. This synthetic example
declares complete coverage for its supplied sources. A company extract needs
its own documented extraction window and completeness assessment.
