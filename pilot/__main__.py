"""Prepare, inspect or approve a versioned shipment intake."""

import argparse
import json
from pathlib import Path

from .approval import approve_exports, intake_fingerprints
from .importing import import_source
from .inspection import inspect_exports, review_limitations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "import", "inspect-exports", "approve"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--profile", type=Path, help="Mapping profile for inspect or import.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviewer", help="Reviewer name or identifier for approve.")
    parser.add_argument("--note", help="Reviewed scope and decisions for approve.")
    options = parser.parse_args(argv)
    maps_sources = options.action in {"inspect", "import"}
    writes_bundle = options.action in {"import", "approve"}
    if maps_sources != (options.profile is not None):
        parser.error("--profile is required for inspect or import and omitted for canonical exports.")
    if writes_bundle != (options.output is not None):
        parser.error("--output is required for import or approve. Inspection only previews.")
    if options.action == "approve" and (options.reviewer is None or options.note is None):
        parser.error("approve requires --reviewer and --note after review.")
    if options.action != "approve" and (options.reviewer is not None or options.note is not None):
        parser.error("--reviewer and --note apply to approve.")
    try:
        if maps_sources:
            profile = json.loads(options.profile.read_text(encoding="utf-8-sig"))
            result = import_source(options.source, profile, options.output)
            result.pop("exports")
        elif options.action == "inspect-exports":
            result = inspect_exports(options.source)
        else:
            fingerprints = intake_fingerprints(options.source)
            inspection = inspect_exports(options.source)
            if inspection["blocking_reasons"]:
                parser.error(" ".join(inspection["blocking_reasons"]))
            result = approve_exports(options.source, options.output, reviewer=options.reviewer, note=options.note,
                                     limitations=review_limitations(inspection), expected_files=fingerprints)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
