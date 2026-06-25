#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import List

DEFAULT_START_DATE = "2024-01-01"
DEFAULT_END_DATE = date.today().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run item-level public medical scrapers in parallel.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=DEFAULT_END_DATE, help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--headless", action="store_true", help="Pass headless mode to Playwright-based scrapers.")
    parser.add_argument("--drap-max-pages", type=int, default=5)
    parser.add_argument("--drap-max-tenders", type=int, default=50)
    parser.add_argument("--epads-max-pages", type=int, default=5)
    parser.add_argument("--epads-max-tenders", type=int, default=50)
    parser.add_argument(
        "--sources",
        default="drap,epads",
        help="Comma-separated source list. Supported values: drap, epads",
    )
    return parser.parse_args()


def build_commands(repo_root: Path, args: argparse.Namespace) -> List[List[str]]:
    requested_sources = {part.strip().lower() for part in args.sources.split(",") if part.strip()}
    commands: List[List[str]] = []
    if "drap" in requested_sources:
        command = [
            sys.executable,
            str(repo_root / "Pakistan" / "DRAP" / "drap_item_scraper.py"),
            "--date-from",
            args.date_from,
            "--date-to",
            args.date_to,
            "--max-pages",
            str(args.drap_max_pages),
            "--max-tenders",
            str(args.drap_max_tenders),
        ]
        if args.headless:
            command.append("--headless")
        commands.append(command)
    if "epads" in requested_sources:
        command = [
            sys.executable,
            str(repo_root / "Pakistan" / "EPADS" / "epads_item_scraper.py"),
            "--date-from",
            args.date_from,
            "--date-to",
            args.date_to,
            "--max-pages",
            str(args.epads_max_pages),
            "--max-tenders",
            str(args.epads_max_tenders),
        ]
        if args.headless:
            command.append("--headless")
        commands.append(command)
    return commands


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    commands = build_commands(repo_root, args)
    processes = []
    for command in commands:
        processes.append(
            {
                "command": command,
                "process": subprocess.Popen(
                    command,
                    cwd=repo_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ),
            }
        )

    results = []
    exit_code = 0
    for entry in processes:
        stdout, stderr = entry["process"].communicate()
        results.append(
            {
                "command": entry["command"],
                "returncode": entry["process"].returncode,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }
        )
        if entry["process"].returncode != 0 and exit_code == 0:
            exit_code = entry["process"].returncode

    print(json.dumps({"date_from": args.date_from, "date_to": args.date_to, "results": results}, ensure_ascii=False))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
