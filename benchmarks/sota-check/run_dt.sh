#!/bin/bash

#SBATCH --job-name=dt
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --gres=gpu:1
#SBATCH --output=slurm_logs/dt_offline_output_%j.txt
#SBATCH --error=slurm_errors/dt_offline_error_%j.txt

current_commit=$(git rev-parse HEAD)
project_name="torchrl-example-check-$current_commit"
group_name="$dt_offline"
python ../../examples/decision_transformer/dt.py \
  logger.backend=wandb \
  logger.project_name="$project_name" \
  logger.group_name="$group_name"

# Capture the exit status of the Python command
exit_status=$?
# Write the exit status to a file
if [ $exit_status -eq 0 ]; then
  echo "$group_name_$SLURM_JOB_ID=success" > report.log
else
  echo "$group_name_$SLURM_JOB_ID=error" > report.log
fi
