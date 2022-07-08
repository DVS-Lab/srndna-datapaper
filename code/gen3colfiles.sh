#!/usr/bin/env bash

# this script will convert your BIDS *events.tsv files into the 3-col format for FSL
# it relies on Tom Nichols' converter, which we store locally under /data/tools
# https://github.com/bids-standard/bidsutils


scriptdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
maindir="$(dirname "$scriptdir")"
baseout=${maindir}/derivatives/fsl/EVfiles
if [ ! -d ${baseout} ]; then
  mkdir -p $baseout
fi

sub=$1
nruns=$2

for run in `seq $nruns`; do
  input=${maindir}/bids/sub-${sub}/func/sub-${sub}_task-trust_run-0${run}_events.tsv
  output=${baseout}/sub-${sub}/trust
  mkdir -p $output
  if [ -e $input ]; then
    bash /data/tools/bidsutils/BIDSto3col/BIDSto3col.sh $input ${output}/run-0${run}
  else
    echo "PATH ERROR: cannot locate ${input}."
    exit
  fi
done
for run in 1 2; do
  input=${maindir}/bids/sub-${sub}/func/sub-${sub}_task-sharedreward_run-0${run}_events.tsv
  output=${baseout}/sub-${sub}/sharedreward
  mkdir -p $output
  if [ -e $input ]; then
    bash /data/tools/bidsutils/BIDSto3col/BIDSto3col.sh $input ${output}/run-0${run}
  else
    echo "PATH ERROR: cannot locate ${input}."
    exit
  fi
done
for run in 1 2; do
  input=${maindir}/bids/sub-${sub}/func/sub-${sub}_task-ultimatum_run-0${run}_events.tsv
  output=${baseout}/sub-${sub}/ultimatum-pmod
  mkdir -p $output
  if [ -e $input ]; then
    bash /data/tools/bidsutils/BIDSto3col/BIDSto3col.sh -h Offer $input ${output}/run-0${run}
  else
    echo "PATH ERROR: cannot locate ${input}."
    exit
  fi

  output=${baseout}/sub-${sub}/ultimatum-rt
  mkdir -p $output
  if [ -e $input ]; then
    bash /data/tools/bidsutils/BIDSto3col/BIDSto3col.sh -h response_time $input ${output}/run-0${run}
  else
    echo "PATH ERROR: cannot locate ${input}."
    exit
  fi
done
