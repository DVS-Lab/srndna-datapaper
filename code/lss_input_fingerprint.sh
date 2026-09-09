#!/usr/bin/env bash

# Emit a portable content fingerprint for the ordered list of small LSS inputs.
set -euo pipefail

if (( $# == 0 )); then
	echo "usage: $0 FILE [...]" >&2
	exit 2
fi

for input in "$@"; do
	if [[ ! -s "$input" ]]; then
		echo "cannot fingerprint missing or empty input: $input" >&2
		exit 1
	fi
done

for input in "$@"; do
	cksum < "$input"
done | cksum | awk '{print $1 ":" $2}'
