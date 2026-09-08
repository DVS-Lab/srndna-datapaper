#!/usr/bin/env bash

# Run LSS models for every generated trial EV belonging to one task.
set -euo pipefail

scriptdir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
basedir="$(dirname "$scriptdir")"

TASK=${1:-ultimatum}
force=${2:-}
NCORES=${NCORES:-30}
SUBJECTS=${SUBJECTS:-}

case "$TASK" in
	ultimatum|trust|sharedreward) ;;
	*) echo "usage: $0 {ultimatum|trust|sharedreward} [--force]" >&2; exit 2 ;;
esac
if [[ -n "$force" && "$force" != "--force" ]]; then
	echo "usage: $0 {ultimatum|trust|sharedreward} [--force]" >&2
	exit 2
fi
if ! [[ "$NCORES" =~ ^[1-9][0-9]*$ ]]; then
	echo "NCORES must be a positive integer" >&2
	exit 2
fi

ev_root="${basedir}/derivatives/fsl/EVfiles"
mapfile -t ev_files < <(
	find "$ev_root" -type f \
		-path "*/SingleTrialEVs/task-${TASK}/run*/trialmodel-*_estimage-single.tsv" \
		| sort
)
if (( ${#ev_files[@]} == 0 )); then
	echo "no ${TASK} single-trial EV files found under ${ev_root}" >&2
	exit 1
fi

pids=()
scheduled=0
wait_batch() {
	local pid
	local failed=0
	for pid in "${pids[@]}"; do
		wait "$pid" || failed=1
	done
	pids=()
	if (( failed )); then
		echo "one or more LSS jobs failed; inspect ${basedir}/logs" >&2
		return 1
	fi
}

for ev_file in "${ev_files[@]}"; do
	if [[ "$ev_file" =~ /sub-([0-9]+)/SingleTrialEVs/task-${TASK}/run([0-9]+)/trialmodel-([0-9]+)_estimage-single\.tsv$ ]]; then
		sub=${BASH_REMATCH[1]}
		run=$((10#${BASH_REMATCH[2]}))
		trial=$((10#${BASH_REMATCH[3]}))
	else
		echo "could not parse EV path: $ev_file" >&2
		exit 1
	fi

	if [[ -n "$SUBJECTS" && " $SUBJECTS " != *" $sub "* ]]; then
		continue
	fi

	args=("$sub" "$run" "$trial" "$TASK")
	if [[ "$force" == "--force" ]]; then
		args+=("--force")
	fi
	bash "${scriptdir}/L1LSSstats.sh" "${args[@]}" &
	pids+=("$!")
	((scheduled += 1))
	if (( ${#pids[@]} >= NCORES )); then
		wait_batch
	fi
done

if (( ${#pids[@]} )); then
	wait_batch
fi
echo "Completed ${scheduled} ${TASK} LSS models"
