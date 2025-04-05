#!/usr/bin/env bash

# ensure paths are correct irrespective from where user runs the script
scriptdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
maindir="$(dirname "$scriptdir")"


TASK=ultimatum
sm=6
nruns=2

for mask in roi-VS roi-VMPFC roi-dACC roi-aINS; do


	# analyses we are doing; these define input/output paths in the L1stats.sh script
	#for ppi in 0 lfpn rfpn ecn dmn rightVS leftVS; do # putting 0 first will indicate "activation"
	for ppi in 0; do # putting 0 first will indicate "activation"

		# loops through the subject/run list
		for sub in 104 105 106 107 108 109 110 111 112 113 115 116 117 118 120 121 122 124 125 126 127 128 129 130 131 132 133 134 135 136 137 138 140 141 142 143 144 145 147 149 150 151 152 153 154 155 156 157 158 159; do
			echo "running: sub-${sub} on conn-${ppi} at `date`..."


			for run in `seq ${nruns}`; do

				# common directory for zstat outputs
				MAINOUTPUT=${maindir}/derivatives/fsl/sub-${sub}
				zoutdir=${MAINOUTPUT}/LSS-images_task-${TASK}_model-01_type-act_run-0${run}
				cd $zoutdir
				rm -rf sub-${sub}*.nii.gz
				fslmerge -t sub-${sub}_run-0${run}_type-act_merged_z zstat_trial-*.nii.gz

				ntrials=`fslnvols sub-${sub}_run-0${run}_type-act_merged_z`
				if [ $ntrials -ne 72 ]; then
					echo "missing data sub-${sub}_run-0${run}: found $ntrials" >> ${scriptdir}/missingData.log
				fi

				# output for extractions
				out_meants=${maindir}/derivatives/singletrial/sub-${sub}
				mkdir -p ${out_meants}

				maskfile=${maindir}/masks/${mask}.nii.gz
				fslmeants -i ${zoutdir}/sub-${sub}_run-0${run}_type-act_merged_z.nii.gz \
					-o ${out_meants}/sub-${sub}_run-0${run}_mask-${mask}.txt \
					-m ${maskfile}

			done
		done
done
done
