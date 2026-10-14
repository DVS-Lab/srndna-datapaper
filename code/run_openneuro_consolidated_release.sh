#!/usr/bin/env bash
# Run in tmux on Linux1. No modifications to the downloaded data or old recovery.
CODE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || exit 1
DATASET_ROOT=${DATASET_ROOT:-/ZPOOL/data/datasets/ds003745-work}
RELEASE_ROOT=${RELEASE_ROOT:-/ZPOOL/data/scratch/srndna-datapaper-openneuro-2.2.0}
WORK_ROOT="$RELEASE_ROOT/consolidated-v1"
REPORT_ROOT="$CODE_ROOT/results/openneuro_release/consolidated-v1"
HELPER_DIR="$RELEASE_ROOT/openneuro-helper-bin"

for TOOL in python3 git git-annex deno openneuro-deno; do
    command -v "$TOOL" >/dev/null || { echo "STOP: missing $TOOL"; exit 1; }
done
mkdir -p "$HELPER_DIR" "$REPORT_ROOT" || exit 1
install -m 0755 "$CODE_ROOT/code/git-annex-remote-openneuro" \
    "$HELPER_DIR/git-annex-remote-openneuro" || exit 1
export PATH="$HELPER_DIR:$PATH"

# Every attempt gets a separate public operational log. No DICOM extraction or
# credential contents are printed or included in this report directory.
RUN_LOG=$(mktemp "$REPORT_ROOT/run-XXXXXXXX.log") || exit 1
run_stage() {
    python3 -u "$CODE_ROOT/code/finalize_openneuro_release.py" "$1" \
        --dataset-root "$DATASET_ROOT" --work-root "$WORK_ROOT" \
        --report-dir "$REPORT_ROOT" 2>&1 | tee -a "$RUN_LOG"
    local statuses=("${PIPESTATUS[@]}")
    if test "${statuses[0]}" -ne 0; then return "${statuses[0]}"; fi
    return "${statuses[1]}"
}

for STAGE in prepare build upload; do
    printf '\nSTAGE: %s\n' "$STAGE" | tee -a "$RUN_LOG"
    run_stage "$STAGE"
    STATUS=$?
    if test "$STATUS" -ne 0; then
        printf 'STOP: %s exited %s. Keep all files; send this log for review.\n' \
            "$STAGE" "$STATUS" | tee -a "$RUN_LOG"
        exit "$STATUS"
    fi
done
echo "PASS: draft updated. Review OpenNeuro validation before publishing snapshot 2.2.0." | tee -a "$RUN_LOG"
