#!/usr/bin/env python3
"""Lossless gzip-header cleanup and evidence-backed sequence descriptions.

Plain, repaired ds003745 download only. Preview by default; no remote actions.
Backups and a resumable journal live outside the dataset. Never suppresses
validator warnings or changes participant records, events or derivative images.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import zlib
from pathlib import Path

from repair_openneuro_validation import atomic_write, check_full_dataset, digest, json_bytes, regular

# General descriptions, not inferred scanner reconstruction settings. Require
# agreement between the vendor sequence identifier and DICOM ScanningSequence.
SEQUENCES = {
    ("%SiemensSeq%_ep2d_bold", "EP"): "Echo-planar imaging",
    ("%SiemensSeq%_gre_field_mapping", "GR"): "Gradient echo",
    ("%SiemensSeq%_tfl", "GR_IR"): "Inversion-recovery gradient echo",
    ("%SiemensSeq%_tse_vfl", "SE"): "Spin echo",
}
VERSION = 1
EXPECTED_RAW_IMAGES = 668
EXPECTED_BOLD_IMAGES = 418


def header(stream):
    """Read RFC1952's first header; conservatively refuse uncommon flags.

    FHCRC/FEXTRA are refused rather than discarded or guessed. Additional gzip
    members are detected during payload verification, before replacement.
    """
    fixed = stream.read(10)
    if len(fixed) != 10 or fixed[:3] != b"\x1f\x8b\x08":
        raise ValueError("not a complete deflate gzip header")
    flags = fixed[3]
    if flags & (0xE0 | 0x02 | 0x04):
        raise ValueError("unsupported gzip header flags; no file changed")
    extra = bytearray()
    for bit in (0x08, 0x10):
        if flags & bit:
            for _ in range(65536):
                char = stream.read(1)
                if not char:
                    raise ValueError("truncated gzip string")
                extra.extend(char)
                if char == b"\0":
                    break
            else:
                raise ValueError("unreasonably long gzip string")
    clean = bytearray(fixed)
    clean[3] &= ~(0x08 | 0x10)
    clean[4:8] = b"\0" * 4
    original = fixed + bytes(extra)
    return original, bytes(clean)


def payload_digest(path):
    """Hash ALL decompressed bytes, including the complete NIfTI header."""
    h = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize(source, destination):
    """Copy deflate bytes unchanged, replacing only the outer gzip header."""
    with source.open("rb") as src, destination.open("wb") as dst:
        _, clean = header(src)
        dst.write(clean)
        # Validate a SINGLE member and its trailer; do not leave metadata in a
        # second member. Hash decompressed bytes independently below as well.
        src.seek(0)
        decoder = zlib.decompressobj(31)
        uncompressed = hashlib.sha256()
        for block in iter(lambda: src.read(1024 * 1024), b""):
            pending = block
            while pending:
                uncompressed.update(decoder.decompress(pending, 1024 * 1024))
                pending = decoder.unconsumed_tail
                if decoder.unused_data:
                    break
            if decoder.unused_data:
                raise ValueError("multiple gzip members or trailing bytes; refusing replacement")
        uncompressed.update(decoder.flush())
        if not decoder.eof:
            raise ValueError("truncated gzip stream")
        src.seek(0)
        header(src)
        shutil.copyfileobj(src, dst, 1024 * 1024)
    actual = payload_digest(destination)
    if actual != uncompressed.hexdigest():
        raise ValueError("decompressed NIfTI checksum changed")
    shutil.copymode(source, destination)
    return actual


def participant_audit(root):
    with (root / "participants.tsv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    ids = [r["participant_id"] for r in rows]
    dirs = sorted(p.name for p in root.glob("sub-*") if p.is_dir())
    return dict(table_rows=len(ids), unique_ids=len(set(ids)),
                directories_without_participant=sorted(set(dirs) - set(ids)),
                participants_without_directory=sorted(set(ids) - set(dirs)),
                bidsignore=(root / ".bidsignore").read_text())


def plan(root):
    check_full_dataset(root)
    if json.loads((root / "dataset_description.json").read_text()).get("DatasetType") != "raw":
        raise ValueError("apply the first metadata repair before this cleanup")
    if len(list(root.glob("sub-*/func/*_bold.nii.gz"))) != EXPECTED_BOLD_IMAGES:
        raise ValueError("expected 418 raw BOLD files after the two exclusions")
    images = sorted(p for p in root.glob("sub-*/*/*.nii.gz") if p.parent.name in {"anat", "fmap", "func"})
    if len(images) != EXPECTED_RAW_IMAGES:
        raise ValueError(f"expected 668 raw images, found {len(images)}")
    items = []
    for image in images:
        regular(image, root)
        with image.open("rb") as f:
            original, clean = header(f)
        if original != clean:
            items.append(dict(path=image.relative_to(root).as_posix(), kind="gzip", before=digest(image),
                              bytes=image.stat().st_size))
        sidecar = image.with_name(image.name.removesuffix(".nii.gz") + ".json")
        regular(sidecar, root)
        data = json.loads(sidecar.read_text())
        if "PulseSequenceType" not in data:
            evidence = (data.get("PulseSequenceDetails"), data.get("ScanningSequence"))
            if evidence not in SEQUENCES:
                raise ValueError(f"unrecognized sequence; no inference made: {sidecar}: {evidence}")
            data["PulseSequenceType"] = SEQUENCES[evidence]
            items.append(dict(path=sidecar.relative_to(root).as_posix(), kind="json", before=digest(sidecar),
                              bytes=sidecar.stat().st_size, replacement=json_bytes(data).decode(),
                              evidence=dict(PulseSequenceDetails=evidence[0], ScanningSequence=evidence[1])))
    return items


def validate_item(root, item):
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 3:
        raise ValueError("unsafe manifest path")
    if not relative.parts[0].startswith("sub-") or relative.parts[1] not in {"anat", "fmap", "func"}:
        raise ValueError("manifest path outside raw image scope")
    suffix = ".nii.gz" if item["kind"] == "gzip" else ".json"
    if item["kind"] not in {"gzip", "json"} or not str(relative).endswith(suffix):
        raise ValueError("invalid manifest kind or suffix")
    regular(root / relative, root)


def apply(root, backup, items, resume=False):
    if backup.is_relative_to(root) or root.is_relative_to(backup):
        raise ValueError("backup must be outside and not an ancestor of dataset")
    journal = backup / "cleanup-manifest.json"
    if resume:
        record = json.loads(journal.read_text())
        if record["dataset_root"] != str(root) or record["version"] != VERSION:
            raise ValueError("resume dataset/version mismatch")
        items = record["files"]
    else:
        backup.mkdir(parents=True, exist_ok=False)
        record = dict(version=VERSION, dataset_root=str(root), files=items,
                      participant_audit=participant_audit(root))
        atomic_write(journal, json_bytes(record))
    for item in items:
        validate_item(root, item)
        src, saved = root / item["path"], backup / "originals" / item["path"]
        current = digest(src)
        if current not in {item["before"], item.get("after")}:
            raise ValueError(f"source changed outside this cleanup: {src}")
        if not saved.exists():
            if current != item["before"]:
                raise ValueError(f"original backup missing: {saved}")
            saved.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".backup-", dir=saved.parent)
            os.close(fd)
            try:
                shutil.copy2(src, name)
                if digest(Path(name)) != item["before"]:
                    raise ValueError("backup checksum mismatch")
                os.replace(name, saved)
            finally:
                Path(name).unlink(missing_ok=True)
        regular(saved, backup)
        if digest(saved) != item["before"]:
            raise ValueError(f"backup changed: {saved}")
    # Every original is now backed up and verified before any replacement.
    for n, item in enumerate(items, 1):
        dst = root / item["path"]
        if item.get("after") and digest(dst) == item["after"]:
            continue
        if digest(dst) != item["before"]:
            raise ValueError(f"source changed during cleanup: {dst}")
        fd, name = tempfile.mkstemp(prefix=".warning-cleanup-", dir=dst.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            if item["kind"] == "gzip":
                item["uncompressed_sha256"] = normalize(dst, temporary)
            else:
                temporary.write_text(item["replacement"])
                shutil.copymode(dst, temporary)
            item["after"] = digest(temporary)
            # Record expected replacement first, so a disconnect directly after
            # rename can be resumed without modifying completed files again.
            atomic_write(journal, json_bytes(record))
            if digest(dst) != item["before"]:
                raise ValueError(f"source changed before replacement: {dst}")
            os.replace(temporary, dst)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Updated {n}/{len(items)}: {item['path']}", flush=True)
    atomic_write(backup / "COMPLETE", b"All backups and replacements verified. No remote changes.\n")
    print(f"PASS: {len(items)} files; originals preserved at {backup / 'originals'}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--backup-root", type=Path)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    try:
        root = a.dataset_root.resolve()
        check_full_dataset(root)
        if a.resume and not a.apply:
            raise ValueError("--resume requires --apply")
        items = [] if a.resume else plan(root)
        if not a.resume:
            counts = {k: sum(x["kind"] == k for x in items) for k in ("gzip", "json")}
            print(f"Planned replacements: {counts}; backup bytes: {sum(x['bytes'] for x in items)}")
            print(json.dumps(participant_audit(root), indent=2))
        if a.apply:
            if not a.backup_root:
                raise ValueError("--apply requires --backup-root")
            apply(root, a.backup_root.resolve(), items, a.resume)
        else:
            print("Preview only; no files changed. No remote operations.")
        return 0
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        p.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
