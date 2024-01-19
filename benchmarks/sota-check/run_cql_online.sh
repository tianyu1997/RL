#!/bin/bash

#SBATCH --job-name=cql_online
#SBATCH --partition=test
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --gres=gpu:1
#SBATCH --output=cql_online_output_%j.txt
#SBATCH --error=cql_online_error_%j.txt

python ../../examples/cql/cql_online.py \
  collector.total_frames=256 \
  optim.batch_size=10 \
  collector.frames_per_batch=16 \
  collector.env_per_collector=1 \
  optim.device=cuda:0 \
  collector.device=cuda:0 \
  logger.backend=wandb \
  logger.project_name="sota-check"