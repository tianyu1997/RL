# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import Callable

import torch
from tensordict import TensorDict
from tensordict.tensordict import TensorDictBase, pad


def _stack_output(fun) -> Callable:
    def stacked_output_fun(*args, **kwargs):
        out = fun(*args, **kwargs)
        return tuple(torch.stack(_o, 0) for _o in out)

    return stacked_output_fun


def _stack_output_zip(fun) -> Callable:
    def stacked_output_fun(*args, **kwargs):
        out = fun(*args, **kwargs)
        return tuple(torch.stack(_o, 0) for _o in zip(*out))

    return stacked_output_fun


def split_trajectories(rollout_tensordict: TensorDictBase) -> TensorDictBase:
    """A util function for trajectory separation.

    Takes a tensordict with a key traj_ids that indicates the id of each trajectory.

    From there, builds a B x T x ... zero-padded tensordict with B batches on max duration T
    """
    # TODO: incorporate tensordict.split once it's implemented
    sep = ".-|-."
    rollout_tensordict = rollout_tensordict.flatten_keys(sep)
    traj_ids = rollout_tensordict.get("traj_ids")
    # ndim = len(rollout_tensordict.batch_size)
    splits = traj_ids.view(-1)
    splits = [(splits == i).sum().item() for i in splits.unique_consecutive()]
    # if all splits are identical then we can skip this function
    if len(set(splits)) == 1 and splits[0] == traj_ids.shape[-1]:
        rollout_tensordict.set(
            "mask",
            torch.ones(
                rollout_tensordict.shape,
                device=rollout_tensordict.device,
                dtype=torch.bool,
            ),
        )
        if rollout_tensordict.ndimension() == 1:
            rollout_tensordict = rollout_tensordict.unsqueeze(0).to_tensordict()
        return rollout_tensordict.unflatten_keys(sep)
    # out_splits = {
    #     key: _d.contiguous().view(-1, *_d.shape[ndim:]).split(splits, 0)
    #     for key, _d in rollout_tensordict.items()
    # #    if key not in ("step_count", "traj_ids")
    # }
    out_splits = rollout_tensordict.view(-1).split(splits, 0)

    # select complete rollouts
    # valid_ids = list(range(len(out_splits)))
    # out_splits = {key: [_out[i] for i in valid_ids] for key, _out in out_splits.items()}
    for out_split in out_splits:
        out_split.set("mask", torch.ones(out_split.shape, dtype=torch.bool, device=out_split._get_meta("done").device))
    # mask = [
    #     torch.ones_like(_out[..., 0], dtype=torch.bool, device=_out.device) for _out in out_splits["done"]
    # ]
    # out_splits["mask"] = mask
    # out_dict = {
    #     key: torch.nn.utils.rnn.pad_sequence(_o, batch_first=True)
    #     for key, _o in out_splits.items()
    # }
    # td = TensorDict(
    #     source=out_dict,
    #     device=rollout_tensordict.device,
    #     batch_size=out_dict["mask"].shape,
    #     _run_checks=False,
    # )
    MAX = max(*[out_split.shape[0] for out_split in out_splits])
    td = torch.stack([pad(out_split, [0, MAX - out_split.shape[0]]) for out_split in out_splits], 0).contiguous()
    td = td.unflatten_keys(sep)
    # if (out_dict.get("done").sum(1) > 1).any():
    #     raise RuntimeError("Got more than one done per trajectory")
    return td
