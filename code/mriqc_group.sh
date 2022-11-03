#!/usr/bin/env bash

# Example code for running group-level MRIQC


# ensure paths are correct irrespective from where user runs the script
codedir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
dsroot="$(dirname "$codedir")"



# make bids folder if it doesn't exist
if [ ! -d $dsroot/bids ]; then
	mkdir -p $dsroot/bids
fi



# make scratch
scratch=/data/scratch/`whoami`
if [ ! -d $scratch ]; then
	mkdir -p $scratch
fi

# no space left on device error for v0.15.2 and higher
# https://neurostars.org/t/mriqc-no-space-left-on-device-error/16187/1
# https://github.com/poldracklab/mriqc/issues/850
TEMPLATEFLOW_DIR=/data/tools/templateflow
export SINGULARITYENV_TEMPLATEFLOW_HOME=/opt/templateflow
singularity run --cleanenv \
-B ${TEMPLATEFLOW_DIR}:/opt/templateflow \
-B $dsroot/bids:/data \
-B $dsroot/derivatives/mriqc:/out \
-B $scratch:/scratch \
/data/tools/mriqc-22.0.6.simg \
/data /out \
group -w /scratch
