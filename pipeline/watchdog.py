#!/usr/bin/env python3
"""Shout if the published forecast has gone stale.

Run this somewhere that is NOT the pipeline host: a watchdog that dies with
the thing it watches is decoration. A second free runner, or a cron job on
any other machine, is enough.

    python3 watchdog.py https://data.klimatikal.com --max-age-hours 8

Exits non-zero when the data is stale, so any scheduler that reports failures
becomes the alerting channel without extra plumbing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", help="e.g. https://data.klimatikal.com")
    parser.add_argument("--max-age-hours", type=float, default=8.0)
    args = parser.parse_args()

    url = f"{args.base.rstrip('/')}/latest.json"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            latest = json.load(response)
    except Exception as exc:
        print(f"CRITICAL cannot read {url}: {exc}")
        return 2

    run_id = latest.get("run", "")
    try:
        run = dt.datetime.strptime(run_id, "%Y-%m-%dT%HZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        print(f"CRITICAL latest.json has an unparseable run: {run_id!r}")
        return 2

    age = (dt.datetime.now(dt.timezone.utc) - run).total_seconds() / 3600
    if age > args.max_age_hours:
        print(f"CRITICAL run {run_id} is {age:.1f}h old (limit {args.max_age_hours}h)")
        return 2

    # A run can be published with a manifest that does not load; check it.
    try:
        with urllib.request.urlopen(f"{args.base.rstrip('/')}/{latest['manifest']}", timeout=20) as r:
            manifest = json.load(r)
        steps = len(manifest.get("steps", []))
    except Exception as exc:
        print(f"CRITICAL run {run_id} published but its manifest is unreadable: {exc}")
        return 2

    print(f"OK run {run_id}, {age:.1f}h old, {steps} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
