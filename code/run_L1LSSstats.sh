#!/bin/bash

# ensure paths are correct irrespective from where user runs the script
scriptdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
basedir="$(dirname "$scriptdir")"

# create log file to record what we did and when
logs=$basedir/logs
logfile=${logs}/runL1LSS_date-`date +"%FT%H%M"`.log

# list subject numbers and run numbers to run
for sub in 104 105 106 107 108 109 110 111 112 113 115 116 117 118 120 121 122 124 125 126 127 128 129 130 131 132 133 134 135 136 137 138 140 141 142 143 144 145 147 149 150 151 152 153 154 155 156 157 158 159; do
	  nruns=5

	  for run in `seq $nruns`; do
			#for trial in `seq 72`; do
			for trial in `seq 36`; do #36 maximum choice / outcome pairs for trust task
			  	# Manages the number of jobs and cores
			  	SCRIPTNAME=${basedir}/code/L1LSSstats.sh
			  	NCORES=20
			  	while [ $(ps -ef | grep -v grep | grep $SCRIPTNAME | wc -l) -ge $NCORES ]; do
			    		sleep 1s
			  	done
			  	bash $SCRIPTNAME $sub $run $trial $logfile &
			done
	  done

	done
