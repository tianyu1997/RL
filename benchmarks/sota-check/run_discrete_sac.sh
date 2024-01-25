#!/bin/bash

#SBATCH --job-name=discrete_sac
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --gres=gpu:1
#SBATCH --output=slurm_logs/discrete_sac_output_%j.txt
#SBATCH --errors=slurm_errors/discrete_sac_error_%j.txt

current_commit=$(git rev-parse HEAD)
project_name="torchrl-example-check-$current_commit"
group_name="discrete_sac"
python ../../examples/discrete_sac/discrete_sac.py \
  logger.backend=wandb \
  logger.project_name="$project_name" \
  logger.group_name="$group_name"

# Capture the exit status of the Python command
exit_status=$?
# Write the exit status to a file
if [ $exit_status -eq 0 ]; then
  echo "$group_name=success" > report.log
else
  echo "$group_name=error" > report.log
fi
