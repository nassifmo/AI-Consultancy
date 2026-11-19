# Preparing company extracts

Use a mapping profile to convert local CSV, JSON or JSONL exports into the evaluator's existing file format. The adapter reads the named files, converts explicitly mapped fields and records source hashes and row references. It can preview the conversion without saving or publish a reproducible bundle.

```python
from pilot import import_source

preview = import_source(source_directory, profile)
prepared = import_source(source_directory, profile, output_directory)
exports_directory = prepared["exports_path"]
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
