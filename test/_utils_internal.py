# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os
import time
from functools import wraps

# Get relative file path
# this returns relative path from current file.
import pytest
import torch.cuda
from torchrl._utils import seed_generator, implement_for
from torchrl.envs import EnvBase


# Specified for test_utils.py
__version__ = "0.3"


def get_relative_path(curr_file, *path_components):
    return os.path.join(os.path.dirname(curr_file), *path_components)


def get_available_devices():
    devices = [torch.device("cpu")]
    n_cuda = torch.cuda.device_count()
    if n_cuda > 0:
        for i in range(n_cuda):
            devices += [torch.device(f"cuda:{i}")]
    return devices


def generate_seeds(seed, repeat):
    seeds = [seed]
    for _ in range(repeat - 1):
        seed = seed_generator(seed)
        seeds.append(seed)
    return seeds


def _test_fake_tensordict(env: EnvBase):
    fake_tensordict = env.fake_tensordict().flatten_keys(".")
    real_tensordict = env.rollout(3).flatten_keys(".")

    keys1 = set(fake_tensordict.keys())
    keys2 = set(real_tensordict.keys())
    assert keys1 == keys2
    fake_tensordict = fake_tensordict.expand(3).to_tensordict()
    fake_tensordict.zero_()
    real_tensordict.zero_()
    assert (fake_tensordict == real_tensordict).all()
    for key in keys2:
        assert fake_tensordict[key].shape == real_tensordict[key].shape


# Decorator to retry upon certain Exceptions.
def retry(ExceptionToCheck, tries=3, delay=3, skip_after_retries=False):
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = "%s, Retrying in %d seconds..." % (str(e), mdelay)
                    print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
            try:
                return f(*args, **kwargs)
            except ExceptionToCheck as e:
                if skip_after_retries:
                    raise pytest.skip(
                        f"Skipping after {tries} consecutive {str(e)}"
                    ) from e
                else:
                    raise e

        return f_retry  # true decorator

    return deco_retry

def PENDULUM_VERSIONED():
    @implement_for("gym", None, "0.20")
    def _pendulum_version():
        return "Pendulum-v0"

    @implement_for("gym", "0.21", None)
    def _pendulum_version():
        return "Pendulum-v1"

    return _pendulum_version()

def PONG_VERSIONED():
    @implement_for("gym", None, "0.20")
    def _pong_versioned():
        return "Pong-v4"

    @implement_for("gym", "0.21", None)
    def _pong_versioned():
        return "ALE/Pong-v5"

    return _pong_versioned()
