# ds003745 draft validation repair

This is a local repair and validation step, **not an upload command**. It is
separate from the Ultimatum manuscript analyses. No FSL rerun is required.

## Scope and provenance

- Synchronize the already prepared 2.2.0 small-file release content (metadata,
  220 ratings TSVs, the four sub-144 event repairs, and reproducibility files)
  from this repository into the complete download. These additions may exist
  only in the earlier sparse upload, not the downloaded tree. The existing
  guarded release contract and ratings hashes are checked. The 222 regenerated
  single-trial images are required but are not copied, changed or rerun.
- Explicitly declare the root dataset `raw`. `GeneratedBy` without `DatasetType`
  caused schema-validator 3.0.1 to infer a derivative dataset and require
  inappropriate fields such as `SkullStripped` on raw images.
- Use `RRID:SCR_006571` for PsychoPy in the three task event sidecars.
- Remove inherited task-level `ImageType` only after confirming that every raw
  BOLD image retains an identical value in its own sidecar. The 420 tracked
  run-level JSON files passed this check; no acquisition values are changed.
- Exclude only Trust run-05 for sub-134 and sub-138, including their run-specific
  derivatives. Remove associated `scans.tsv` rows and fieldmap `IntendedFor`
  references. Preserve subject-wide anatomical derivatives and other tasks/runs.

