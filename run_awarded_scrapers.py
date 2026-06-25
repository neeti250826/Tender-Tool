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
    parser = argparse.ArgumentParser(description="Run awarded medical scrapers in parallel.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=DEFAULT_END_DATE, help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--headless", action="store_true", help="Pass headless mode to Playwright-based scrapers.")
    parser.add_argument("--translate", action="store_true", help="Enable best-effort English translation columns.")
    parser.add_argument("--capt-max-pages", type=int, default=250)
    parser.add_argument("--ppra-max-pages", type=int, default=100)
    parser.add_argument(
        "--ppra-live-timeout",
        type=int,
        default=900,
        help="Timeout in seconds for live PPRA requests before fallback rows take over.",
    )
    parser.add_argument("--esupply-max-pages", type=int, default=25)
    parser.add_argument(
        "--sources",
        default="capt,ppra,esupply",
        help="Comma-separated source list. Supported values: capt, ppra, esupply",
    )
    return parser.parse_args()


def build_commands(repo_root: Path, args: argparse.Namespace) -> List[List[str]]:
    requested_sources = {part.strip().lower() for part in args.sources.split(",") if part.strip()}
    commands: List[List[str]] = []
    if "capt" in requested_sources:
        capt_command = [
            sys.executable,
            str(repo_root / "Kuwait" / "CAPT" / "capt_awarded_scraper.py"),
            "--date-from",
            args.date_from,
            "--date-to",
            args.date_to,
            "--max-pages",
            str(args.capt_max_pages),
        ]
        if args.headless:
            capt_command.append("--headless")
        commands.append(capt_command)
    if "ppra" in requested_sources:
        commands.append(
            [
                sys.executable,
                str(repo_root / "Pakistan" / "PPRA" / "ppra_awarded_scraper.py"),
                "--date-from",
                args.date_from,
                "--date-to",
                args.date_to,
                "--max-pages",
                str(args.ppra_max_pages),
                "--live-timeout",
                str(max(30, int(args.ppra_live_timeout))),
            ]
        )
    if "esupply" in requested_sources:
        commands.append(
            [
                sys.executable,
                str(repo_root / "UAE" / "Dubai_eSupply" / "dubai_esupply_scraper.py"),
                "--date-from",
                args.date_from,
                "--date-to",
                args.date_to,
                "--max-pages",
                str(args.esupply_max_pages),
            ]
        )
    if args.translate:
        for command in commands:
            command.append("--translate")
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
        process = entry["process"]
        stdout, stderr = process.communicate()
        results.append(
            {
                "command": entry["command"],
                "returncode": process.returncode,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }
        )
        if process.returncode != 0 and exit_code == 0:
            exit_code = process.returncode

    print(json.dumps({"date_from": args.date_from, "date_to": args.date_to, "results": results}, ensure_ascii=False))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
