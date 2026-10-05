# Auxiliary friends' task records — not the primary BIDS sample

These exports are not part of the 50-participant imaging dataset or its
OpenNeuro release. The legacy `sub-2xx` files remain excluded by `.bidsignore`.
Demographic and acquisition records are incomplete. A parseable single
acquisition does not establish participant identity or suitability for analysis.

The audit inventories 301 legacy runs from 48 identifiers. It exports 290
runs and holds 11 ambiguous runs; no repeated acquisition is chosen by guesswork.
See `../../results/friend_behavior/export_manifest.tsv` for source hashes,
cross-identifier matches, and exclusions, and
`../../code/FRIEND_BEHAVIOR_EXPORT.md` for methods and regeneration commands.

Task-specific JSON dictionaries describe the exported columns. Files contain
one row per source trial, not the repeated rows of legacy modeling events.
Original source logs and legacy event files have not been edited or deleted.
