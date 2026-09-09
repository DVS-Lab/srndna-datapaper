#!/usr/bin/env bash

# Selectively run and optionally pack trial-wise LSS models for one task.
set -euo pipefail

usage() {
	cat >&2 <<'EOF'
usage: run_L1LSSstats.sh TASK (--all-subjects | --subject ID [...]) [options]

TASK is one of: ultimatum, trust, sharedreward

Options:
  --all-subjects    include every participant with generated EV files
  --subject ID      include one participant; repeatable (144 or sub-144)
  --run RUN         include one run; repeatable (2 or run-02)
  --dataset-root P  OpenNeuro BIDS root containing sub-* and derivatives/
  --work-root P     external root for EVs and trial-wise FEAT intermediates
  --available-runs  select only runs with a preprocessed BOLD image
  --jobs N          run at most N FEAT models concurrently
  --refresh         replace outputs lacking a current input fingerprint
  --force           replace completed trial images in the selected scope
  --pack            pack completed trial images into public 4D derivatives
  --dry-run         validate and report the selected work without running FEAT
  -h, --help        show this help

NCORES remains a fallback for --jobs (default: 30).
EOF
}

if (( $# == 0 )); then
	usage
	exit 2
fi
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
	usage
	exit 0
fi

TASK=$1
shift
case "$TASK" in
	ultimatum|trust|sharedreward) ;;
	*) usage; exit 2 ;;
esac

