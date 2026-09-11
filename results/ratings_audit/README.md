# Task-ratings audit

This audit inventories the partner-rating CSV files under
`stimuli/psychopy/logs` before any new files are added to the BIDS dataset.
Run it from the repository root with:

```bash
python3 code/audit_task_ratings.py
```

## BIDS representation

The ratings are item-level responses linked to the Ultimatum, Trust, and
Shared Reward tasks. They are not participant-level questionnaire summaries.
Because they do not contain onset and duration, the intended representation is
one or more subject-level `sub-*/beh/*_beh.tsv` files with JSON sidecars, not a
root-level `phenotype/` table. The audit does not yet write into `bids/`.

## Protocol evidence

- `UG_pre_post_Ratings.py` explicitly defines suffix 1 as pre-task and suffix 2
  as post-task. Ratings use a 0--10 scale. Partner codes 1, 2, and 3 denote the
  computer, dissimilar partner, and similar partner. Pre-task ratings cover
  fairness and likeability; post-task ratings add anger and satisfaction.
- The Investment files use the same suffix 1/2 pre/post convention and a 0--10
  scale. Partner codes denote the computer, stranger, and friend; traits denote
  approachability, likeability, and trustworthiness. The flat-file acquisition
  source survives only as `Trust_Pre_Post_Ratings.pyc` in the original public
  `DVS-Lab/srndna` repository. The local Builder-generated `TrustRatings.py`
  uses a different output schema and 0--100 scale and therefore is not the
  script that generated these CSV files.
- Shared Reward files contain partner-by-outcome ratings on a -5--5 scale.
  Existing analysis code maps trait 0 to win and trait 1 to loss. The correct
  `SR_postRatings.py` generator was recovered from the original `DVS-Lab/srndna`
  history at content revision `b4f7132`, before its conflicted-merge deletion
  in `261d98e`, and restored byte-for-byte beside its unchanged `SRratings.csv`
  input. It writes the observed `SR-Ratings` schema. The script is preserved as
  acquisition provenance rather than maintained software: it uses Python 2-era
  PsychoPy syntax and refers to `SRRatings.csv` with different capitalization.
  A different Builder-generated script, `SharedReward_PostRatings.py`, used an
  incorrect -50--50 scale and was explicitly removed from `srndna` in 2019.
- The study decision rule for repeated Shared Reward ratings retains the second
  set and excludes the first. Accordingly, sub-104's session-1 file is
  superseded by session 2, and the final complete block is retained from the
  two-block sub-144 session-2 file. Both source sets remain represented in the
  normalized audit table for provenance.

## Initial findings

- 442 ratings-like files were inventoried: 441 files matching a recognized
  naming convention and one unassigned `sub_Investment-Ratings-.csv` file.
- The source files contain 4,026 normalized item responses across imaging and
  behavioral-only participants.
- Of the source files, 221 belong to the 50 participants currently listed in
  `bids/participants.tsv`.
- Among those 50 participants, 30 expected task/timepoint measurements are
  absent. Most missingness is concentrated in sub-106, sub-109, sub-110, and
  sub-143; Shared Reward ratings are also absent for seven additional imaging
  participants.
- Ten imaging-participant files contain two complete acquisition blocks. All
  blocks remain preserved in `ratings_normalized_rows.tsv`. The Shared Reward
  rule resolves one of these files by retaining its last block; the remaining
  nine still require review. Across the complete source tree, 23 files contain
  multiple blocks. One behavioral-only file has two exactly identical blocks
  and can be collapsed, one Shared Reward file is resolved by the second-set
  rule, and 21 changed repeats remain unresolved.
- Several files from different participants have identical byte content. The
  inventory records every matching path. Most are uniform/default response
  patterns, so identical content is a review flag rather than evidence that a
  file was assigned to the wrong participant.

## Outputs

- `ratings_file_inventory.tsv`: file identity, hashes, schemas, block counts,
  content matches, and file-level problems.
- `ratings_normalized_rows.tsv`: every parsed rating, retaining participant,
  source file, source session, and source block.
- `ratings_subject_coverage.tsv`: expected pre/post coverage for the 50 current
  BIDS participants.
- `ratings_repeat_review.tsv`: repeated acquisition blocks, their current
  resolution status, and the superseded Shared Reward session-1 file.

Before generating `*_beh.tsv`, resolve whether the remaining changed repeated
blocks should be published as separate `run-01`/`run-02` acquisitions or
whether the final block is an authoritative replacement.

## Timestamp provenance

The `srndna-datapaper` import commit dates are not acquisition dates because
the files entered this repository in one bulk copy in 2022. The original
`DVS-Lab/srndna` history provides more useful transfer provenance:

- All 46 BIDS participants with both imaging and ratings followed the fixed MRI
  order Trust, Shared Reward, then Ultimatum after correcting the documented
  100-year date shift in `*_scans.tsv`.
- The first ratings commit occurred after the MRI session for all 46. It was on
  the same calendar day for 29, within 24 hours for 30, and within seven days
  for 36. Older early-study records were uploaded in later batches.
- For all 46, ratings and raw task CSVs share at least one original participant
  commit. For 43, every ratings and raw task file was introduced in the same
  commit set; the other three had raw task files split across extra commits.
- Every repeated ratings block was already present when its source file first
  entered `srndna`; later commits did not append or overwrite those blocks.
  Git therefore supports participant/session assignment but cannot timestamp
  the individual repeated blocks within a file.
