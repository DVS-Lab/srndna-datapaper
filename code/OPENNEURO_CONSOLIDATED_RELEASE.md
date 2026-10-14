# Consolidated ds003745 2.2.0 release

This replaces the old sparse-staging/recovery upload instructions. It prepares
**one draft update**, not two releases. Do not push the old recovery commit:
it contains text stored with Git symlink mode. Keep that repository and all
backups for recovery, but do not use it as the parent of a release commit.

## Preconditions and scope

The complete plain-files download must already contain the completed repairs:
50 primary participants, 418 raw BOLD images, 668 losslessly header-cleaned raw
images, DICOM-backed metadata, 220 ratings tables, four sub-144 event repairs,
218 unsmoothed Trust single-trial images, and four corrected sub-144 single-trial
images. No models are rerun. No additional imaging-data corrections are inferred.

The workflow incorporates all of these plus the exact **48 file exclusions**
recorded for sub-134/sub-138 Trust run-05, their scans-table edits and fieldmap
references. Excluded files remain recoverable from previous snapshots and the
existing local backups. Auxiliary sub-2xx content remains unchanged and ignored;
it is not added to the 50-participant inventory.

There are **890 candidate annex files** (668 raw images plus 222 single-trial
images). The raw images have new compressed hashes after gzip privacy-header
cleanup; their decompressed contents are unchanged. Consequently, this update
is larger than the earlier 1.9-GB single-trial upload. Allow roughly 25 GB for
the fresh local candidate; an exact free-space check runs before creating it.

## Linux1

```bash
tmux new -As srndna-openneuro
```

Inside tmux:

```bash
cd /ZPOOL/data/projects/srndna-datapaper-code &&
git pull --ff-only &&
bash code/run_openneuro_consolidated_release.sh
```

Detach with Ctrl-b then d. To resume after interruption, rerun the same command.
The preparation verifies checksums again; a finished candidate is reused and
remote objects are checked individually before deciding whether to transfer.
An interrupted initial fetch can resume in the directory marked as owned by
this workflow. An unexpected existing directory or changed remote parent stops
for inspection. Do not remove checkpoints, force-push, or retry the old commit.

The three stages can also be invoked separately with
`finalize_openneuro_release.py prepare|build|upload --work-root ... --report-dir ...`.
Only `upload` writes to OpenNeuro. It uses the documented native Git/annex
interface and existing OpenNeuro CLI login, not the stalled JavaScript Git
packing path. No API keys are printed or embedded in URLs. The credential
helper configuration is local to the new candidate repository.

## Gates and receipts

1. Hash all approved sources; compare raw image hashes with the completed
   lossless-cleanup manifest. Require recovered JSON fields and PartialFourier=1.
2. Run the pinned full-dataset validator. Require zero errors, only the already
   reviewed warning categories, and exact agreement of the 50 participant IDs.
3. Create a fresh candidate from OpenNeuro main. The expected parent is published
   2.1.1 (`cc3fee633f...`); a different remote draft requires reconciliation.
4. Use explicit regular-file modes for text and native git-annex for images.
   Check checksums, annex symlink targets, the exact changed-path allowlist,
   exclusions, and a clean working tree before committing.
5. Physically check each annex object on OpenNeuro; upload missing objects and
   verify them. Then fast-forward the annex branch and main, without force.
6. Record success only when the remote main hash equals the candidate hash.

The candidate and private checkpoints live under
`/ZPOOL/data/scratch/srndna-datapaper-openneuro-2.2.0/consolidated-v1`.
Small public reports/logs go to `results/openneuro_release/consolidated-v1`.
Commit those reports even if a stage stops, so its failure can be inspected.

```bash
cd /ZPOOL/data/projects/srndna-datapaper-code &&
git add results/openneuro_release/consolidated-v1 &&
git diff --cached --stat &&
git commit -m "Record consolidated OpenNeuro release checks and upload outcome" &&
git push origin main
```

## Remaining validator recommendations

The last complete report has zero errors and 1,529 warning instances in six
groups. These are not hidden by the workflow. Partial-Fourier direction is not
applicable when the confirmed fraction is 1; appropriate ratings ontology IDs
are unverified; HEDVersion and SourceDatasets are not applicable to unannotated
original acquisition. Do not fabricate values to obtain a zero-warning badge.

The participant warning persists even though the reported 50 subjects and 50
participant records agree. Validator 3.0.1 constructs its subject-directory
comparison from root directories, including the ignored sub-2xx directories.
The release audit separately requires exact primary-ID agreement and retains
the auxiliary exclusion. It does not add 48 demographic rows or silently
remove the auxiliary data. A changed primary inventory stops the release.

After upload, inspect **the actual remote draft** and its validation, then
publish **2.2.0** in OpenNeuro. No snapshot is created automatically, and a
successful Git push is not presented as successful server-side validation.

References: [OpenNeuro Git/annex workflow](https://docs.openneuro.org/git),
[validator 3.0.1 subject context](https://jsr.io/@bids/validator/3.0.1/src/schema/context.ts).