all_subjects=0
force=0
refresh=0
pack=0
dry_run=0
available_runs=0
dataset_root=
work_root=
jobs=
subjects=()
runs=()
subject_count=0
run_count=0
while (( $# )); do
	case "$1" in
		--all-subjects)
			all_subjects=1
			shift
			;;
		--subject)
			(( $# >= 2 )) || { usage; exit 2; }
			subjects+=("${2#sub-}")
			((subject_count += 1))
			shift 2
			;;
		--run)
			(( $# >= 2 )) || { usage; exit 2; }
			runs+=("${2#run-}")
			((run_count += 1))
			shift 2
			;;
		--dataset-root)
			(( $# >= 2 )) || { usage; exit 2; }
			dataset_root=$2
			shift 2
			;;
		--work-root)
			(( $# >= 2 )) || { usage; exit 2; }
			work_root=$2
			shift 2
			;;
		--available-runs)
			available_runs=1
			shift
			;;
		--jobs)
			(( $# >= 2 )) || { usage; exit 2; }
			jobs=$2
			shift 2
			;;
		--force)
			force=1
			shift
			;;
		--refresh)
			refresh=1
			shift
			;;
		--pack)
			pack=1
			shift
			;;
		--dry-run)
			dry_run=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "unknown argument: $1" >&2
			usage
			exit 2
			;;
	esac
done

if (( all_subjects && subject_count )); then
	echo "choose --all-subjects or --subject, not both" >&2
	exit 2
fi
if (( ! all_subjects && subject_count == 0 )); then
	echo "an explicit scope is required: --all-subjects or --subject ID" >&2
	exit 2
fi
if (( force && refresh )); then
	echo "choose --refresh or --force, not both" >&2
	exit 2
fi
if (( subject_count )); then
	for sub in "${subjects[@]}"; do
		if ! [[ "$sub" =~ ^[0-9]+$ ]]; then
			echo "invalid subject: $sub" >&2
			exit 2
		fi
	done
fi
if (( run_count )); then
	for run in "${runs[@]}"; do
		if ! [[ "$run" =~ ^[0-9]+$ ]] || (( 10#$run < 1 )); then
			echo "invalid run: $run" >&2
			exit 2
		fi
	done
	for index in "${!runs[@]}"; do
		runs[$index]=$((10#${runs[$index]}))
	done
fi

jobs=${jobs:-${NCORES:-30}}
if ! [[ "$jobs" =~ ^[1-9][0-9]*$ ]]; then
	echo "--jobs (or NCORES) must be a positive integer" >&2
	exit 2
fi

scriptdir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
basedir="$(dirname "$scriptdir")"
dataset_root=${dataset_root:-$basedir}
if [[ ! -d "$dataset_root" ]]; then
	echo "dataset root does not exist: $dataset_root" >&2
	exit 1
fi
dataset_root="$(cd "$dataset_root" >/dev/null 2>&1 && pwd)"
work_root=${work_root:-${dataset_root}/derivatives/fsl}
mkdir -p "$work_root"
work_root="$(cd "$work_root" >/dev/null 2>&1 && pwd)"
ev_root="${work_root}/EVfiles"
if [[ ! -d "$ev_root" ]]; then
	echo "EV root does not exist: $ev_root" >&2
	exit 1
fi

contains() {
	local wanted=$1
	shift
	local value
	for value in "$@"; do
		if [[ "$value" == "$wanted" ]]; then
			return 0
		fi
	done
	return 1
}

is_current() {
	local output=$1
	local fingerprint_file=$2
	shift 2
	local expected
	[[ -s "$output" && -s "$fingerprint_file" ]] || return 1
	expected=$(bash "${scriptdir}/lss_input_fingerprint.sh" "$@" 2>/dev/null) || return 1
	[[ "$(<"$fingerprint_file")" == "$expected" ]]
}

all_ev_files=()
while IFS= read -r ev_file; do
	all_ev_files+=("$ev_file")
done < <(
	find "$ev_root" -type f \
		-path "*/SingleTrialEVs/task-${TASK}/run*/trialmodel-*_estimage-single.tsv" \
		| sort -V
)

selected_ev_files=()
selected_current_flags=()
selected_run_keys=()
unavailable_run_keys=()
unavailable_run_count=0
existing=0
current=0
missing_inputs=0
row_count_checks=0
for ev_file in "${all_ev_files[@]}"; do
	if [[ "$ev_file" =~ /sub-([0-9]+)/SingleTrialEVs/task-${TASK}/run([0-9]+)/trialmodel-([0-9]+)_estimage-single\.tsv$ ]]; then
		sub=${BASH_REMATCH[1]}
		run=$((10#${BASH_REMATCH[2]}))
		trial=$((10#${BASH_REMATCH[3]}))
	else
		echo "could not parse EV path: $ev_file" >&2
		exit 1
	fi

	if (( ! all_subjects )) && ! contains "$sub" "${subjects[@]}"; then
		continue
	fi
	if (( run_count )) && ! contains "$run" "${runs[@]}"; then
		continue
	fi
	data="${dataset_root}/derivatives/fmriprep/sub-${sub}/func/sub-${sub}_task-${TASK}_run-${run}_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
	if (( available_runs )) && [[ ! -s "$data" ]]; then
		unavailable_run_keys+=("${sub}:${run}")
		((unavailable_run_count += 1))
		continue
	fi

	selected_ev_files+=("$ev_file")
	selected_run_keys+=("${sub}:${run}")
	other_file="${ev_file/_estimage-single.tsv/_estimage-other.tsv}"
	if [[ ! -s "$other_file" ]]; then
		echo "missing other-trials EV: $other_file" >&2
		((missing_inputs += 1))
	fi
	trial_padded=$(printf '%02d' "$trial")
	output="${work_root}/sub-${sub}/LSS-images_task-${TASK}_model-01_type-act_run-$(printf '%02d' "$run")/zstat_trial-${trial_padded}.nii.gz"
	fingerprint_file="${output%.nii.gz}.lss-inputs.cksum"
	confounds="${work_root}/confounds/sub-${sub}/sub-${sub}_task-${TASK}_run-${run}_desc-fslConfounds.tsv"
	template="${basedir}/templates/L1LSS_task-${TASK}_model-01_type-act.fsf"
	dependencies=("$ev_file" "$other_file" "$confounds" "$template" "${scriptdir}/L1LSSstats.sh")
	if [[ "$TASK" == "trust" ]]; then
		dependencies+=("${ev_root}/sub-${sub}/SingleTrialEVs/task-trust/run$(printf '%02d' "$run")/trialmodel-decisionphase_.tsv")
	fi
	if [[ -s "$output" ]]; then
		((existing += 1))
	fi
	is_output_current=0
	if (( refresh )) && is_current "$output" "$fingerprint_file" "${dependencies[@]}"; then
		((current += 1))
		is_output_current=1
	fi
	selected_current_flags+=("$is_output_current")
done

if (( ${#selected_ev_files[@]} == 0 )); then
	echo "no ${TASK} EV files matched the requested participant/run scope" >&2
	exit 1
fi

run_keys=()
while IFS= read -r key; do
	run_keys+=("$key")
done < <(printf '%s\n' "${selected_run_keys[@]}" | sort -u -t: -k1,1n -k2,2n)
for key in "${run_keys[@]}"; do
	sub=${key%%:*}
	run=${key##*:}
	data="${dataset_root}/derivatives/fmriprep/sub-${sub}/func/sub-${sub}_task-${TASK}_run-${run}_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
	confounds="${work_root}/confounds/sub-${sub}/sub-${sub}_task-${TASK}_run-${run}_desc-fslConfounds.tsv"
	if [[ ! -s "$data" ]]; then
		echo "missing preprocessed BOLD: $data" >&2
		((missing_inputs += 1))
	fi
	if [[ ! -s "$confounds" ]]; then
		echo "missing FSL confounds: $confounds" >&2
		((missing_inputs += 1))
	fi
	if [[ -s "$data" && -s "$confounds" ]] && command -v fslnvols >/dev/null 2>&1; then
		if ! nvolumes=$(fslnvols "$data"); then
			echo "could not read BOLD volume count: $data" >&2
			((missing_inputs += 1))
		else
			confound_rows=$(wc -l < "$confounds")
			if (( confound_rows != nvolumes )); then
				echo "confound/BOLD row mismatch for sub-${sub} task-${TASK} run-${run}: ${confound_rows} != ${nvolumes}" >&2
				((missing_inputs += 1))
			fi
			((row_count_checks += 1))
		fi
	fi
	if [[ "$TASK" == "trust" ]]; then
		decision="${ev_root}/sub-${sub}/SingleTrialEVs/task-trust/run$(printf '%02d' "$run")/trialmodel-decisionphase_.tsv"
		if [[ ! -s "$decision" ]]; then
			echo "missing Trust decision-phase EV: $decision" >&2
			((missing_inputs += 1))
		fi
	fi
done

selected=${#selected_ev_files[@]}
if (( force )); then
	to_run=$selected
elif (( refresh )); then
	to_run=$((selected - current))
else
	to_run=$((selected - existing))
fi
echo "Task: $TASK"
echo "Dataset root: $dataset_root"
echo "Work root: $work_root"
echo "Concurrent FEAT jobs: $jobs"
echo "Participant-runs: ${#run_keys[@]}"
if (( row_count_checks )); then
	echo "Confound/BOLD row counts checked: $row_count_checks"
else
	echo "Confound/BOLD row counts not checked (fslnvols unavailable)"
fi
if (( unavailable_run_count )); then
	skipped_run_count=$(printf '%s\n' "${unavailable_run_keys[@]}" | sort -u | wc -l | tr -d ' ')
	echo "Skipped participant-runs without preprocessed BOLD: $skipped_run_count"
fi
echo "Selected trial models: $selected"
echo "Completed trial images already present: $existing"
echo "Trial images current with code and inputs: $current"
echo "Trial models to execute: $to_run"
if (( missing_inputs )); then
	echo "Preflight failed with $missing_inputs missing inputs" >&2
	exit 1
fi
if (( dry_run )); then
	echo "Dry run complete; no FEAT jobs or packing commands were run"
	exit 0
fi

for command in feat fslnvols; do
	if ! command -v "$command" >/dev/null 2>&1; then
		echo "required FSL command not found: $command" >&2
		exit 1
	fi
done

pids=()
pid_count=0
failures=0
wait_batch() {
	local pid
	for pid in "${pids[@]}"; do
		wait "$pid" || ((failures += 1))
	done
	pids=()
	pid_count=0
}

scheduled=0
for index in "${!selected_ev_files[@]}"; do
	ev_file=${selected_ev_files[$index]}
	[[ "$ev_file" =~ /sub-([0-9]+)/SingleTrialEVs/task-${TASK}/run([0-9]+)/trialmodel-([0-9]+)_estimage-single\.tsv$ ]]
	sub=${BASH_REMATCH[1]}
	run=$((10#${BASH_REMATCH[2]}))
	trial=$((10#${BASH_REMATCH[3]}))
	trial_padded=$(printf '%02d' "$trial")
	output="${work_root}/sub-${sub}/LSS-images_task-${TASK}_model-01_type-act_run-$(printf '%02d' "$run")/zstat_trial-${trial_padded}.nii.gz"
	if (( refresh )); then
		if (( selected_current_flags[$index] )); then
			continue
		fi
	elif (( ! force )) && [[ -s "$output" ]]; then
		continue
	fi
	args=("$sub" "$run" "$trial" "$TASK")
	if (( force || refresh )); then
		args+=("--force")
	fi
	SRNDNA_DATASET_ROOT="$dataset_root" \
		SRNDNA_LSS_WORK_ROOT="$work_root" \
		bash "${scriptdir}/L1LSSstats.sh" "${args[@]}" &
	pids+=("$!")
	((pid_count += 1))
	((scheduled += 1))
	if (( pid_count >= jobs )); then
		wait_batch
	fi
done
if (( pid_count )); then
	wait_batch
fi
if (( failures )); then
	echo "$failures LSS jobs failed; packing was not attempted; inspect ${work_root}/logs" >&2
	exit 1
fi
echo "Completed $scheduled ${TASK} LSS models"

if (( pack )); then
	for key in "${run_keys[@]}"; do
		sub=${key%%:*}
		run=${key##*:}
		SRNDNA_DATASET_ROOT="$dataset_root" \
			SRNDNA_LSS_WORK_ROOT="$work_root" \
			bash "${scriptdir}/pack_L1LSSstats.sh" "$TASK" "$sub" "$run"
	done
fi
