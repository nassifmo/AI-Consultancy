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

Give the evaluator the `exports` directory inside the returned bundle. The `raw` directory, mapping profile and preparation record preserve the source evidence and remain outside evaluator inputs. The example declares its source tables complete because it was built from a complete fixture. An actual source needs a documented extraction window and completeness assessment. Fields such as assignment, related contacts, active work and finance values remain missing unless a mapped source provides them.
