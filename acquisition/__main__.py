"""Collect an approved REST endpoint into local JSONL source records."""

import argparse
import json
from pathlib import Path

from .collect import CollectionError, collect_json, validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-config", action="store_true", help="Validate settings without contacting the service.")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        if args.check_config:
            validate_config(config)
            print("Collection settings are valid. No request was made.")
        elif args.output is None:
            parser.error("--output is required for a collection.")
        else:
            print(json.dumps(collect_json(config, args.output), indent=2, allow_nan=False))
    except CollectionError as error:
        parser.error(str(error))
    except (OSError, json.JSONDecodeError):
        parser.error("Collection could not complete. Check the configuration file and output location.")


if __name__ == "__main__":
    main()
