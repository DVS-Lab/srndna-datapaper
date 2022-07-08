#!/bin/bash

FILES="/data/projects/srndna-data/bids/sub*/func/sub-*_task-ultimatum_run*.tsv"

for sub in $FILES
do
   #echo "This is the file: $sub"
   cp "$sub" /data/projects/srndna-data/bids/behavioraldata
done 
