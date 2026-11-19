"""Preview or import a directory of explicitly mapped company extracts."""

import argparse
import json
from pathlib import Path

from .importing import import_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "import"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    if options.action == "import" and options.output is None:
        parser.error("import needs --output to publish a prepared bundle.")
    if options.action == "inspect" and options.output is not None:
        parser.error("inspect previews in memory. Omit --output.")
    try:
        profile = json.loads(options.profile.read_text(encoding="utf-8-sig"))
        result = import_source(options.source, profile, options.output)
        result.pop("exports")
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
