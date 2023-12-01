# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
from __future__ import annotations

import json
import os.path
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import torch
import tqdm

from tensordict import MemoryMappedTensor, PersistentTensorDict, TensorDict
from torchrl._utils import KeyDependentDefaultDict
from torchrl.data.datasets.utils import _get_root_dir
from torchrl.data.replay_buffers.replay_buffers import TensorDictReplayBuffer
from torchrl.data.replay_buffers.samplers import Sampler
from torchrl.data.replay_buffers.storages import TensorStorage
from torchrl.data.replay_buffers.writers import Writer
from torchrl.data.tensor_specs import (
    BoundedTensorSpec,
    CompositeSpec,
    DiscreteTensorSpec,
    UnboundedContinuousTensorSpec,
)

_NAME_MATCH = KeyDependentDefaultDict(lambda key: key)
_NAME_MATCH["observations"] = "observation"
_NAME_MATCH["rewards"] = "reward"
_NAME_MATCH["truncations"] = "truncated"
_NAME_MATCH["terminations"] = "terminated"
_NAME_MATCH["actions"] = "action"
_NAME_MATCH["infos"] = "info"


class MinariExperienceReplay(TensorDictReplayBuffer):
    """Minari Experience replay dataset.

    Args:
        dataset_id (str):
        batch_size (int):

    Keyword Args:
        root (Path or str, optional): The Minari dataset root directory.
            The actual dataset memory-mapped files will be saved under
            `<root>/<dataset_id>`. If none is provided, it defaults to
            ``~/.cache/torchrl/minari`.
        download (bool or str, optional): Whether the dataset should be downloaded if
            not found. Defaults to ``True``. Download can also be passed as "force",
            in which case the downloaded data will be overwritten.
        sampler (Sampler, optional): the sampler to be used. If none is provided
            a default RandomSampler() will be used.
        writer (Writer, optional): the writer to be used. If none is provided
            a default RoundRobinWriter() will be used.
        collate_fn (callable, optional): merges a list of samples to form a
            mini-batch of Tensor(s)/outputs.  Used when using batched
            loading from a map-style dataset.
        pin_memory (bool): whether pin_memory() should be called on the rb
            samples.
        prefetch (int, optional): number of next batches to be prefetched
            using multithreading.
        transform (Transform, optional): Transform to be executed when sample() is called.
            To chain transforms use the :obj:`Compose` class.
        split_trajs (bool, optional): if ``True``, the trajectories will be split
            along the first dimension and padded to have a matching shape.
            To split the trajectories, the ``"done"`` signal will be used, which
            is recovered via ``done = truncated | terminated``. In other words,
            it is assumed that any ``truncated`` or ``terminated`` signal is
            equivalent to the end of a trajectory. For some datasets from
            ``D4RL``, this may not be true. It is up to the user to make
            accurate choices regarding this usage of ``split_trajs``.
            Defaults to ``False``.

    Examples:
        >>> from torchrl.data.datasets.minari_data import MinariExperienceReplay
        >>> data = MinariExperienceReplay("door-human-v1", batch_size=32, download="force")
        >>> for sample in data:
        ...     print(sample)
        ...     break
        TensorDict(
            fields={
                action: Tensor(shape=torch.Size([32, 28]), device=cpu, dtype=torch.float32, is_shared=False),
                index: Tensor(shape=torch.Size([32]), device=cpu, dtype=torch.int64, is_shared=False),
                info: TensorDict(
                    fields={
                        success: Tensor(shape=torch.Size([32]), device=cpu, dtype=torch.bool, is_shared=False)},
                    batch_size=torch.Size([32]),
                    device=None,
                    is_shared=False),
                next: TensorDict(
                    fields={
                        observation: Tensor(shape=torch.Size([32, 39]), device=cpu, dtype=torch.float64, is_shared=False),
                        reward: Tensor(shape=torch.Size([32, 1]), device=cpu, dtype=torch.float64, is_shared=False),
                        state: TensorDict(
                            fields={
                                door_body_pos: Tensor(shape=torch.Size([32, 3]), device=cpu, dtype=torch.float64, is_shared=False),
                                qpos: Tensor(shape=torch.Size([32, 30]), device=cpu, dtype=torch.float64, is_shared=False),
                                qvel: Tensor(shape=torch.Size([32, 30]), device=cpu, dtype=torch.float64, is_shared=False)},
                            batch_size=torch.Size([32]),
                            device=None,
                            is_shared=False),
                        terminated: Tensor(shape=torch.Size([32, 1]), device=cpu, dtype=torch.bool, is_shared=False),
                        truncated: Tensor(shape=torch.Size([32, 1]), device=cpu, dtype=torch.bool, is_shared=False)},
                    batch_size=torch.Size([32]),
                    device=None,
                    is_shared=False),
                observation: Tensor(shape=torch.Size([32, 39]), device=cpu, dtype=torch.float64, is_shared=False),
                state: TensorDict(
                    fields={
                        door_body_pos: Tensor(shape=torch.Size([32, 3]), device=cpu, dtype=torch.float64, is_shared=False),
                        qpos: Tensor(shape=torch.Size([32, 30]), device=cpu, dtype=torch.float64, is_shared=False),
                        qvel: Tensor(shape=torch.Size([32, 30]), device=cpu, dtype=torch.float64, is_shared=False)},
                    batch_size=torch.Size([32]),
                    device=None,
                    is_shared=False)},
            batch_size=torch.Size([32]),
            device=None,
            is_shared=False)

    """

    def __init__(
        self,
        dataset_id,
        batch_size: int,
        *,
        root: str | Path | None = None,
        download: bool = True,
        sampler: Sampler | None = None,
        writer: Writer | None = None,
        collate_fn: Callable | None = None,
        pin_memory: bool = False,
        prefetch: int | None = None,
        transform: "torchrl.envs.Transform" | None = None,  # noqa-F821
        split_trajs: bool = False,
        **env_kwargs,
    ):
        self.dataset_id = dataset_id
        if root is None:
            root = _get_root_dir("minari")
            os.makedirs(root, exist_ok=True)
        self.root = root
        self.split_trajs = split_trajs
        self.download = download
        if self.download == "force" or (self.download and not self._is_downloaded()):
            if self.download == "force":
                try:
                    shutil.rmtree(self.data_path_root)
                    if self.data_path != self.data_path_root:
                        shutil.rmtree(self.data_path)
                except FileNotFoundError:
                    pass
            storage = self._download_and_preproc()
        elif self.split_trajs and not os.path.exists(self.data_path):
            storage = self._make_split()
        else:
            storage = self._load()
        storage = TensorStorage(storage)
        super().__init__(
            storage=storage,
            sampler=sampler,
            writer=writer,
            collate_fn=collate_fn,
            pin_memory=pin_memory,
            prefetch=prefetch,
            batch_size=batch_size,
        )

    def available_datasets(self):
        import minari

        return minari.list_remote_datasets().keys()

    def _is_downloaded(self):
        return os.path.exists(self.data_path)

    @property
    def data_path(self):
        if self.split_trajs:
            return Path(self.root) / (self.dataset_id + "_split")
        return self.data_path_root

    @property
    def data_path_root(self):
        return Path(self.root) / self.dataset_id

    @property
    def metadata_path(self):
        return Path(self.root) / self.dataset_id / "env_metadata.json"

    def _download_and_preproc(self):
        import minari

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["MINARI_DATASETS_PATH"] = tmpdir
            minari.download_dataset(dataset_id=self.dataset_id)
            parent_dir = Path(tmpdir) / self.dataset_id / "data"

            td_data = TensorDict({}, [])
            total_steps = 0
            print("first read through data to create data structure...")
            h5_data = PersistentTensorDict.from_h5(parent_dir / "main_data.hdf5")
            # Get the total number of steps for the dataset
            total_steps += sum(
                h5_data[episode, "actions"].shape[0]
                for episode in h5_data.keys()
            )
            # populate the tensordict
            episode_dict = {}
            for episode_key, episode in h5_data.items():
                episode_num = int(episode_key[len("episode_"):])
                episode_dict[episode_num] = episode_key
                for key, val in episode.items():
                    match = _NAME_MATCH[key]
                    if key in ("observations", "state", "infos"):
                        if not val.shape:
                            # Data is ambiguous, skipping
                            continue
                            # unique_shapes = defaultdict([])
                            # for subkey, subval in val.items():
                            #     unique_shapes[subval.shape[0]].append(subkey)
                            # if not len(unique_shapes) == 2:
                            #     raise RuntimeError("Unique shapes in a sub-tensordict can only be of length 2.")
                            # val_td = val.to_tensordict()
                            # min_shape = min(*unique_shapes) # can only be found at root
                            # max_shape = min_shape + 1
                            # val_td = val_td.select(*unique_shapes[min_shape])
                            # print("key - val", key, val)
                            # print("episode", episode)
                        td_data.set(("next", match), torch.zeros_like(val)[0])
                        td_data.set(match, torch.zeros_like(val)[0])
                    if key not in ("terminations", "truncations", "rewards"):
                        td_data.set(match, torch.zeros_like(val)[0])
                    else:
                        td_data.set(
                            ("next", match),
                            torch.zeros_like(val)[0].unsqueeze(-1),
                        )
                break

            # give it the proper size
            td_data = td_data.expand(total_steps)
            # save to designated location
            print(f"creating tensordict data in {self.data_path_root}: ", end="\t")
            td_data = td_data.memmap_like(self.data_path_root)
            print(td_data)

            print("Reading data")
            index = 0
            with tqdm.tqdm(total=total_steps) as pbar:
                # iterate over episodes and populate the tensordict
                for episode_num in sorted(episode_dict):
                    episode_key = episode_dict[episode_num]
                    episode = h5_data.get(episode_key)
                    for key, val in episode.items():
                        match = _NAME_MATCH[key]
                        if key in (
                            "observations",
                            "state",
                            "infos",
                        ):
                            if not val.shape:
                                # Data is ambiguous, skipping
                                continue
                            steps = val.shape[0] - 1
                            td_data["next", match][index : (index + steps)] = val[
                                1:
                            ]
                            td_data[match][index : (index + steps)] = val[:-1]
                        elif key not in ("terminations", "truncations", "rewards"):
                            steps = val.shape[0]
                            td_data[match][index : (index + val.shape[0])] = val
                        else:
                            steps = val.shape[0]
                            td_data[("next", match)][
                                index : (index + val.shape[0])
                            ] = val.unsqueeze(-1)
                    pbar.update(steps)
                    pbar.set_description(f"index={index} - episode num {episode_num}")
                    index += steps
            h5_data.close()
            # Add a "done" entry
            with td_data.unlock_():
                td_data["next", "done"] = MemoryMappedTensor.from_tensor(
                    (td_data["next", "terminated"] | td_data["next", "truncated"])
                )
                if self.split_trajs:
                    from torchrl.objectives.utils import split_trajectories

                    td_data = split_trajectories(td_data).memmap_(self.data_path)
            with open(self.metadata_path, "w") as metadata_file:
                dataset = minari.load_dataset(self.dataset_id)
                self.metadata = asdict(dataset.spec)
                self.metadata["observation_space"] = _spec_to_dict(
                    self.metadata["observation_space"]
                )
                self.metadata["action_space"] = _spec_to_dict(
                    self.metadata["action_space"]
                )
                print("self.metadata", self.metadata)
                json.dump(self.metadata, metadata_file)
            self._load_and_proc_metadata()
            return td_data

    def _make_split(self):
        from torchrl.objectives.utils import split_trajectories

        self._load_and_proc_metadata()
        td_data = TensorDict.load_memmap(self.data_path_root)
        td_data = split_trajectories(td_data).memmap_(self.data_path)
        return td_data

    def _load(self):
        self._load_and_proc_metadata()
        return TensorDict.load_memmap(self.data_path)

    def _load_and_proc_metadata(self):
        with open(self.metadata_path, "r") as file:
            self.metadata = json.load(file)
        self.metadata["observation_space"] = _proc_spec(
            self.metadata["observation_space"]
        )
        self.metadata["action_space"] = _proc_spec(self.metadata["action_space"])
        print("Loaded metadata", self.metadata)


