# Preparing company extracts

Use a mapping profile to convert local CSV, JSON or JSONL exports into the evaluator's existing file format. The adapter reads the named files, converts explicitly mapped fields and records source hashes and row references. It can preview the conversion without saving or publish a reproducible bundle.

## Review and approve the data

In Streamlit, open **Prepare company files**. Select a profile and a source ZIP
or select the individual CSV, JSON and JSONL files. **Evaluator exports ZIP**
previews files that already use our format. **Preview synthetic company extract**
exercises the same workflow using shipment case S32.

1. **Files received** lists mapped, withheld, duplicate and conflicting records,
   the study period and the evidence cutoff.
2. **Mapping preview** lets you compare an original record with its mapped
   values and trace the output back to the source.
3. **Review issues** shows searchable checks and a downloadable issue register.
   For a missing source path, review a proposed mapping or edit the profile
   manually. Previewing a trial leaves the current draft in place. Applying a
   trial requires a reviewer note and reruns the input checks. Optional Ollama
   suggestions use field paths and schema details on this computer. Values from
   customer records stay in the local review.
4. **Approval** records a reviewer and the unresolved evidence. **Approve for
   evaluation** publishes one reviewed copy and selects it for **Run evaluation**.
   A study period, evidence cutoff and identifiable enquiry are required.

An approved bundle preserves the exact export files and a review record
`exports/intake_approval.json`. That record includes the approval ID, time,
reviewer, mapping revision when applicable, decisions, evidence limitations,
and file fingerprints. The evaluator verifies the fingerprints before use and
includes the review in its run provenance. Use a new approval after changing the
data. The local review records the reviewer's attestation.

The command line can review and approve exports from a prepared bundle or from
an existing standardized extract:

```powershell
.venv/Scripts/python.exe -m pilot inspect-exports --source <draft-exports>
.venv/Scripts/python.exe -m pilot approve --source <draft-exports> --output pilot_imports --reviewer "Reviewer name" --note "Review evidence and outstanding limitations"
.venv/Scripts/python.exe -m evaluator --exports <approved-exports> --analyze
```

Reviewed company exports and intentionally synthetic benchmark exports are
supported. Company exports need source coverage declarations for conclusions
that depend on complete histories.

## Tracking history available at reply time

Map `tracking_events.event_available_datetime` to the first time the specific
support channel could retrieve the event. Preserve its creation and occurrence
timestamps separately. A clearly identified source-owner confirmation can
support creation-time fallback through `metadata.tracking_creation_visibility_ref`.
An explicit availability time takes precedence. If the evidence cannot
establish when a relevant revision was available, the affected historical
check remains unknown. Synthetic benchmarks can use their recorded creation
times.

```python
from pilot import import_source

preview = import_source(source_directory, profile)
prepared = import_source(source_directory, profile, output_directory)
draft_exports = prepared["exports_path"]
```

## Mapping profile

The profile has `schema_version` of `1.0`, a `profile_id` and `profile_version`, explicit `metadata`, and `tables`. Metadata needs the study start and end and the data cutoff as ISO times with UTC offsets. A source owner should confirm what period the export covers and whether each table is complete, partial, or unknown. The adapter defaults those declarations to unknown.

```json
{
  "schema_version": "1.0",
  "profile_id": "partner-sample",
  "profile_version": "1",
  "metadata": {
    "dataset_origin": "unconfirmed",
    "study_period": ["2026-11-01T00:00:00+00:00", "2026-11-08T00:00:00+00:00"],
    "data_cutoff": "2026-11-15T00:00:00+00:00",
    "source_completeness": {"enquiries": "partial"}
  },
  "tables": {
    "enquiries": {
      "file": "tickets.csv",
      "format": "csv",
      "columns": {
        "enquiry_id": "ticket_id",
        "customer_id": "account_id",
        "received_at": {"path": "created", "type": "datetime", "timezone": "Asia/Beirut"},
        "enquiry_type": {"path": "category", "values": {"Tracking": "status", "Delay": "delay"}},
        "customer_message": "description"
      }
    }
  }
}
```

Supply one mapping per canonical table. The available tables are the names in `evaluator/exports.py`. Each table identifies a direct filename and `csv`, `json`, or `jsonl` format. JSON may specify a `records_path` such as `data.records`. Column paths may identify a direct field or a nested path such as `ticket.account.id`. A direct key takes precedence over interpreting dots as nesting.

Mappings support `string`, `datetime`, `integer`, `number`, `boolean`, `list`, and `object_list`. An `object_list` may have `items` mappings to convert each nested record, as in the agent-tool trace example. A `values` object explicitly maps enums or source booleans. Unknown mappings, invalid types and ambiguous local times are reported. A missing field remains unavailable. JSON and JSONL bodies must contain records. Structured content remains data and is never evaluated as instructions or code.

An optional `objects.cost_parameters` entry with a direct JSON `file` supplies the finance configuration object. Its field interpretation remains the cost ledger's responsibility. Missing finance files allow service evidence to be inspected. Missing allocation records and active-work measurements do not acquire inferred replacements.

## Prepared bundle

Publishing creates `import-<content digest>/` with `exports/`, `raw/`, `profile.json` and `preparation.json`. The preparation record includes the importer source hash, profile version, source file hashes and sizes, input/output row counts, conversion issues, duplicates, conflicting IDs and row provenance. Exact and conflicting duplicate records are retained for the evaluator's existing conflict handling. Malformed source rows are identified by their original record index and remain in the retained raw file.

The import directory is published atomically. Repeating the same conversion reuses the verified bundle, and a changed file or mapping creates a different ID. A bundle whose contents have been changed is rejected. The evaluator receives only `exports/`. Source data and mapping evidence stay outside that directory.

The preparation limits are 100 MiB per source file, 300 MiB total input and 250,000 records per table. These are implementation limits for this local release. Source files must be directly inside the selected source directory. Nested paths and symbolic links are rejected. An authenticated API or scheduled extraction would provide these local snapshots through a company-specific connector once access and the source contract are agreed.

The [renamed shipment example](examples/renamed_shipment/README.md) provides a mixed-format synthetic walkthrough. It preserves the evidence from S32 while illustrating the adjustment needed when a partner uses different field names.
