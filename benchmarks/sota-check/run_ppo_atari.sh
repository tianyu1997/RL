#!/bin/bash

#SBATCH --job-name=ppo_atari
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --gres=gpu:1
#SBATCH --output=slurm_logs/ppo_atari_output_%j.txt
#SBATCH --error=slurm_errors/ppo_atari_error_%j.txt

current_commit=$(git rev-parse HEAD)
project_name="torchrl-example-check-$current_commit"
group_name="ppo_atari"
python ../../examples/ppo/ppo_atari.py \
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
