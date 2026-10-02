#!/usr/bin/env python3
"""Print every validation issue grouped by severity/code/subcode; hide nothing."""
import argparse
import collections
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", type=Path)
    a = p.parse_args()
    data = json.loads(a.report.read_text())
    issues = data["issues"]["issues"]
    totals = collections.Counter(i["severity"] for i in issues)
    print("Issue instances:", dict(totals))
    counts = collections.Counter((i["severity"], i["code"], i.get("subCode", "")) for i in issues)
    for (severity, code, subcode), count in sorted(counts.items()):
        print(f"{severity}\t{count}\t{code}\t{subcode}")
    return int(totals["error"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
