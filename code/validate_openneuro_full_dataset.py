#!/usr/bin/env python3
"""Validate a complete ds003745 tree using a recorded OpenNeuro server profile.

The profile is pinned to OpenNeuro v5.8.0 (validator 3.0.1, schema 1.2.7).
This records a reproducible comparison, not a claim about future server versions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from repair_openneuro_validation import check_full_dataset

PROFILE = "v5.8.0"
VALIDATOR = "3.0.1"
ASSETS = ("https://raw.githubusercontent.com/OpenNeuroOrg/openneuro/"
          f"{PROFILE}/services/datalad/datalad_service/tasks/assets/")


def command(root: Path, report: Path, deno: str) -> list[str]:
    return [deno, "run", "-A", f"jsr:@bids/validator@{VALIDATOR}",
            "--config", str(report / "validator-config.json"), "--json",
            "--blacklistModalities", "micr", "--datasetTypes", "raw,derivative",
            "--schema", (report / "schema-1.2.7-datacite.json").as_uri(), str(root)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root, report = args.dataset_root.resolve(), args.output_dir.resolve()
    try:
        check_full_dataset(root)
        if report.is_relative_to(root) or root.is_relative_to(report):
            raise ValueError("validation output must be outside the dataset")
        deno = shutil.which("deno")
        if not deno:
            raise ValueError("deno is not on PATH")
        report.mkdir(parents=True, exist_ok=False)
        assets = {}
        for name in ("validator-config.json", "schema-1.2.7-datacite.json"):
            url = ASSETS + name
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read()
            parsed = json.loads(content)
            if name.startswith("schema-") and parsed.get("schema_version") != "1.2.7":
                raise ValueError("unexpected downloaded schema version")
            (report / name).write_bytes(content)
            assets[name] = dict(url=url, sha256=hashlib.sha256(content).hexdigest())
        invocation = command(root, report, deno)
        record = dict(dataset_root=str(root), started=datetime.now(timezone.utc).isoformat(),
                      openneuro_profile=PROFILE, validator_version=VALIDATOR, assets=assets,
                      command=invocation,
                      deno_version=subprocess.check_output([deno, "--version"], text=True),
                      raw_bold_files=len(list(root.glob("sub-*/func/*_bold.nii.gz"))))
        (report / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"Validating complete tree ({record['raw_bold_files']} raw BOLD files): {root}", flush=True)
        with (report / "validation.json").open("w") as stdout, (report / "validator.stderr.log").open("w") as stderr:
            result = subprocess.run(invocation, stdout=stdout, stderr=stderr, check=False)
        record.update(exit_status=result.returncode, finished=datetime.now(timezone.utc).isoformat())
        (report / "invocation.json").write_text(json.dumps(record, indent=2) + "\n")
        # A successful process is not automatically a warning-free dataset.
        json.loads((report / "validation.json").read_text())
        print(f"Validator exit status: {result.returncode}; review {report / 'validation.json'}")
        print("No upload or publication was performed.")
        return result.returncode
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