In `DVS-Lab/srndna`, each participant has four complete 36-trial Trust logs,
named with zero-based run indices 0–3. Their contents match their original
uploads: [sub-134, 2019-03-22](https://github.com/DVS-Lab/srndna/commit/57dcb02b2fe8a33ab3cb28062615a01dc75f3479)
and [sub-138, 2019-04-16](https://github.com/DVS-Lab/srndna/commit/f17fe24680b186792a9e9b621e3f33877384e9e4).
Across Trial, cLeft, cRight, Partner, Reciprocate, ISI and ITI, each log uniquely
matches its run-01 through run-04 schedule. Decision/missed-trial onsets match
the corresponding BIDS tables. This supports run identity, but is not an
independent wall-clock synchronization check. The fifth-run behavioral records
were not found. Those event TSVs were header-only placeholders at the 2022
repository import. The reason the records are absent is unknown.

Historical input copies in the code repository remain available for provenance;
the exclusion is applied to the complete release dataset. The 218 regenerated
Trust LSS images already omit these two runs and remain unchanged.

## Linux1: preview, apply and validate

Use the complete **plain-files OpenNeuro download**, not the sparse staging tree
or Git-annex recovery repository. A sparse tree is not a substitute for
validating the resulting complete dataset. Run this in tmux if SSH is unstable.

```bash
CODE_ROOT=/ZPOOL/data/projects/srndna-datapaper-code
DATASET_ROOT=/ZPOOL/data/datasets/ds003745-work
FIX_ROOT=/ZPOOL/data/scratch/srndna-datapaper-validation-fix-v1

cd "$CODE_ROOT" && git pull --ff-only

python3 code/repair_openneuro_validation.py --dataset-root "$DATASET_ROOT"
```

Review the listed paths, then:

```bash
python3 code/repair_openneuro_validation.py \
  --dataset-root "$DATASET_ROOT" \
  --backup-root "$FIX_ROOT/backup" --apply &&
python3 code/validate_openneuro_full_dataset.py \
  --dataset-root "$DATASET_ROOT" \
  --output-dir "$FIX_ROOT/validation"
```

The repair requires 418–420 raw BOLD files (420 before the exclusions, 418
after), intact retained runs, and empty placeholder event tables for the
excluded acquisitions. It refuses Git/annex trees, symlinked target files,
unexpected populated event tables, and existing backup directories. Every
affected original is copied and SHA-256 verified before any dataset mutation.
Metadata replacements are atomic, so earlier hard-linked staging copies are
not silently altered. NIfTI payloads are not edited or recompressed.

The external backup contains:

- `originals/`: recoverable copies of every replaced/excluded file;
- `replacements/`: small-file updates and additions, including metadata;
- `repair-manifest.json`: exact paths, before/after hashes and reasons;
- `deletions.tsv`: explicit exclusions for a later reviewed remote update;
- `COMPLETE`: written only after all planned local operations finish.

If interrupted or any check fails, retain this directory and inspect the
manifest before retrying. Do not remove the backup to bypass a safety check.
A finished repair is idempotent; a fresh preview should propose no changes.

The validator wrapper records the OpenNeuro **v5.8.0** server profile:
validator **3.0.1**, schema **1.2.7**, and the matching server configuration.
It downloads the pinned schema/config, records their hashes plus the exact
command and runtime version, and validates the complete plain-files tree.
This pins the inspected server profile; it does not assume future OpenNeuro
deployments use the same versions. Results are `validation/validation.json`,
`validation/invocation.json`, and `validation/validator.stderr.log`.
Do not infer zero warnings from an exit code of zero.

## Before any remote update

Review the new validation report. Participant-ID reconciliation and lossless
gzip-header cleanup are separate remaining checks; this patch does not hide
warnings, invent optional metadata, or claim the dataset is warning-free.

The remote draft is unchanged by these commands. **Do not use `--delete` on a
sparse upload directory**: that could remove unrelated dataset files. Simply
omitting files from a sparse upload does not exclude them remotely. The exact
paths in `deletions.tsv` require a separate, reviewed remote deletion step.
Subject-wide historical preprocessing reports may mention the excluded runs;
  they are retained as historical reports, not rewritten as if never processed.

Keep the full backup outside the public release and retain earlier published
snapshots. Publish only after validating and checking the actual remote draft.

## Second pass: gzip privacy headers and sequence descriptions

`clean_openneuro_warnings.py` previews by default. It requires the repaired
complete download (418 BOLD files, 668 raw images). It removes outer gzip
timestamps, original filenames and comments while preserving the compressed
deflate stream and verifying SHA-256 of every decompressed byte, including the
NIfTI header. It refuses unsupported header flags, corrupt/truncated streams
and multiple gzip members. See [RFC 1952](https://www.rfc-editor.org/rfc/rfc1952).

The script also adds a general `PulseSequenceType` only when the existing
vendor `PulseSequenceDetails` and DICOM `ScanningSequence` agree with one of
four explicitly supported combinations. It does not infer coil reconstruction,
gradient correction, missing slice timing or task ontology identifiers.

```bash
python3 code/clean_openneuro_warnings.py --dataset-root "$DATASET_ROOT"
python3 -u code/clean_openneuro_warnings.py \
  --dataset-root "$DATASET_ROOT" \
  --backup-root /ZPOOL/data/scratch/srndna-datapaper-warning-cleanup-v1 \
  --apply
```

Run in tmux. Allow at least 25 GB of additional free space for this dataset's
raw-image backups plus working space. Every affected original is backed up and
checksum-verified before replacing the first file. Replacements are atomic;
hard-linked earlier staging copies are unchanged. An interrupted run resumes
with the same command plus `--resume`. Keep `cleanup-manifest.json` and
`originals/`; do not delete an existing backup to restart. The manifest records
before/after compressed hashes and decompressed hashes for the images.

Validate again into a fresh report directory using
`validate_openneuro_full_dataset.py`, then inspect all issue groups with
`summarize_bids_validation.py REPORT/validation.json`. No warnings are hidden
or downgraded. Based on the first report, 768 gzip-header warning instances and
668 missing sequence-description instances should disappear; approximately
3,602 warning instances will remain pending verification. Most are repeated
recommended metadata fields, not thousands of independent data defects.

The participant audit in `cleanup-manifest.json` lists actual root directories
not represented in `participants.tsv`, but does not move or remove them.
Remaining recommendations must be reviewed for applicability and available
source evidence; never fill unknown acquisition parameters merely to silence
the validator. This operation makes no OpenNeuro changes. The changed gzip
files have new compressed checksums and will need remote replacement even
though the image contents are identical. Single-trial estimates are untouched.

## Third pass: recovered DICOM metadata

The completed second-pass report is committed in
`results/openneuro_validation/cleanup_v1` (0 errors; 3,602 warning instances).
Use [DICOM_METADATA_RECOVERY.md](DICOM_METADATA_RECOVERY.md) for private,
resumable extraction, strict scan matching, geometry-checked slice timing,
missing-only JSON patches and a backed-up application step. That workflow
does not suppress the remaining recommendations or update OpenNeuro itself.
