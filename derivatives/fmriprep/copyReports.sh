#!/bin/bash

for i in `ls -d sub-1* | grep -v '\.html$' | column`; do
	echo $i
	rclone copy --retries 5 ${i}.html dvs-onedrive:srndna-fmriprep/ &
	rclone copy --transfers 20 --retries 5 --create-empty-src-dirs ${i}/figures dvs-onedrive:srndna-fmriprep/${i}/figures/ &
done
