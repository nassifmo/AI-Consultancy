"""Grade shipment exports or a single normalized enquiry."""

import argparse
import json
from pathlib import Path
import sys

from .grading import grade_enquiry
from .verification import verify_exports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("enquiry", nargs="?", help="Path to a normalized enquiry JSON file, or - for standard input.")
    parser.add_argument("--exports", type=Path, help="Path to an exports directory.")
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("policy.json"))
    parser.add_argument("--analyze", action="store_true", help="Compare assigned groups and calculate costs.")
    parser.add_argument("--analysis-config", type=Path, help="Optional JSON analysis settings.")
    parser.add_argument("--output-dir", type=Path, help="Parent directory for the immutable analysis bundle.")
    options = parser.parse_args()
    if (options.enquiry is None) == (options.exports is None):
        parser.error("Supply either a normalized enquiry or --exports.")
    if options.analyze and options.exports is None:
        parser.error("--analyze requires --exports.")
    if not options.analyze and (options.analysis_config is not None or options.output_dir is not None):
        parser.error("--analysis-config and --output-dir require --analyze.")
    try:
        policy = json.loads(options.policy.read_text(encoding="utf-8-sig"))
        if options.analyze:
            from .analysis import analyze_exports

            config = (json.loads(options.analysis_config.read_text(encoding="utf-8-sig"))
                      if options.analysis_config else None)
            result = analyze_exports(options.exports, policy, config)
            if options.output_dir:
                from .reporting import write_run_bundle

                path = write_run_bundle(options.output_dir, result, policy)
                print(path, file=sys.stderr)
        elif options.exports is not None:
            result = verify_exports(options.exports, policy)
        else:
            source = sys.stdin.read() if options.enquiry == "-" else Path(options.enquiry).read_text(encoding="utf-8-sig")
            result = grade_enquiry(policy, json.loads(source.lstrip("\ufeff")))
    except (OSError, ValueError, TypeError, OverflowError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