def _proc_spec(spec):
    if spec is None:
        return
    if spec["type"] == "Dict":
        return CompositeSpec(
            {key: _proc_spec(subspec) for key, subspec in spec["subspaces"].items()}
        )
    elif spec["type"] == "Box":
        if all(item == -float("inf") for item in spec["low"]) and all(
            item == float("inf") for item in spec["high"]
        ):
            return UnboundedContinuousTensorSpec(
                spec["shape"], dtype=_DTYPE_DIR[spec["dtype"]]
            )
        return BoundedTensorSpec(
            shape=spec["shape"],
            low=torch.tensor(spec["low"]),
            high=torch.tensor(spec["high"]),
            dtype=_DTYPE_DIR[spec["dtype"]],
        )
    elif spec["type"] == "Discrete":
        return DiscreteTensorSpec(
            spec["n"], shape=spec["shape"], dtype=_DTYPE_DIR[spec["dtype"]]
        )
    else:
        raise NotImplementedError(f"{type(spec)}")


def _spec_to_dict(spec):
    from torchrl.envs.libs.gym import gym_backend

    if isinstance(spec, gym_backend("spaces").Dict):
        return {
            "type": "Dict",
            "subspaces": {key: _spec_to_dict(val) for key, val in spec.items()},
        }
    if isinstance(spec, gym_backend("spaces").Box):
        return {
            "type": "Box",
            "low": spec.low.tolist(),
            "high": spec.high.tolist(),
            "dtype": str(spec.dtype),
            "shape": tuple(spec.shape),
        }
    if isinstance(spec, gym_backend("spaces").Discrete):
        return {
            "type": "Discrete",
            "dtype": str(spec.dtype),
            "n": int(spec.n),
            "shape": tuple(spec.shape),
        }
    if isinstance(spec, gym_backend("spaces").Text):
        return
    raise NotImplementedError(f"{type(spec)}, {str(spec)}")


_DTYPE_DIR = {
    "float16": torch.float16,
    "float32": torch.float32,
    "float64": torch.float64,
    "int64": torch.int64,
    "int32": torch.int32,
    "uint8": torch.uint8,
}
