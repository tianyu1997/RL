#!/usr/bin/env bash

set -euxo pipefail
set -v

# ==================================================================================== #
# ================================ Setup env ========================================= #


if [[ $OSTYPE != 'darwin'* ]]; then
  apt-get update && apt-get upgrade -y
  apt-get install -y vim git wget

  apt-get install -y libglfw3 libgl1-mesa-glx libosmesa6 libglew-dev
  apt-get install -y libglvnd0 libgl1 libglx0 libegl1 libgles2

  if [ "${CU_VERSION:-}" == cpu ] ; then
    # solves version `GLIBCXX_3.4.29' not found for tensorboard
#    apt-get install -y gcc-4.9
    apt-get upgrade -y libstdc++6
    apt-get dist-upgrade -y
  else
    apt-get install -y g++ gcc
  fi

fi

this_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
if [[ $OSTYPE != 'darwin'* ]]; then
  # from cudagl docker image
  cp $this_dir/10_nvidia.json /usr/share/glvnd/egl_vendor.d/10_nvidia.json
fi

# Avoid error: "fatal: unsafe repository"
git config --global --add safe.directory '*'
root_dir="$(git rev-parse --show-toplevel)"
conda_dir="${root_dir}/conda"
env_dir="${root_dir}/env"
lib_dir="${env_dir}/lib"

cd "${root_dir}"

case "$(uname -s)" in
    Darwin*) os=MacOSX;;
    *) os=Linux
esac

# 1. Install conda at ./conda
if [ ! -d "${conda_dir}" ]; then
    printf "* Installing conda\n"
    wget -O miniconda.sh "http://repo.continuum.io/miniconda/Miniconda3-latest-${os}-x86_64.sh"
    bash ./miniconda.sh -b -f -p "${conda_dir}"
fi
eval "$(${conda_dir}/bin/conda shell.bash hook)"

# 2. Create test environment at ./env
printf "python: ${PYTHON_VERSION}\n"
if [ ! -d "${env_dir}" ]; then
    printf "* Creating a test environment\n"
    conda create --prefix "${env_dir}" -y python="$PYTHON_VERSION"
fi
conda activate "${env_dir}"

# 4. Install Conda dependencies
printf "* Installing dependencies (except PyTorch)\n"
echo "  - python=${PYTHON_VERSION}" >> "${this_dir}/environment.yml"
cat "${this_dir}/environment.yml"

if [ "${CU_VERSION:-}" == cpu ] ; then
  export MUJOCO_GL=glfw
else
  export MUJOCO_GL=egl
fi

# legacy from bash scripts: remove?
conda env config vars set MUJOCO_GL=$MUJOCO_GL PYOPENGL_PLATFORM=$MUJOCO_GL DISPLAY=:0 SDL_VIDEODRIVER=dummy

python3 -m pip install --upgrade pip

#if [[ $OSTYPE == 'darwin'* ]]; then
#  echo "Insalling mujoco"
#  python3 -m pip uninstall cython -y
#  python3 -m pip install "cython<3.0.0"
##  python3 -m pip install mujoco
#  # pip fails to install mujoco
#  conda install -c conda-forge mujoco-python -y
#  # https://stackoverflow.com/questions/53014306/error-15-initializing-libiomp5-dylib-but-found-libiomp5-dylib-already-initial
#  conda env config vars set KMP_DUPLICATE_LIB_OK='True'
#fi
pip3 install virtualenv

conda env update --file "${this_dir}/environment.yml" --prune

# Reset conda env variables
conda deactivate
conda activate "${env_dir}"

echo "installing gymnasium"
python3 -m pip install "gymnasium[atari,ale-py,accept-rom-license]"
python3 -m pip install mo-gymnasium[mujoco]  # requires here bc needs mujoco-py

# sanity check: remove?
python3 -c """
import dm_control
from dm_control import composer
from tensorboard import *
from google.protobuf import descriptor as _descriptor
"""

# ============================================================================================ #
# ================================ PyTorch & TorchRL ========================================= #

unset PYTORCH_VERSION

if [ "${CU_VERSION:-}" == cpu ] ; then
    version="cpu"
    echo "Using cpu build"
else
    if [[ ${#CU_VERSION} -eq 4 ]]; then
        CUDA_VERSION="${CU_VERSION:2:1}.${CU_VERSION:3:1}"
    elif [[ ${#CU_VERSION} -eq 5 ]]; then
        CUDA_VERSION="${CU_VERSION:2:2}.${CU_VERSION:4:1}"
    fi
    echo "Using CUDA $CUDA_VERSION as determined by CU_VERSION ($CU_VERSION)"
    version="$(python3 -c "print('.'.join(\"${CUDA_VERSION}\".split('.')[:2]))")"
fi

# submodules
git submodule sync && git submodule update --init --recursive

printf "Installing PyTorch with %s\n" "${CU_VERSION}"
if [ "${CU_VERSION:-}" == cpu ] ; then
    python3 -m pip install --pre torch torchvision --extra-index-url https://download.pytorch.org/whl/nightly/cpu
else
    python3 -m pip install --pre torch torchvision --extra-index-url https://download.pytorch.org/whl/nightly/$CU_VERSION
fi

## smoke test
#python3 -c "import functorch"

# install snapshot
python3 -m pip install git+https://github.com/pytorch/torchsnapshot

# install tensordict
python3 -m pip install git+https://github.com/pytorch-labs/tensordict.git

printf "* Installing torchrl\n"
python3 setup.py develop -v


if [ "${CU_VERSION:-}" != cpu ] ; then
  printf "* Installing VC1\n"
  python3 -c """
from torchrl.envs.transforms.vc1 import VC1Transform
VC1Transform.install_vc_models(auto_exit=True)
"""

  python3 -c """
import vc_models
from vc_models.models.vit import model_utils
print(model_utils)
"""
fi

# ==================================================================================== #
# ================================ Run tests ========================================= #


export PYTORCH_TEST_WITH_SLOW='1'
python3 -m torch.utils.collect_env
# Avoid error: "fatal: unsafe repository"

# solves ImportError: /lib64/libstdc++.so.6: version `GLIBCXX_3.4.21' not found
#export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$lib_dir
export MKL_THREADING_LAYER=GNU
export CKPT_BACKEND=torch


pytest test/smoke_test.py -v --durations 200
pytest test/smoke_test_deps.py -v --durations 200 -k 'test_gym or test_dm_control_pixels or test_dm_control or test_tb'
if [ "${CU_VERSION:-}" != cpu ] ; then
  python3 .circleci/unittest/helpers/coverage_run_parallel.py -m pytest test \
    --instafail --durations 200 --ignore test/test_rlhf.py
else
  python3 .circleci/unittest/helpers/coverage_run_parallel.py -m pytest test \
    --instafail --durations 200 --ignore test/test_rlhf.py --ignore test/test_distributed.py
fi

coverage combine
coverage xml -i

# ==================================================================================== #
# ================================ Post-proc ========================================= #

bash ${this_dir}/post_process.sh
