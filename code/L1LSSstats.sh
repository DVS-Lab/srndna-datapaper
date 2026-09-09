#!/usr/bin/env bash

# Run one activation-only least-squares-separate (LSS) model in FSL FEAT.
set -euo pipefail

usage() {
	echo "usage: $0 SUBJECT RUN TRIAL [TASK] [--force]" >&2
}

if (( $# < 3 || $# > 5 )); then
	usage
	exit 2
fi
sub=${1#sub-}
run=${2#run-}
trial=$3
TASK=${4:-ultimatum}
force=${5:-}

case "$TASK" in
	ultimatum|trust|sharedreward) ;;
	*) echo "unsupported task: $TASK" >&2; exit 2 ;;
esac
if [[ -n "$force" && "$force" != "--force" ]]; then
	usage
	exit 2
fi
if ! [[ "$sub" =~ ^[0-9]+$ && "$run" =~ ^[0-9]+$ && "$trial" =~ ^[0-9]+$ ]] \
	|| (( 10#$run < 1 || 10#$trial < 1 )); then
	echo "subject must be numeric; run and trial must be positive integers" >&2
	exit 2
fi
run=$((10#$run))
trial=$((10#$trial))
run_padded=$(printf '%02d' "$run")
trial_padded=$(printf '%02d' "$trial")

for command in feat fslnvols; do
	if ! command -v "$command" >/dev/null 2>&1; then
		echo "required FSL command not found: $command" >&2
		exit 1
	fi
done

scriptdir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(dirname "$scriptdir")"
dataset_root=${SRNDNA_DATASET_ROOT:-$repo_root}
logs="${dataset_root}/logs"
main_output="${dataset_root}/derivatives/fsl/sub-${sub}"
mkdir -p "$logs" "$main_output"

data="${dataset_root}/derivatives/fmriprep/sub-${sub}/func/sub-${sub}_task-${TASK}_run-${run}_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
confounds="${dataset_root}/derivatives/fsl/confounds/sub-${sub}/sub-${sub}_task-${TASK}_run-${run}_desc-fslConfounds.tsv"
evdir="${dataset_root}/derivatives/fsl/EVfiles/sub-${sub}/SingleTrialEVs/task-${TASK}/run${run_padded}"
single_trial="${evdir}/trialmodel-${trial}_estimage-single.tsv"
other_trials="${evdir}/trialmodel-${trial}_estimage-other.tsv"
decision_phase="${evdir}/trialmodel-decisionphase_.tsv"
template="${repo_root}/templates/L1LSS_task-${TASK}_model-01_type-act.fsf"

for required_file in "$data" "$confounds" "$single_trial" "$other_trials" "$template"; do
	if [[ ! -s "$required_file" ]]; then
		echo "missing required LSS input: $required_file" >&2
		exit 1
	fi
done
if [[ "$TASK" == "trust" && ! -s "$decision_phase" ]]; then
	echo "missing Trust decision-phase EV: $decision_phase" >&2
	exit 1
fi

nvolumes=$(fslnvols "$data")
confound_rows=$(wc -l < "$confounds")
if (( confound_rows != nvolumes )); then
	echo "confound/BOLD row mismatch for sub-${sub} task-${TASK} run-${run}: ${confound_rows} != ${nvolumes}" >&2
	exit 1
fi

output="${main_output}/L1LSS_task-${TASK}_model-01_type-act_run-${run_padded}_trial-${trial_padded}"
rendered_template="${main_output}/L1LSS_sub-${sub}_task-${TASK}_model-01_type-act_run-${run_padded}_trial-${trial_padded}.fsf"
trial_output_dir="${main_output}/LSS-images_task-${TASK}_model-01_type-act_run-${run_padded}"
trial_output="${trial_output_dir}/zstat_trial-${trial_padded}.nii.gz"
temporary_output="${trial_output}.tmp"
fingerprint_file="${trial_output%.nii.gz}.lss-inputs.cksum"
temporary_fingerprint="${fingerprint_file}.tmp"
mkdir -p "$trial_output_dir"

if [[ -s "$trial_output" && "$force" != "--force" ]]; then
	exit 0
fi
echo "running: $output" >> "${logs}/re-runL1LSS.log"
rm -rf -- "${output}.feat"

sed_args=(
	-e "s@OUTPUT@${output}@g"
	-e "s@DATA@${data}@g"
	-e "s@SINGLETRIAL@${single_trial}@g"
	-e "s@OTHERTRIAL@${other_trials}@g"
	-e "s@CONFOUNDEVS@${confounds}@g"
	-e "s@NVOLUMES@${nvolumes}@g"
)
if [[ "$TASK" == "trust" ]]; then
	sed_args+=( -e "s@DECISIONPHASE@${decision_phase}@g" )
fi
sed "${sed_args[@]}" "$template" > "$rendered_template"
feat "$rendered_template"

zstat="${output}.feat/stats/zstat1.nii.gz"
if [[ ! -s "$zstat" ]]; then
	echo "FEAT completed without the expected zstat1: ${output}.feat" >&2
	exit 1
fi
cp "$zstat" "$temporary_output"
mv "$temporary_output" "$trial_output"
fingerprint_inputs=(
	"$single_trial"
	"$other_trials"
	"$confounds"
	"$template"
	"${scriptdir}/L1LSSstats.sh"
)
if [[ "$TASK" == "trust" ]]; then
	fingerprint_inputs+=("$decision_phase")
fi
bash "${scriptdir}/lss_input_fingerprint.sh" "${fingerprint_inputs[@]}" \
	> "$temporary_fingerprint"
mv "$temporary_fingerprint" "$fingerprint_file"
rm -rf -- "${output}.feat"
