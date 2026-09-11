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
- Shared Reward files contain partner-by-outcome ratings on an observed -5--5
  scale. Existing analysis code maps trait 0 to win and trait 1 to loss. The
  source acquisition script is absent. Session 2 is provisionally labeled
  post-task because it is the only protocol-wide acquisition. The lone session
  1 file, for sub-104, remains unresolved.

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
- Ten imaging-participant files contain two complete acquisition blocks. Both
  blocks are preserved in `ratings_normalized_rows.tsv`; none is silently
  selected. Across the complete source tree, 23 files contain multiple blocks.
  One behavioral-only file has two exactly identical blocks and can be safely
  collapsed; the other repeated blocks contain changed ratings.
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
- `ratings_repeat_review.tsv`: repeated acquisition blocks and the unresolved
  Shared Reward session-1 file.

Before generating `*_beh.tsv`, resolve whether changed repeated blocks should
be published as separate `run-01`/`run-02` acquisitions or whether the final
block is an authoritative replacement. The repository import timestamps do not
answer that question because all source files entered this repository in one
bulk commit in 2022.
