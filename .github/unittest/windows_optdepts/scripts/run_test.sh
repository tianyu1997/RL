#!/usr/bin/env bash

set -e

this_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

eval "$(${conda_dir}/Scripts/conda.exe 'shell.bash' 'hook')"
conda activate rlenv

source "$this_dir/set_cuda_envs.sh"

python -m torch.utils.collect_env
pytest --junitxml=test-results/junit.xml -v --durations 200  --ignore test/test_distributed.py --ignore test/test_rlhf.py
