# Analysis Code

## Overview and disclaimers
- run_* scripts loop through a list of subjects for a given script; e.g., run_fmriprep.sh loops all subjects through the fmriprep.sh script.
- paths to input/output data should work without error, but check package/software installation

## Scripts used to generate public data
Some files cannot be shared publicly. And some raw source data are in non-standard format. The scripts below helped us go from the raw source data to the standardized public data:
- `prepdata.sh` -- runs [heudiconv](https://github.com/nipy/heudiconv) to convert dicoms to BIDS, defaces structural scans with pydeface, and runs [mriqc](https://mriqc.readthedocs.io/en/latest/index.html)
  - [heuristics.py](https://github.com/DVS-Lab/srndna-data/blob/main/code/heuristics.py) sets the heuristics for heudiconv
  - [addIntendedFor.py](https://github.com/DVS-Lab/srndna-data/blob/main/code/addIntendedFor.py) adds the "IntendedFor" field for the fmap files
- Code for stimuli control/presentation and conversion of raw behavioral data to BIDS are in [stimuli](https://github.com/DVS-Lab/srndna-data/tree/main/stimuli)

## Analyses  
- Analysis scripts are in task-specific repositories
- e.g., https://github.com/DVS-Lab/srndna-trustgame

## Data corrections

`recover_sub144_ultimatum_events.py` and
`recover_sub144_sharedreward_events.py` reconstruct the sub-144 event files
from the second complete session stored in each concatenated raw acquisition
log. In both tasks the first session reproduces the separately recovered
sub-143 files, while the second contains sub-144's distinct responses and
timing. Run both scripts with `--check` to verify that the tracked files remain
reproducible from the raw logs.

To apply these verified files to a separately downloaded OpenNeuro dataset,
first preview the guarded deployment and then explicitly apply it with a
backup directory outside the dataset:

```bash
python3 code/apply_openneuro_event_repairs.py \
  --dataset-root /path/to/openneuro-dataset

python3 code/apply_openneuro_event_repairs.py \
  --dataset-root /path/to/openneuro-dataset \
  --backup-root /path/to/external-backup --apply
```

The deployment refuses unexpected destination hashes, keeps the published
files in the backup directory, uses atomic replacement, and writes a SHA-256
manifest. It updates optional legacy Ultimatum mirrors only when those files
are present in the downloaded dataset.

## Single-trial LSS models

`make_fsl_confounds.py` extracts cosine terms, non-steady-state indicators,
six rigid-body motion parameters, six aCompCor components, and framewise
displacement from each fMRIPrep confounds table. Missing numeric values are
replaced with zero for FSL. Write these matrices to the external LSS work root:

```bash
python3 code/make_fsl_confounds.py trust \
  --dataset-root /path/to/openneuro-dataset \
  --output-root /path/to/lss-work/confounds \
  --all-subjects --dry-run
```

`makeSingleTrials.py` generates EV files for Trust, Ultimatum, and
SharedReward. `run_L1LSSstats.sh` requires an explicit participant scope,
supports participant/run subsets, performs a dry-run preflight, and can pack
the trial-wise z-statistics into the public 4D files under
`derivatives/single_trials`.

The analysis code and downloaded OpenNeuro dataset may live in separate
directories. Pass the OpenNeuro BIDS root (the directory containing `sub-*`
and `derivatives/`) with `--dataset-root`; templates are always read from this
GitHub repository. For production reruns, put generated EVs and trial-wise
FEAT outputs outside the dataset: pass that directory's `EVfiles` child to the
EV generator with `--output-root`, and pass the directory itself to the runner
with `--work-root`. Only the final packed 4D files are then written into the
OpenNeuro tree.

Always preview a scope before running FEAT:

```bash
python3 code/makeSingleTrials.py trust \
  --dataset-root /path/to/openneuro-dataset \
  --output-root /path/to/lss-work/EVfiles \
  --all-subjects --clean --dry-run

bash code/run_L1LSSstats.sh trust \
  --dataset-root /path/to/openneuro-dataset \
  --work-root /path/to/lss-work \
  --all-subjects --available-runs --jobs 44 \
  --refresh --pack --dry-run
```

Remove `--dry-run` from the EV command first, then from the FEAT command. The
Trust correction should use `--refresh`: it reruns outputs without a matching
content fingerprint for the current template, analysis script, EVs, and
confounds. BOLD inputs are checked for presence without repeatedly hashing the
large images. This remains restartable after interruption because every
successfully corrected trial receives a matching fingerprint. `--force`
instead reruns every trial in the selected scope.

For a repaired subset, repeat `--subject` and `--run` as needed:

```bash
python3 code/makeSingleTrials.py ultimatum \
  --dataset-root /path/to/openneuro-dataset \
  --output-root /path/to/lss-work/EVfiles \
  --subject 144 --run 1 --run 2 --clean --dry-run

bash code/run_L1LSSstats.sh ultimatum \
  --dataset-root /path/to/openneuro-dataset \
  --work-root /path/to/lss-work \
  --subject 144 --run 1 --run 2 --refresh --pack --dry-run
```

Set FEAT concurrency explicitly with `--jobs`; `NCORES` remains supported as a
fallback for legacy invocations. Packing happens only after every selected FEAT
job succeeds. It uses the generated EV files as the trial manifest, checks that
every expected z-statistic exists, verifies the packed volume count, and
atomically replaces the corresponding public 4D file. `--available-runs`
restricts a whole-task rerun to participant-runs with a preprocessed BOLD image;
all other selected inputs are still required and missing confounds remain fatal.

The legacy `makeSingleTrials_trust.py` entry point remains available but now
delegates to the unified generator and requires the same explicit scope.




[fmriprep]: http://fmriprep.readthedocs.io/en/latest/index.html
