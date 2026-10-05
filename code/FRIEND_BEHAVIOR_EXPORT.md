# Behavioral-only participants and task metadata

The primary dataset contains **50 imaging participants**. Its participant
table is unchanged and `.bidsignore` continues to exclude all `sub-2*` files.
The 48 legacy `sub-2xx` directories contain auxiliary friends' task records,
not additional members of the imaging sample. Demographics and acquisition
documentation are incomplete, and some source identities remain unresolved.
These records require independent evaluation before analysis.

## Reproducible export

```bash
python3 code/export_friend_behavior.py
python3 code/export_friend_behavior.py --write
```

The first command previews. The second writes trial-level files under
`supplementary/friend_behavior/` and saves `results/friend_behavior/`.
It never updates `bids/`, the participant inventory, or the OpenNeuro staging
tree. The two game-specific JSON dictionaries live in the supplementary root.
Only task runs already represented by the published friend event files are
in scope. Additional source-only participants and friend ratings are not
silently added. Source logs and old event files are never edited or deleted.
Rerunning with unchanged sources is idempotent; divergent existing exports
are rejected before writing. `--write` is not an OpenNeuro upload.

Each `acq-game_beh.tsv` row is one original task trial. The exporter preserves
missed trials, real zero investments, choices, conditions and source-clock
timestamps. RT is available for all recorded responses, including block-first
trials. Original event files contain repeated modeling rows and are not used
as trial-level observations. The new game-specific JSON dictionaries override
the general ratings task descriptions; pre/post rating files are unchanged.

`export_manifest.tsv` records original log and legacy-event hashes, acquisition
counts, trial counts, output hashes and unresolved identity issues. Multiple
headers, trial-counter resets, invalid values and exact copies under another
source owner are not resolved by guessing. The final-complete-attempt rule
for ratings is not automatically applied to these task logs.

The current audit inventories 301 runs: 290 exports and 11 held for source
review. A successful export means the audit completed, not that participant
identity is certified. Check `summary.json` and per-run statuses before use.
These supplementary exports are not included in the primary OpenNeuro release;
their unresolved records do not block it. The release builder independently
enforces the 50-participant inventory and the original `sub-2*` exclusion.
No legacy friend event file needs to be deleted from OpenNeuro by this change.

## Metadata decisions

- No partial-Fourier acquisition was used (confirmed by the investigators).
  Preserve `PartialFourier: 1`; `PartialFourierDirection` is inapplicable and
  remains absent. Do not fabricate a direction or remove the fraction to
  silence the validator. Recommended-field warnings may remain.
- Shared Reward is a social-sharing adaptation of the Delgado card-guessing
  paradigm, following the Fareri social-reward extension. Its BOLD sidecar
  links to Cognitive Atlas `trm_550b5c1a7f4db` and describes the different
  stakes and partner manipulation. This is a parent-paradigm mapping.
- Parent-game ontology identifiers are not applied to partner ratings.
  Trust and Ultimatum game identifiers remain on the game recordings.
- No CogPO identifier is asserted without a verified matching definition.
  HEDVersion is absent because no HED tags are provided; SourceDatasets is
  absent for this original acquired dataset, not replaced with a self-citation.

References:
- https://bids-specification.readthedocs.io/en/stable/modality-specific-files/behavioral-experiments.html
- https://bids-specification.readthedocs.io/en/stable/modality-agnostic-files/data-summary-files.html
- https://www.cognitiveatlas.org/task/id/trm_550b5c1a7f4db/

## Linux1 validation

After committing and pulling the code and generated small files, preview the
existing full-download repair workflow with a **new backup directory**.
Do not reuse an old sparse staging tree or assume that its manifest describes
these metadata updates. Preserve
the earlier DICOM metadata corrections and validate the complete download
again before any remote update. See `OPENNEURO_VALIDATION_REPAIR.md`.
