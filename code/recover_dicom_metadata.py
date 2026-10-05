#!/usr/bin/env python3
"""Recover missing raw-image metadata from matched DICOM conversions.

extract: private, resumable, sequential conversion (never into BIDS).
plan: read-only matching; allowlisted public audit plus private patch.
apply: checksum-guarded additions only, with all originals backed up first.
No remote operations, deletions, ontology guesses or image replacements.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from repair_openneuro_validation import check_full_dataset, digest, json_bytes, regular, atomic_write

VERSION = 1
CONVERTER_VERSION = "v1.0.20241211"
REPO = Path(__file__).resolve().parents[1]
COPY_FIELDS = ("CoilCombinationMethod", "MatrixCoilMode", "NonlinearGradientCorrection")
ALLOWED = set(COPY_FIELDS) | {"SliceTiming", "SliceEncodingDirection"}
REQUIRED_MATCH = ("SeriesNumber", "ProtocolName", "EchoTime", "RepetitionTime",
                  "MRAcquisitionType", "ScanningSequence", "ImageOrientationPatientDICOM",
                  "SliceThickness", "Manufacturer")
OPTIONAL_MATCH = ("EchoTime1", "EchoTime2", "FlipAngle", "PixelBandwidth",
                  "SpacingBetweenSlices", "PartialFourier")


def outside(path, *roots):
    for root in roots:
        if path.is_relative_to(root) or root.is_relative_to(path):
            raise ValueError("private work/report/backup must be disjoint from dataset, DICOMs and code repository")


def private_write(path, value):
    atomic_write(path, json_bytes(value))
    path.chmod(0o600)


def raw_images(root):
    check_full_dataset(root)
    if json.loads((root / "dataset_description.json").read_text()).get("DatasetType") != "raw":
        raise ValueError("run the existing full-dataset validation repair first")
    images = sorted(p for p in root.glob("sub-*/*/*.nii.gz")
                    if p.parent.name in {"anat", "fmap", "func"})
    if len(images) != 668:
        raise ValueError(f"expected 668 released raw images; found {len(images)}")
    for path in images:
        if not re.fullmatch(r"sub-1[0-9]{2}", path.parts[-3]):
            raise ValueError("unexpected participant in raw-image scope")
        regular(path, root)
    return images


def select_subjects(images, selected):
    available = sorted({p.parts[-3] for p in images})
    if selected:
        requested = {"sub-" + s.removeprefix("sub-") for s in selected}
        if requested - set(available):
            raise ValueError("requested subject not in released raw-image inventory")
        return sorted(requested)
    return available


def extraction_valid(folder, record):
    if not record.get("json_sha256"):
        return False
    for relative, expected in record["json_sha256"].items():
        path = folder / relative
        if Path(relative).name != relative or not path.is_file() or path.is_symlink() or digest(path) != expected:
            return False
    for relative, size in record.get("nifti_bytes", {}).items():
        path = folder / relative
        if Path(relative).name != relative or not path.is_file() or path.is_symlink() or path.stat().st_size != size:
            return False
    return True


def extract(root, dicoms, work, selected=None, with_images=False):
    images = raw_images(root)
    outside(work, root, dicoms, REPO)
    if not dicoms.is_dir():
        raise ValueError("DICOM root absent; check that this is Linux1")
    binary = shutil.which("dcm2niix")
    if not binary:
        raise ValueError("dcm2niix not on PATH")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True)
    if CONVERTER_VERSION not in version.stdout + version.stderr:
        raise ValueError(f"this recovery records dcm2niix {CONVERTER_VERSION}; inspect another version before use")
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    work.chmod(0o700)
    config = dict(version=VERSION, dataset_root=str(root), dicom_root=str(dicoms),
                  converter=CONVERTER_VERSION, with_images=with_images)
    config_path = work / "extraction-config.json"
    if config_path.exists():
        if json.loads(config_path.read_text()) != config:
            raise ValueError("extraction configuration changed; use a new private work directory")
    else:
        if any(work.iterdir()):
            raise ValueError("unrecognized nonempty extraction directory")
        private_write(config_path, config)
    missing = []
    for subject in select_subjects(images, selected):
        source = dicoms / ("SMITH-AgingDM-" + subject.removeprefix("sub-"))
        if not source.is_dir():
            print(f"MISSING_DICOM: {subject}", flush=True)
            missing.append(subject)
            continue
        if source.is_symlink():
            raise ValueError(f"symlinked DICOM participant folder: {subject}")
        folder = work / subject
        folder.mkdir(exist_ok=True, mode=0o700)
        complete = folder / "complete.json"
        if complete.exists():
            record = json.loads(complete.read_text())
            attempt = folder / record["attempt"]
            if attempt.parent != folder or not extraction_valid(attempt, record):
                raise ValueError(f"completed extraction changed: {subject}; preserve it and use a new work directory")
            print(f"SKIP_COMPLETE: {subject}", flush=True)
            continue
        if with_images and shutil.disk_usage(work).free < 10 * 1024**3:
            raise ValueError("less than 10 GiB free before next participant; preserve completed extractions and free scratch space")
        attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=folder))
        command = [binary, "-g", "i", "-b", "y" if with_images else "o", "-ba", "y",
                   "-d", "9", "-z", "i", "-f", "series-%s_echo-%e", "-o", str(attempt), str(source)]
        private_write(attempt / "invocation.json", dict(command=command, converter=CONVERTER_VERSION))
        print(f"EXTRACT: {subject}; images={with_images}", flush=True)
        with (attempt / "conversion.log").open("w") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                    env={**os.environ, "OMP_NUM_THREADS": "1"})
        outputs = sorted(attempt.glob("series-*.json"))
        if result.returncode or not outputs:
            raise ValueError(f"extraction failed for {subject}; private conversion.log retained; rerun to retry in a fresh attempt")
        record = dict(attempt=attempt.name, json_sha256={p.name: digest(p) for p in outputs},
                      nifti_bytes={p.name: p.stat().st_size for p in attempt.glob("*.nii.gz")})
        if with_images and not record["nifti_bytes"]:
            raise ValueError(f"no scratch images produced for {subject}")
        private_write(complete, record)
        print(f"EXTRACTED: {subject}; JSONs={len(outputs)}", flush=True)
    private_write(work / "missing-dicoms.json", missing)
    print(f"Extraction complete; missing participant folders={len(missing)}. No BIDS changes.")


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-6)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    return a == b


def image_type(data):
    value = data.get("ImageType")
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        return None
    result = set(value)
    # New converter appends descriptive equivalents to old Siemens M/P tags.
    for short, long in (("M", "MAGNITUDE"), ("P", "PHASE"), ("R", "REAL"), ("I", "IMAGINARY")):
        if short in result:
            result.discard(long)
    return result


def matches(old, new):
    if not image_type(old) or image_type(old) != image_type(new):
        return False
    for field in REQUIRED_MATCH:
        if field not in old or field not in new or not equal(old[field], new[field]):
            return False
    for field in OPTIONAL_MATCH:
        if field in old and field in new and not equal(old[field], new[field]):
            return False
    # Compare private identifiers if both happen to be available; never export.
    for field in ("SeriesInstanceUID", "StudyInstanceUID", "AcquisitionTime"):
        if field in old and field in new and old[field] != new[field]:
            return False
    return True


def geometry(image):
    try:
        import nibabel as nib
    except ImportError as exc:
        raise ValueError("nibabel required for geometry checks; use the srndna-ultimatum conda environment") from exc
    img = nib.load(image)
    if not all(math.isfinite(float(v)) for v in img.affine.ravel()):
        raise ValueError("nonfinite NIfTI affine")
    if not int(img.header["sform_code"]) and not int(img.header["qform_code"]):
        raise ValueError("NIfTI has no coded spatial transform")
    return dict(shape=list(img.shape), affine=img.affine.tolist(), slice_axis=img.header.get_dim_info()[2])


def timing_additions(old, new, old_image, new_image):
    """Use a verified NIfTI slice axis, never reverse arrays to force agreement."""
    if "SliceTiming" in old:
        if "SliceTiming" in new and not equal(old["SliceTiming"], new["SliceTiming"]):
            return {}, "existing_timing_differs", None
        return {}, "existing_timing_preserved", None
    timing = new.get("SliceTiming")
    if not isinstance(timing, list) or not timing:
        return {}, "no_source_timing", None
    direction = new.get("SliceEncodingDirection")
    if direction is not None and direction not in {"i", "i-", "j", "j-", "k", "k-"}:
        return {}, "invalid_timing", None
    if not new_image.is_file():
        return {}, "scratch_image_required", None
    g_old, g_new = geometry(old_image), geometry(new_image)
    if not equal(g_old, g_new):
        return {}, "geometry_mismatch", None
    axis = g_new["slice_axis"]
    if axis not in (0, 1, 2):
        return {}, "source_slice_axis_missing", None
    # BIDS: absent SliceEncodingDirection means increasing NIfTI slice index.
    # This converter writes timing against dim[3]; require the header to agree.
    if direction is None and (axis != 2 or new.get("MRAcquisitionType") != "2D"):
        return {}, "source_slice_axis_missing", None
    if direction is not None and "ijk".index(direction[0]) != axis:
        return {}, "slice_axis_conflict", None
    if "SliceEncodingDirection" in old and old["SliceEncodingDirection"] != (direction or "ijk"[axis]):
        return {}, "slice_axis_conflict", None
    tr = new.get("RepetitionTime")
    if (len(timing) != g_old["shape"][axis] or not isinstance(tr, (int, float)) or tr <= 0
            or any(isinstance(x, bool) or not isinstance(x, (float, int))
                   or not math.isfinite(x) or not 0 <= x < tr for x in timing)):
        return {}, "invalid_timing", None
    # Avoid transferring timing to a differently reoriented released image.
    # The fresh NIfTI header identifies the axis; BIDS defines list direction.
    values = {"SliceTiming": timing}
    if direction is not None and "SliceEncodingDirection" not in old:
        values["SliceEncodingDirection"] = direction
    return values, "geometry_verified", g_old


def mismatch_fields(old, source_list):
    if not source_list:
        return "no_completed_extraction"
    same_series = [d for _, d in source_list if d.get("SeriesNumber") == old.get("SeriesNumber")]
    if not same_series:
        return "SeriesNumber"
    reasons = set()
    for new in same_series:
        for field in REQUIRED_MATCH + OPTIONAL_MATCH:
            if field in REQUIRED_MATCH and (field not in old or field not in new):
                reasons.add(field + ":missing")
            elif field in old and field in new and not equal(old[field], new[field]):
                reasons.add(field + ":different")
        if image_type(old) != image_type(new):
            reasons.add("ImageType:different")
        for field in ("SeriesInstanceUID", "StudyInstanceUID", "AcquisitionTime"):
            if field in old and field in new and old[field] != new[field]:
                reasons.add(field + ":different")
    return ";".join(sorted(reasons))


def approved_value(key, value, source):
    if key == "CoilCombinationMethod":
        return value in ("Sum of Squares", "Adaptive Combine")
    if key == "MatrixCoilMode":
        return value in ("SENSE", "GRAPPA")  # retained converter label, NOT an acceleration claim
    if key == "NonlinearGradientCorrection":
        types = image_type(source) or set()
        return type(value) is bool and ((value and bool(types & {"DIS2D", "DIS3D"}) and "ND" not in types)
                                       or (not value and "ND" in types and not types & {"DIS2D", "DIS3D"}))
    return False


def inherited_values(root, sidecar):
    """Respect applicable root/subject/datatype JSONs; never shadow a value."""
    def entities(path):
        parts = path.stem.split("_")
        return parts[-1], dict(p.split("-", 1) for p in parts[:-1] if "-" in p)
    suffix, target = entities(sidecar)
    values, evidence = {}, {}
    for directory in (root, sidecar.parent.parent, sidecar.parent):
        applicable = []
        for path in directory.glob("*.json"):
            if path == sidecar:
                continue
            other_suffix, subset = entities(path)
            if other_suffix == suffix and all(target.get(k) == v for k, v in subset.items()):
                regular(path, root)
                applicable.append((len(subset), path))
        tier_values = {}
        for specificity, path in sorted(applicable):
            evidence[path.relative_to(root).as_posix()] = digest(path)
            for key, value in json.loads(path.read_text()).items():
                if key not in ALLOWED:
                    continue
                tier = (specificity, key)
                if tier in tier_values and not equal(tier_values[tier], value):
                    raise ValueError("ambiguous inherited metadata; resolve before patching")
                tier_values[tier] = value
                values[key] = value
    return values, evidence


def candidates(work, subject):
    marker = work / subject / "complete.json"
    if not marker.is_file():
        return []
    record = json.loads(marker.read_text())
    folder = marker.parent / record["attempt"]
    if folder.parent != marker.parent or not extraction_valid(folder, record):
        raise ValueError(f"extraction manifest invalid: {subject}")
    return [(p, json.loads(p.read_text())) for p in sorted(folder.glob("series-*.json"))]


def make_plan(root, work, report, public_report, selected=None):
    images = raw_images(root)
    outside(report, root, work, REPO)
    outside(public_report, work, report)
    if public_report.is_relative_to(root) or root.is_relative_to(public_report):
        raise ValueError("public audit must be outside the dataset")
    config = json.loads((work / "extraction-config.json").read_text())
    if config["dataset_root"] != str(root) or config["converter"] != CONVERTER_VERSION:
        raise ValueError("extraction configuration mismatch")
    subjects = select_subjects(images, selected)
    sources = {s: candidates(work, s) for s in subjects}
    items, audit = [], []
    for image in images:
        subject = image.parts[-3]
        if subject not in subjects:
            continue
        sidecar = image.with_name(image.name.removesuffix(".nii.gz") + ".json")
        regular(sidecar, root)
        old = json.loads(sidecar.read_text())
        inherited, inherited_hashes = inherited_values(root, sidecar)
        effective = {**inherited, **old}
        hits = [(p, d) for p, d in sources[subject] if matches(old, d)]
        row = dict(path=sidecar.relative_to(root).as_posix(), candidates=len(hits),
                   status="unmatched" if not hits else "ambiguous", added="", conflicts="", timing="not_matched",
                   unmatched_fields=mismatch_fields(old, sources[subject]) if not hits else "")
        if len(hits) == 1:
            source, new = hits[0]
            additions, conflicts = {}, []
            for key in COPY_FIELDS:
                if key in new:
                    if not approved_value(key, new[key], new):
                        conflicts.append(key + ":unsupported")
                    elif key in effective and not equal(effective[key], new[key]):
                        conflicts.append(key + ":existing_value")
                    elif key not in effective:
                        additions[key] = new[key]
            fresh_image = source.with_suffix(".nii.gz")
            timing, state, image_geometry = timing_additions(effective, new, image, fresh_image)
            additions.update(timing)
            if state in {"existing_timing_differs", "slice_axis_conflict", "invalid_timing", "geometry_mismatch"}:
                conflicts.append(state)
            row.update(status="conflict" if conflicts else "matched", conflicts=";".join(conflicts), timing=state)
            # Any conflict holds this entire sidecar, not just the conflicting field.
            if not conflicts and additions:
                row["added"] = ";".join(sorted(additions))
                after = json_bytes({**old, **additions})
                items.append(dict(path=row["path"], before=digest(sidecar),
                                  after=hashlib.sha256(after).hexdigest(), additions=additions,
                                  source=str(source), source_sha256=digest(source),
                                  source_image=str(fresh_image) if timing else None,
                                  image_geometry=image_geometry, inherited_sha256=inherited_hashes))
        audit.append(row)
    report.mkdir(parents=True, exist_ok=False, mode=0o700)
    private_write(report / "patch.json", dict(version=VERSION, dataset_root=str(root),
                  extraction_root=str(work), files=items))
    public_report.mkdir(parents=True, exist_ok=True)
    with (public_report / "matching.tsv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(audit[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(audit)
    counts = {state: sum(r["status"] == state for r in audit)
              for state in ("matched", "unmatched", "ambiguous", "conflict")}
    summary = dict(images_audited=len(audit), **counts, proposed_sidecars=len(items),
                   proposed_fields={k: sum(k in item["additions"] for item in items) for k in sorted(ALLOWED)},
                   dataset_modified=False, no_remote_operations=True)
    atomic_write(public_report / "summary.json", json_bytes(summary))
    print(json.dumps(summary, indent=2))
    print(f"Preview only. Private patch: {report / 'patch.json'}")
    print("Only matching.tsv and summary.json are intended for Git; raw extraction and logs remain private.")
    return summary


def validate_patch_item(root, item):
    path = Path(item["path"])
    if (path.is_absolute() or ".." in path.parts or len(path.parts) != 3
            or not re.fullmatch(r"sub-1[0-9]{2}", path.parts[0])
            or path.parts[1] not in {"anat", "fmap", "func"} or path.suffix != ".json"):
        raise ValueError("patch path outside raw sidecar scope")
    if not item["additions"] or set(item["additions"]) - ALLOWED:
        raise ValueError("unapproved field in patch")
    sidecar = root / path
    regular(sidecar, root)
    image = sidecar.with_suffix(".nii.gz")
    regular(image, root)
    return sidecar, image


def apply(root, patch_path, backup):
    raw_images(root)
    outside(backup, root, REPO, patch_path.parent)
    record = json.loads(patch_path.read_text())
    if record["dataset_root"] != str(root) or record["version"] != VERSION:
        raise ValueError("patch dataset/version mismatch")
    if len({x["path"] for x in record["files"]}) != len(record["files"]):
        raise ValueError("duplicate patch targets")
    journal = backup / "patch.json"
    if backup.exists():
        if not journal.is_file() or journal.read_bytes() != patch_path.read_bytes():
            raise ValueError("backup belongs to a different patch; do not delete it")
    else:
        backup.mkdir(parents=True, mode=0o700)
        private_write(journal, record)
    replacements = []
    # Validate all source evidence and targets, then back up every original,
    # before the first replacement. Resume accepts only exact planned bytes.
    for item in record["files"]:
        sidecar, image = validate_patch_item(root, item)
        source = Path(item["source"])
        if source.is_symlink() or digest(source) != item["source_sha256"]:
            raise ValueError("extracted source changed after planning")
        saved = backup / "originals" / item["path"]
        current = digest(sidecar)
        if current not in {item["before"], item["after"]}:
            raise ValueError(f"sidecar changed since planning: {item['path']}")
        if not saved.exists():
            if current != item["before"]:
                raise ValueError("original backup missing for an already modified sidecar")
            saved.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(saved, sidecar.read_bytes())
        regular(saved, backup)
        if digest(saved) != item["before"]:
            raise ValueError("original backup checksum mismatch")
        old, new = json.loads(saved.read_text()), json.loads(source.read_text())
        inherited, inherited_hashes = inherited_values(root, sidecar)
        if inherited_hashes != item["inherited_sha256"]:
            raise ValueError("inherited sidecars changed since planning")
        effective = {**inherited, **old}
        if not matches(old, new):
            raise ValueError("scan identity no longer matches")
        for key, value in item["additions"].items():
            if key in effective or key not in new or not equal(value, new[key]):
                raise ValueError("patch is not a missing-only source-backed addition")
            if key in COPY_FIELDS and not approved_value(key, value, new):
                raise ValueError("unsupported source value")
        if "SliceTiming" in item["additions"]:
            values, status, observed = timing_additions(effective, new, image, Path(item["source_image"]))
            if status != "geometry_verified" or not equal(observed, item["image_geometry"]):
                raise ValueError("slice timing geometry changed")
            if any(item["additions"].get(k) != v for k, v in values.items()):
                raise ValueError("slice timing patch mismatch")
        elif "SliceEncodingDirection" in item["additions"]:
            raise ValueError("slice axis cannot be patched without verified timing")
        content = json_bytes({**old, **item["additions"]})
        if hashlib.sha256(content).hexdigest() != item["after"]:
            raise ValueError("patch replacement checksum mismatch")
        replacements.append((sidecar, item, content))
    for sidecar, item, content in replacements:
        regular(sidecar, root)
        current = digest(sidecar)
        if current == item["after"]:
            continue
        if current != item["before"]:
            raise ValueError("sidecar changed during patch application")
        atomic_write(sidecar, content)
        print(f"ADDED_METADATA: {item['path']}", flush=True)
    private_write(backup / "COMPLETE", dict(sidecars=len(replacements), images_changed=0))
    print(f"PASS: {len(replacements)} sidecars; originals backed up; no images or remote files changed.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--dicom-root", type=Path, required=True)
    e.add_argument("--work-root", type=Path, required=True)
    e.add_argument("--with-images", action="store_true", help="scratch NIfTIs needed to verify missing slice timing")
    e.add_argument("--subjects", nargs="+")
    q = sub.add_parser("plan")
    q.add_argument("--work-root", type=Path, required=True)
    q.add_argument("--report-root", type=Path, required=True)
    q.add_argument("--public-report", type=Path, required=True)
    q.add_argument("--subjects", nargs="+")
    a = sub.add_parser("apply")
    a.add_argument("--patch", type=Path, required=True)
    a.add_argument("--backup-root", type=Path, required=True)
    for parser in (e, q, a):
        parser.add_argument("--dataset-root", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    try:
        root = args.dataset_root.resolve()
        if args.command == "extract":
            work = args.work_root.resolve()
            outside(work, root, args.dicom_root.resolve(), REPO)
            work.parent.mkdir(parents=True, exist_ok=True)
            with work.with_name(work.name + ".lock").open("w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError("another extraction is running for this work root") from exc
                extract(root, args.dicom_root.resolve(), work, args.subjects, args.with_images)
        elif args.command == "plan":
            make_plan(root, args.work_root.resolve(), args.report_root.resolve(), args.public_report.resolve(), args.subjects)
        else:
            apply(root, args.patch.resolve(), args.backup_root.resolve())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Do not echo raw converter exceptions or arbitrary source metadata.
        p.exit(1, f"STOP: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
