# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
from __future__ import annotations

import abc
import pickle
import shutil
import tempfile
from pathlib import Path
from typing import Callable

import torch
from tensordict import TensorDictBase
from torch import multiprocessing as mp

from torchrl.data import ReplayBuffer
from torchrl.data.replay_buffers import TensorDictReplayBuffer, TensorStorage
from torchrl.data.utils import CloudpickleWrapper


class BaseDatasetExperienceReplay(TensorDictReplayBuffer):
    """Parent class for offline datasets."""

    @property
    @abc.abstractmethod
    def data_path(self) -> Path:
        """Path to the dataset, including split."""
        ...

    @property
    @abc.abstractmethod
    def data_path_root(self) -> Path:
        """Path to the dataset root."""
        ...

    @abc.abstractmethod
    def _is_downloaded(self) -> bool:
        """Checks if the data has been downloaded."""
        ...

    @property
    def root(self) -> Path:
        return self._root

    @root.setter
    def root(self, value):
        self._root = Path(value)

    def preprocess(
        self,
        fn: Callable[[TensorDictBase], TensorDictBase],
        dim: int = 0,
        num_workers: int | None = None,
        *,
        chunksize: int | None = None,
        num_chunks: int | None = None,
        pool: mp.Pool | None = None,
        generator: torch.Generator | None = None,
        max_tasks_per_child: int | None = None,
        worker_threads: int = 1,
        index_with_generator: bool = False,
        pbar: bool = False,
        mp_start_method: str | None = None,
        num_frames: int | None = None,
        dest: str | Path | None = None,
    ):
        """Preprocesses a dataset, discards the previous data an replaces it with the newly formatted data.

        The data transform must be unitary (work on a single sample of the dataset).

        Args and Keyword Args are forwarded to :meth:`~tensordict.TensorDictBase.map`.

        Keyword Args:
            num_frames (int, optional): if provided, only the first `num_frames` will be
                transformed. This is useful to debug the transform at first.
            dest (path or equivalent, optional): a path to the location of the new dataset.
                If not provided or `"same"` (default) the dataset will be updated in-place
                and the previously downloaded data will be discarded.
                If `dest` is a path to a new storage location, the sampler will be identical
                to the current sampler, as well as the writer. The transforms however will
                not be copied.

        Returns: The same dataset with the updated storage if ``dest="same"`` or a new
            dataset with the updated storage otherwise.

        Examples:
            >>> from torchrl.data.datasets import MinariExperienceReplay
            >>>
            >>> data = MinariExperienceReplay(
            ...     list(MinariExperienceReplay.available_datasets)[0],
            ...     batch_size=32
            ...     )
            >>> print(data)
            MinariExperienceReplay(
                storages=TensorStorage(TensorDict(
                    fields={
                        action: MemoryMappedTensor(shape=torch.Size([1000000, 8]), device=cpu, dtype=torch.float32, is_shared=True),
                        episode: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.int64, is_shared=True),
                        info: TensorDict(
                            fields={
                                distance_from_origin: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                forward_reward: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                goal: MemoryMappedTensor(shape=torch.Size([1000000, 2]), device=cpu, dtype=torch.float64, is_shared=True),
                                qpos: MemoryMappedTensor(shape=torch.Size([1000000, 15]), device=cpu, dtype=torch.float64, is_shared=True),
                                qvel: MemoryMappedTensor(shape=torch.Size([1000000, 14]), device=cpu, dtype=torch.float64, is_shared=True),
                                reward_ctrl: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                reward_forward: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                reward_survive: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                success: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.bool, is_shared=True),
                                x_position: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                x_velocity: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                y_position: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                y_velocity: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True)},
                            batch_size=torch.Size([1000000]),
                            device=cpu,
                            is_shared=False),
                        next: TensorDict(
                            fields={
                                done: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.bool, is_shared=True),
                                info: TensorDict(
                                    fields={
                                        distance_from_origin: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        forward_reward: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        goal: MemoryMappedTensor(shape=torch.Size([1000000, 2]), device=cpu, dtype=torch.float64, is_shared=True),
                                        qpos: MemoryMappedTensor(shape=torch.Size([1000000, 15]), device=cpu, dtype=torch.float64, is_shared=True),
                                        qvel: MemoryMappedTensor(shape=torch.Size([1000000, 14]), device=cpu, dtype=torch.float64, is_shared=True),
                                        reward_ctrl: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        reward_forward: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        reward_survive: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        success: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.bool, is_shared=True),
                                        x_position: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        x_velocity: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        y_position: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True),
                                        y_velocity: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.float64, is_shared=True)},
                                    batch_size=torch.Size([1000000]),
                                    device=cpu,
                                    is_shared=False),
                                observation: TensorDict(
                                    fields={
                                        achieved_goal: MemoryMappedTensor(shape=torch.Size([1000000, 2]), device=cpu, dtype=torch.float64, is_shared=True),
                                        desired_goal: MemoryMappedTensor(shape=torch.Size([1000000, 2]), device=cpu, dtype=torch.float64, is_shared=True),
                                        observation: MemoryMappedTensor(shape=torch.Size([1000000, 27]), device=cpu, dtype=torch.float64, is_shared=True)},
                                    batch_size=torch.Size([1000000]),
                                    device=cpu,
                                    is_shared=False),
                                reward: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.float64, is_shared=True),
                                terminated: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.bool, is_shared=True),
                                truncated: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.bool, is_shared=True)},
                            batch_size=torch.Size([1000000]),
                            device=cpu,
                            is_shared=False),
                        observation: TensorDict(
                            fields={
                                achieved_goal: MemoryMappedTensor(shape=torch.Size([1000000, 2]), device=cpu, dtype=torch.float64, is_shared=True),
                                desired_goal: MemoryMappedTensor(shape=torch.Size([1000000, 2]), device=cpu, dtype=torch.float64, is_shared=True),
                                observation: MemoryMappedTensor(shape=torch.Size([1000000, 27]), device=cpu, dtype=torch.float64, is_shared=True)},
                            batch_size=torch.Size([1000000]),
                            device=cpu,
                            is_shared=False)},
                    batch_size=torch.Size([1000000]),
                    device=cpu,
                    is_shared=False)),
                samplers=RandomSampler,
                writers=ImmutableDatasetWriter(),
            batch_size=32,
            transform=Compose(
            ),
            collate_fn=<function _collate_id at 0x120e21dc0>)
            >>> from torchrl.envs import CatTensors, Compose
            >>>
            >>> cat_tensors = CatTensors(
            ...     in_keys=[("observation", "observation"), ("observation", "achieved_goal"),
            ...              ("observation", "desired_goal")],
            ...     out_key="obs"
            ...     )
            >>> cat_next_tensors = CatTensors(
            ...     in_keys=[("next", "observation", "observation"),
            ...              ("next", "observation", "achieved_goal"),
            ...              ("next", "observation", "desired_goal")],
            ...     out_key=("next", "obs")
            ...     )
            >>> t = Compose(cat_tensors, cat_next_tensors)
            >>>
            >>> def func(td):
            ...     td = td.select(
            ...         "action",
            ...         "episode",
            ...         ("next", "done"),
            ...         ("next", "observation"),
            ...         ("next", "reward"),
            ...         ("next", "terminated"),
            ...         ("next", "truncated"),
            ...         "observation"
            ...         )
            ...     td = t(td)
            ...     return td
            >>>
            >>> data.preprocess(func, num_workers=4, pbar=True, mp_start_method="fork")
            >>> print(data)
            MinariExperienceReplay(
                storages=TensorStorage(TensorDict(
                    fields={
                        action: MemoryMappedTensor(shape=torch.Size([1000000, 8]), device=cpu, dtype=torch.float32, is_shared=True),
                        episode: MemoryMappedTensor(shape=torch.Size([1000000]), device=cpu, dtype=torch.int64, is_shared=True),
                        next: TensorDict(
                            fields={
                                done: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.bool, is_shared=True),
                                obs: MemoryMappedTensor(shape=torch.Size([1000000, 31]), device=cpu, dtype=torch.float64, is_shared=True),
                                observation: TensorDict(
                                    fields={
                                    },
                                    batch_size=torch.Size([1000000]),
                                    device=cpu,
                                    is_shared=False),
                                reward: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.float64, is_shared=True),
                                terminated: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.bool, is_shared=True),
                                truncated: MemoryMappedTensor(shape=torch.Size([1000000, 1]), device=cpu, dtype=torch.bool, is_shared=True)},
                            batch_size=torch.Size([1000000]),
                            device=cpu,
                            is_shared=False),
                        obs: MemoryMappedTensor(shape=torch.Size([1000000, 31]), device=cpu, dtype=torch.float64, is_shared=True),
                        observation: TensorDict(
                            fields={
                            },
                            batch_size=torch.Size([1000000]),
                            device=cpu,
                            is_shared=False)},
                    batch_size=torch.Size([1000000]),
                    device=cpu,
                    is_shared=False)),
                samplers=RandomSampler,
                writers=ImmutableDatasetWriter(),
            batch_size=32,
            transform=Compose(
            ),
            collate_fn=<function _collate_id at 0x120e21dc0>)

        """
        if not _can_be_pickled(fn):
            fn = CloudpickleWrapper(fn)
        if isinstance(self._storage, TensorStorage):
            item = self._storage[0]
            with item.unlock_():
                example_data = fn(item)
            with tempfile.TemporaryDirectory() as mock_folder:
                mmlike = example_data.expand(
                    (self._storage.shape[0], *example_data.shape)
                ).memmap_like(mock_folder, num_threads=32)
                storage = self._storage._storage
                if num_frames is not None:
                    storage = storage[:num_frames]
                with storage.unlock_():
                    storage.map(
                        fn=fn,
                        dim=dim,
                        num_workers=num_workers,
                        chunksize=chunksize,
                        num_chunks=num_chunks,
                        pool=pool,
                        generator=generator,
                        max_tasks_per_child=max_tasks_per_child,
                        worker_threads=worker_threads,
                        index_with_generator=index_with_generator,
                        pbar=pbar,
                        mp_start_method=mp_start_method,
                        out=mmlike,
                    )
                if dest is None or dest == "same":
                    shutil.rmtree(self.data_path)
                    shutil.move(mock_folder, self.data_path)
                    self._storage._storage = TensorDictBase.load_memmap(self.data_path)
                    return self
                else:
                    self_copy = ReplayBuffer(
                        storage=TensorStorage(mmlike),
                        sampler=self.sampler,
                        writer=self.writer,
                        collate_fn=self._collate_fn,
                        batch_size=self._batch_size,
                    )
                    return self_copy
        else:
            raise NotImplementedError


def _can_be_pickled(obj):
    try:
        pickle.dumps(obj)
        return True
    except (pickle.PickleError, AttributeError, TypeError):
        return False
