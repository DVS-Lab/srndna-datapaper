# SRNDNA: Data Management and Preprocessing
This repository contains the final code for managing and processing all of the data in our SRDNDA project. The data live on OpenNeuro with the citation below:

David V. Smith and Dominic Fareri (2021). Social Reward Processing and Decision Making in Younger and Older Adults. OpenNeuro. [Dataset] doi: 10.18112/openneuro.ds003745.v1.0.0


## A few prerequisites and recommendations
- Understand BIDS and be comfortable navigating Linux
- Install [FSL](https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FslInstallation)
- Install [miniconda or anaconda](https://stackoverflow.com/questions/45421163/anaconda-vs-miniconda)
- Install PyDeface: `pip install pydeface`
- Make singularity containers for heudiconv (version: 0.9.0), mriqc (version: 0.16.1), and fmriprep (version: 20.2.3).


## Notes on repository organization and files
- Raw DICOMS (an input to heudiconv) are only accessible locally (Smith Lab Linux: /data/sourcedata)
- Some of the contents of this repository are not tracked (.gitignore) because the files are large and we do not yet have a nice workflow for datalad. Note that we only track key text files in `bids` and `derivatives`.
- Tracked folders and their contents:
  - `code`: analysis code
  - `derivatives`: stores derivates from our scripts
  - `bids`: contains the standardized "raw" in BIDS format (output of heudiconv)
  - `stimuli`: psychopy scripts and matlab scripts for delivering stimuli and organizing output. This directory also contains the sourcedata for the raw behavioral data.


## Downloading Data and Running Preprocessing
```
# get data via datalad
git clone https://github.com/DVS-Lab/srndna-datapaper
cd srndna-datapaper
datalad clone https://github.com/OpenNeuroDatasets/ds003745.git bids
# you can get all of the data with the commands below:
cd bids
datalad get sub-*

# run preprocessing and generate confounds and timing files for analyses
bash code/run_fmriprep.sh
python code/MakeConfounds.py --fmriprepDir="derivatives/fmriprep"
bash code/run_gen3colfiles.sh

```


## Acknowledgments
This work was supported, in part, by grants from the National Institutes of Health (R21-MH113917 and R03-DA046733 to DVS and R15-MH122927 to DSF) and a Pilot Grant from the Scientific Research Network on Decision Neuroscience and Aging [to DVS; Subaward of NIH R24-AG054355 (PI Gregory Samanez-Larkin)]. We thank Elizabeth Beard for assistance with task coding, Dennis Desalme, Ben Muzekari, Isaac Levy, Gemma Goldstein, and Srikar Katta for assistance with participant recruitment and data collection, and Jeffrey Dennison for assistance with data processing. DVS was a Research Fellow of the Public Policy Lab at Temple University during the preparation of the manuscript (2019-2020 academic year).

[openneuro]: https://openneuro.org/
