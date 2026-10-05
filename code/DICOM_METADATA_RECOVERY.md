# DICOM-backed metadata recovery for ds003745

This workflow is separate from the Ultimatum analyses. It adds missing metadata
to the plain downloaded dataset; it never replaces images, events, ratings,
derivatives or participant records, and never uploads anything.

The committed October 2 cleanup validation contains **0 errors, 3,602 warning
instances**. Earlier gzip privacy-header and sequence-description fixes are
already reflected in that report. Do not repeat the earlier cleanup merely
because these remaining warnings exist.

## What the patch can establish

- `CoilCombinationMethod`: converter interpretation of Siemens CSA settings.
- `MatrixCoilMode`: converter-reported mode. `SENSE` is not proof of accelerated
  acquisition: the Siemens setting can be populated even at acceleration 1.
- `NonlinearGradientCorrection`: converter interpretation of ND/DIS image-type
  markers, checked again by this script. This describes the source image,
  not every correction that might later be applied during preprocessing.
- `SliceTiming`: only after unique scan matching and agreement between the
  newly converted scratch NIfTI and released NIfTI in shape, affine and slice
  axis. Arrays must fit the slice count and TR. No array reversal or assumed
  slice ordering is used to force agreement. Missing explicit direction uses
  the BIDS increasing-index convention and requires matching NIfTI slice axes.

The extractor is pinned to the available dcm2niix **v1.0.20241211**. The software
reads original DICOMs and writes private scratch outputs, not published BIDS
files. Values are **converter-derived metadata**, not a claim that every value
is a literal public DICOM tag. See [converter source](https://github.com/rordenlab/dcm2niix/blob/v1.0.20241211/console/nii_dicom_batch.cpp)
and [BIDS timing definitions](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/magnetic-resonance-imaging-data.html#timing-parameters).

Matching requires participant, series number, protocol, echo time, TR, MR
acquisition type, scanning sequence, image type, orientation, thickness and
manufacturer. Further shared fields and available UIDs/acquisition time must
agree. Neither series number alone nor nearest timing is accepted. Ambiguous
or unmatched scans and conflicting existing metadata are held for review.
Inherited BIDS metadata is respected and fingerprinted too.

## Linux1: extract and preview

Run inside tmux. This is sequential, with internal gzip compression and one
OpenMP thread; it does not consume the 40-core Stan budget. Allow substantial
scratch space (potentially tens of GB): un-defaced anatomical images may be
recreated privately for verification. Nothing from the extraction directory
belongs in GitHub or OpenNeuro, including converter logs.

```bash
cd /ZPOOL/data/projects/srndna-datapaper-code && git pull --ff-only
conda activate srndna-ultimatum
python3 -c 'import nibabel; print(nibabel.__version__)'

DATASET_ROOT=/ZPOOL/data/datasets/ds003745-work
DICOM_ROOT=/mnt/elements/2023-07-01_BackUp/sourcedata/srndna/dicoms
RECOVERY_ROOT=/ZPOOL/data/scratch/srndna-dicom-metadata-v1

python3 -u code/recover_dicom_metadata.py extract \
  --dataset-root "$DATASET_ROOT" --dicom-root "$DICOM_ROOT" \
  --work-root "$RECOVERY_ROOT/extraction" --with-images &&
python3 code/recover_dicom_metadata.py plan \
  --dataset-root "$DATASET_ROOT" \
  --work-root "$RECOVERY_ROOT/extraction" \
  --report-root "$RECOVERY_ROOT/plan-v1" \
  --public-report results/openneuro_validation/dicom_metadata_v1
```

Both steps can optionally receive `--subjects 143 144` for a restricted pilot.
Extraction automatically skips checksum-verified completed participants.
An interrupted participant gets a new attempt directory; the old attempt is
preserved. A lock prevents duplicate extraction for the same work root.
Re-running `plan` needs a fresh private report directory; existing patches are
never overwritten. Missing DICOM participant folders are reported, not guessed.
The 10-GiB free-space guard before each new participant is a safety minimum,
not an estimate of the total required disk space.

The only shareable outputs are `matching.tsv` and `summary.json` in the public
report directory. They contain BIDS paths, counts, field names and status codes,
not private DICOM values, raw source paths or UIDs. Commit these for review:

```bash
git add results/openneuro_validation/dicom_metadata_v1/matching.tsv \
        results/openneuro_validation/dicom_metadata_v1/summary.json
git commit -m "Audit DICOM-backed metadata recovery matches"
git push origin main
```

## Apply after reviewing that preview

```bash
python3 code/recover_dicom_metadata.py apply \
  --dataset-root "$DATASET_ROOT" \
  --patch "$RECOVERY_ROOT/plan-v1/patch.json" \
  --backup-root "$RECOVERY_ROOT/backup-v1" &&
python3 code/validate_openneuro_full_dataset.py \
  --dataset-root "$DATASET_ROOT" \
  --output-dir "$RECOVERY_ROOT/validation-v1" &&
python3 code/summarize_bids_validation.py \
  "$RECOVERY_ROOT/validation-v1/validation.json"
```

The patch validates all planned changes and backs up all original JSON files
before the first replacement. It uses atomic replacements, preserving earlier
hard-linked staging copies. Re-run the identical apply command to resume; do
not remove its backup. Any changed input or backup checksum stops application.
Validation outputs require a fresh output directory if already generated.
The old sparse upload/recovery trees are **not** refreshed by this operation;
remote release staging and deletion review remain separate tasks.

## Warnings that this patch deliberately does not manufacture away

The baseline contains up to 2,004 missing coil/gradient fields and 150 missing
fieldmap timing fields that this recovery may address; actual recovery depends
on DICOM coverage and successful matching. Remaining categories include:

- **668 PartialFourierDirection recommendations:** pilot fractions are 1.
  No arbitrary direction or placeholder is inserted, and the known fraction
  is not removed to silence validation. Review any actual fractions below 1
  separately across the complete dataset.
- **777 task ontology recommendations:** CogAtlasID/CogPOID require a genuinely
  matching task/ratings concept, not a convenient but incorrect identifier.
- **HEDVersion and SourceDatasets:** do not invent HED annotations, schema use,
  or source-dataset relationships. These are not scanner metadata.
- **Participant-ID mismatch:** the saved cleanup inventory has 50 participant
  rows and 48 additional `sub-2*` directories excluded by `.bidsignore`. Their
  contents and intended release scope need reconciliation; this script neither
  deletes those directories nor fabricates participant records.

No warnings are suppressed or downgraded. Revalidate the complete candidate
dataset, inspect unresolved cases, and only then prepare a reviewed remote
update. Missing optional metadata is preferable to false scientific metadata.
