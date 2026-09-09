#!/usr/bin/env bash

# Pack one completed participant/run of trial-wise LSS z-statistics into 4D.
set -euo pipefail

usage() {
	echo "usage: $0 {ultimatum|trust|sharedreward} SUBJECT RUN" >&2
}

if (( $# != 3 )); then
	usage
	exit 2
fi

TASK=$1
sub=${2#sub-}
run=${3#run-}
case "$TASK" in
	ultimatum|trust|sharedreward) ;;
	*) usage; exit 2 ;;
esac
if ! [[ "$sub" =~ ^[0-9]+$ && "$run" =~ ^[0-9]+$ ]] || (( 10#$run < 1 )); then
	usage
	exit 2
fi
run=$((10#$run))
run_padded=$(printf '%02d' "$run")

scriptdir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
maindir="$(dirname "$scriptdir")"
dataset_root=${SRNDNA_DATASET_ROOT:-$maindir}
evdir="${dataset_root}/derivatives/fsl/EVfiles/sub-${sub}/SingleTrialEVs/task-${TASK}/run${run_padded}"
zdir="${dataset_root}/derivatives/fsl/sub-${sub}/LSS-images_task-${TASK}_model-01_type-act_run-${run_padded}"
outdir="${dataset_root}/derivatives/single_trials/sub-${sub}"
output="${outdir}/sub-${sub}_task-${TASK}_run-${run_padded}_singletrial-Act.nii.gz"
temporary="${outdir}/.sub-${sub}_task-${TASK}_run-${run_padded}_singletrial-Act.tmp-$$.nii.gz"

for command in fslmerge fslnvols; do
	if ! command -v "$command" >/dev/null 2>&1; then
		echo "required FSL command not found: $command" >&2
		exit 1
	fi
done

ev_files=()
while IFS= read -r ev_file; do
	ev_files+=("$ev_file")
done < <(
	find "$evdir" -maxdepth 1 -type f -name 'trialmodel-*_estimage-single.tsv' \
		| sort -V
)
if (( ${#ev_files[@]} == 0 )); then
	echo "no single-trial EV files found in $evdir" >&2
	exit 1
fi

images=()
for ev_file in "${ev_files[@]}"; do
	filename=${ev_file##*/}
	if [[ "$filename" =~ ^trialmodel-([0-9]+)_estimage-single\.tsv$ ]]; then
		trial=$((10#${BASH_REMATCH[1]}))
	else
		echo "could not parse EV filename: $ev_file" >&2
		exit 1
	fi
	trial_padded=$(printf '%02d' "$trial")
	image="${zdir}/zstat_trial-${trial_padded}.nii.gz"
	if [[ ! -s "$image" ]]; then
		echo "missing completed trial image: $image" >&2
		exit 1
	fi
	images+=("$image")
done

mkdir -p "$outdir"
trap 'rm -f "$temporary"' EXIT
fslmerge -t "$temporary" "${images[@]}"
nvolumes=$(fslnvols "$temporary")
if (( nvolumes != ${#images[@]} )); then
	echo "packed volume count mismatch: expected ${#images[@]}, found $nvolumes" >&2
	exit 1
fi
mv "$temporary" "$output"
trap - EXIT
echo "Packed ${#images[@]} trials: $output"
