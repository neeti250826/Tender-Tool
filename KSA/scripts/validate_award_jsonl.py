import argparse
import sys

from award_io import validate_jsonl_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate award scraper JSONL output against the normalized schema.")
    parser.add_argument("path", help="Path to JSONL file")
    args = parser.parse_args()
    errors, count = validate_jsonl_file(args.path)
    if errors:
        print(f"Validation failed for {args.path}", file=sys.stderr)
        for error in errors[:100]:
            print(error, file=sys.stderr)
        raise SystemExit(1)
    print(f"Validated {count} rows from {args.path}")


if __name__ == "__main__":
    main()
