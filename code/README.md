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

`recover_sub144_ultimatum_events.py` reconstructs the two sub-144 Ultimatum
events files from the second complete session stored in each concatenated raw
acquisition log. It updates the BIDS file and both tracked legacy mirrors. Run
`python3 code/recover_sub144_ultimatum_events.py --check` to verify that the
tracked files remain reproducible from the raw logs.

## Trust single-trial models

The Trust LSS template uses no additional spatial smoothing, consistent with
the other task-specific LSS templates. To rebuild the Trust single-trial EVs
and force regeneration of the LSS images on a Linux system with FSL and the
untracked imaging derivatives available:

```bash
python3 code/makeSingleTrials_trust.py --clean
NCORES=30 bash code/run_L1LSSstats.sh trust --force
```

Set `SUBJECTS="104 105"` before the second command to limit a test run. The
runner writes each completed z-statistic through a temporary file before
replacing the prior image.




[fmriprep]: http://fmriprep.readthedocs.io/en/latest/index.html
