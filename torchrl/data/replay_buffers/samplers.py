# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import json
import warnings
from abc import ABC, abstractmethod
from copy import copy, deepcopy
from multiprocessing.context import get_spawning_popen
from pathlib import Path
from typing import Any, Dict, Tuple, Union

import numpy as np
import torch

from tensordict import MemoryMappedTensor
from tensordict.utils import NestedKey

from ..._extension import EXTENSION_WARNING

try:
    from torchrl._torchrl import (
        MinSegmentTreeFp32,
        MinSegmentTreeFp64,
        SumSegmentTreeFp32,
        SumSegmentTreeFp64,
    )
except ImportError:
    warnings.warn(EXTENSION_WARNING)

from .storages import Storage, TensorStorage
from .utils import _to_numpy, INT_CLASSES

_EMPTY_STORAGE_ERROR = "Cannot sample from an empty storage."


class Sampler(ABC):
    """A generic sampler base class for composable Replay Buffers."""

    @abstractmethod
    def sample(self, storage: Storage, batch_size: int) -> Tuple[Any, dict]:
        ...

    def add(self, index: int) -> None:
        return

    def extend(self, index: torch.Tensor) -> None:
        return

    def update_priority(
        self, index: Union[int, torch.Tensor], priority: Union[float, torch.Tensor]
    ) -> dict:
        return

    def mark_update(self, index: Union[int, torch.Tensor]) -> None:
        return

    @property
    def default_priority(self) -> float:
        return 1.0

    def state_dict(self) -> Dict[str, Any]:
        return {}

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        return

    @property
    def ran_out(self) -> bool:
        # by default, samplers never run out
        return False

    @abstractmethod
    def _empty(self):
        ...

    @abstractmethod
    def dumps(self, path):
        ...

    @abstractmethod
    def loads(self, path):
        ...


class RandomSampler(Sampler):
    """A uniformly random sampler for composable replay buffers.

    Args:
        batch_size (int, optional): if provided, the batch size to be used by
            the replay buffer when calling :meth:`~.ReplayBuffer.sample`.

    """

    def sample(self, storage: Storage, batch_size: int) -> Tuple[torch.Tensor, dict]:
        if len(storage) == 0:
            raise RuntimeError(_EMPTY_STORAGE_ERROR)
        index = torch.randint(0, len(storage), (batch_size,))
        return index, {}

    def _empty(self):
        pass

    def dumps(self, path):
        # no op
        ...

    def loads(self, path):
        # no op
        ...


class SamplerWithoutReplacement(Sampler):
    """A data-consuming sampler that ensures that the same sample is not present in consecutive batches.

    Args:
        drop_last (bool, optional): if ``True``, the last incomplete sample (if any) will be dropped.
            If False, this last sample will be kept and (unlike with torch dataloaders)
            completed with other samples from a fresh indices permutation.

    *Caution*: If the size of the storage changes in between two calls, the samples will be re-shuffled
    (as we can't generally keep track of which samples have been sampled before and which haven't).

    Similarly, it is expected that the storage content remains the same in between two calls,
    but this is not enforced.

    When the sampler reaches the end of the list of available indices, a new sample order
    will be generated and the resulting indices will be completed with this new draw, which
    can lead to duplicated indices, unless the :obj:`drop_last` argument is set to ``True``.

    """

    def __init__(self, drop_last: bool = False):
        self._sample_list = None
        self.len_storage = 0
        self.drop_last = drop_last
        self._ran_out = False

    def dumps(self, path):
        path = Path(path)
        path.mkdir(exist_ok=True)

        with open(path / "sampler_metadata.json", "w") as file:
            json.dump(
                {
                    "len_storage": self.len_storage,
                    "_sample_list": self._sample_list,
                    "drop_last": self.drop_last,
                    "_ran_out": self._ran_out,
                },
                file,
            )

    def loads(self, path):
        with open(path / "sampler_metadata.json", "r") as file:
            metadata = json.load(file)
        self._sample_list = metadata["_sample_list"]
        self.len_storage = metadata["len_storage"]
        self.drop_last = metadata["drop_last"]
        self._ran_out = metadata["_ran_out"]

    def _single_sample(self, len_storage, batch_size):
        index = self._sample_list[:batch_size]
        self._sample_list = self._sample_list[batch_size:]

        # check if we have enough elements for one more batch, assuming same batch size
        # will be used each time sample is called
        if self._sample_list.numel() == 0 or (
            self.drop_last and len(self._sample_list) < batch_size
        ):
            self._ran_out = True
            self._sample_list = torch.randperm(len_storage)
        else:
            self._ran_out = False
        return index

    def sample(self, storage: Storage, batch_size: int) -> Tuple[Any, dict]:
        len_storage = len(storage)
        if len_storage == 0:
            raise RuntimeError(_EMPTY_STORAGE_ERROR)
        if not len_storage:
            raise RuntimeError("An empty storage was passed")
        if self.len_storage != len_storage or self._sample_list is None:
            self._sample_list = torch.randperm(len_storage)
        if len_storage < batch_size and self.drop_last:
            raise ValueError(
                f"The batch size ({batch_size}) is greater than the storage capacity ({len_storage}). "
                "This makes it impossible to return a sample without repeating indices. "
                "Consider changing the sampler class or turn the 'drop_last' argument to False."
            )
        self.len_storage = len_storage
        index = self._single_sample(len_storage, batch_size)
        # we 'always' return the indices. The 'drop_last' just instructs the
        # sampler to turn to 'ran_out = True` whenever the next sample
        # will be too short. This will be read by the replay buffer
        # as a signal for an early break of the __iter__().
        return index, {}

    @property
    def ran_out(self):
        return self._ran_out

    @ran_out.setter
    def ran_out(self, value):
        self._ran_out = value

    def _empty(self):
        self._sample_list = None
        self.len_storage = 0
        self._ran_out = False


class PrioritizedSampler(Sampler):
    """Prioritized sampler for replay buffer.

    Presented in "Schaul, T.; Quan, J.; Antonoglou, I.; and Silver, D. 2015.
        Prioritized experience replay."
        (https://arxiv.org/abs/1511.05952)

    Args:
        alpha (float): exponent α determines how much prioritization is used,
            with α = 0 corresponding to the uniform case.
        beta (float): importance sampling negative exponent.
        eps (float, optional): delta added to the priorities to ensure that the buffer
            does not contain null priorities. Defaults to 1e-8.
        reduction (str, optional): the reduction method for multidimensional
            tensordicts (ie stored trajectory). Can be one of "max", "min",
            "median" or "mean".

    """

    def __init__(
        self,
        max_capacity: int,
        alpha: float,
        beta: float,
        eps: float = 1e-8,
        dtype: torch.dtype = torch.float,
        reduction: str = "max",
    ) -> None:
        if alpha <= 0:
            raise ValueError(
                f"alpha must be strictly greater than 0, got alpha={alpha}"
            )
        if beta < 0:
            raise ValueError(f"beta must be greater or equal to 0, got beta={beta}")

        self._max_capacity = max_capacity
        self._alpha = alpha
        self._beta = beta
        self._eps = eps
        self.reduction = reduction
        self.dtype = dtype
        self._init()

    def __getstate__(self):
        if get_spawning_popen() is not None:
            raise RuntimeError(
                f"Samplers of type {type(self)} cannot be shared between processes."
            )
        state = copy(self.__dict__)
        return state

    def _init(self):
        if self.dtype in (torch.float, torch.FloatType, torch.float32):
            self._sum_tree = SumSegmentTreeFp32(self._max_capacity)
            self._min_tree = MinSegmentTreeFp32(self._max_capacity)
        elif self.dtype in (torch.double, torch.DoubleTensor, torch.float64):
            self._sum_tree = SumSegmentTreeFp64(self._max_capacity)
            self._min_tree = MinSegmentTreeFp64(self._max_capacity)
        else:
            raise NotImplementedError(
                f"dtype {self.dtype} not supported by PrioritizedSampler"
            )
        self._max_priority = 1.0

    def _empty(self):
        self._init()

    @property
    def default_priority(self) -> float:
        return (self._max_priority + self._eps) ** self._alpha

    def sample(self, storage: Storage, batch_size: int) -> torch.Tensor:
        if len(storage) == 0:
            raise RuntimeError(_EMPTY_STORAGE_ERROR)
        p_sum = self._sum_tree.query(0, len(storage))
        p_min = self._min_tree.query(0, len(storage))
        if p_sum <= 0:
            raise RuntimeError("negative p_sum")
        if p_min <= 0:
            raise RuntimeError("negative p_min")
        mass = np.random.uniform(0.0, p_sum, size=batch_size)
        index = self._sum_tree.scan_lower_bound(mass)
        if not isinstance(index, np.ndarray):
            index = np.array([index])
        if isinstance(index, torch.Tensor):
            index.clamp_max_(len(storage) - 1)
        else:
            index = np.clip(index, None, len(storage) - 1)
        weight = self._sum_tree[index]

        # Importance sampling weight formula:
        #   w_i = (p_i / sum(p) * N) ^ (-beta)
        #   weight_i = w_i / max(w)
        #   weight_i = (p_i / sum(p) * N) ^ (-beta) /
        #       ((min(p) / sum(p) * N) ^ (-beta))
        #   weight_i = ((p_i / sum(p) * N) / (min(p) / sum(p) * N)) ^ (-beta)
        #   weight_i = (p_i / min(p)) ^ (-beta)
        # weight = np.power(weight / (p_min + self._eps), -self._beta)
        weight = np.power(weight / p_min, -self._beta)
        return index, {"_weight": weight}

    def _add_or_extend(self, index: Union[int, torch.Tensor]) -> None:
        priority = self.default_priority

        if not (
            isinstance(priority, float)
            or len(priority) == 1
            or len(priority) == len(index)
        ):
            raise RuntimeError(
                "priority should be a scalar or an iterable of the same "
                "length as index"
            )

        self._sum_tree[index] = priority
        self._min_tree[index] = priority

    def add(self, index: int) -> None:
        super().add(index)
        if index is not None:
            # some writers don't systematically write data and can return None
            self._add_or_extend(index)

    def extend(self, index: torch.Tensor) -> None:
        super().extend(index)
        if index is not None:
            # some writers don't systematically write data and can return None
            self._add_or_extend(index)

    def update_priority(
        self, index: Union[int, torch.Tensor], priority: Union[float, torch.Tensor]
    ) -> None:
        """Updates the priority of the data pointed by the index.

        Args:
            index (int or torch.Tensor): indexes of the priorities to be
                updated.
            priority (Number or torch.Tensor): new priorities of the
                indexed elements.

        """
        if isinstance(index, INT_CLASSES):
            if not isinstance(priority, float):
                if len(priority) != 1:
                    raise RuntimeError(
                        f"priority length should be 1, got {len(priority)}"
                    )
                priority = priority.item()
        else:
            if not (
                isinstance(priority, float)
                or len(priority) == 1
                or len(index) == len(priority)
            ):
                raise RuntimeError(
                    "priority should be a number or an iterable of the same "
                    "length as index"
                )
            index = _to_numpy(index)
            priority = _to_numpy(priority)

        self._max_priority = max(self._max_priority, np.max(priority))
        priority = np.power(priority + self._eps, self._alpha)
        self._sum_tree[index] = priority
        self._min_tree[index] = priority

    def mark_update(self, index: Union[int, torch.Tensor]) -> None:
        self.update_priority(index, self.default_priority)

    def state_dict(self) -> Dict[str, Any]:
        return {
            "_alpha": self._alpha,
            "_beta": self._beta,
            "_eps": self._eps,
            "_max_priority": self._max_priority,
            "_sum_tree": deepcopy(self._sum_tree),
            "_min_tree": deepcopy(self._min_tree),
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        self._alpha = state_dict["_alpha"]
        self._beta = state_dict["_beta"]
        self._eps = state_dict["_eps"]
        self._max_priority = state_dict["_max_priority"]
        self._sum_tree = state_dict.pop("_sum_tree")
        self._min_tree = state_dict.pop("_min_tree")

    def dumps(self, path):
        path = Path(path).absolute()
        path.mkdir(exist_ok=True)
        try:
            mm_st = MemoryMappedTensor.from_filename(
                shape=(self._max_capacity,),
                dtype=torch.float64,
                filename=path / "sumtree.memmap",
            )
            mm_mt = MemoryMappedTensor.from_filename(
                shape=(self._max_capacity,),
                dtype=torch.float64,
                filename=path / "mintree.memmap",
            )
        except FileNotFoundError:
            mm_st = MemoryMappedTensor.empty(
                (self._max_capacity,),
                dtype=torch.float64,
                filename=path / "sumtree.memmap",
            )
            mm_mt = MemoryMappedTensor.empty(
                (self._max_capacity,),
                dtype=torch.float64,
                filename=path / "mintree.memmap",
            )
        mm_st.copy_(
            torch.tensor([self._sum_tree[i] for i in range(self._max_capacity)])
        )
        mm_mt.copy_(
            torch.tensor([self._min_tree[i] for i in range(self._max_capacity)])
        )
        with open(path / "sampler_metadata.json", "w") as file:
            json.dump(
                {
                    "_alpha": self._alpha,
                    "_beta": self._beta,
                    "_eps": self._eps,
                    "_max_priority": self._max_priority,
                    "_max_capacity": self._max_capacity,
                },
                file,
            )

    def loads(self, path):
        path = Path(path).absolute()
        with open(path / "sampler_metadata.json", "r") as file:
            metadata = json.load(file)
        self._alpha = metadata["_alpha"]
        self._beta = metadata["_beta"]
        self._eps = metadata["_eps"]
        self._max_priority = metadata["_max_priority"]
        _max_capacity = metadata["_max_capacity"]
        if _max_capacity != self._max_capacity:
            raise RuntimeError(
                f"max capacity of loaded metadata ({_max_capacity}) differs from self._max_capacity ({self._max_capacity})."
            )
        mm_st = MemoryMappedTensor.from_filename(
            shape=(self._max_capacity,),
            dtype=torch.float64,
            filename=path / "sumtree.memmap",
        )
        mm_mt = MemoryMappedTensor.from_filename(
            shape=(self._max_capacity,),
            dtype=torch.float64,
            filename=path / "mintree.memmap",
        )
        for i, elt in enumerate(mm_st.tolist()):
            self._sum_tree[i] = elt
        for i, elt in enumerate(mm_mt.tolist()):
            self._min_tree[i] = elt


class SliceSampler(Sampler):
    """Samples slices of data along the first dimension, given start and stop signals.

    Keyword Args:
        num_slices (int): the number of slices to be sampled. The batch-size
            must be greater or equal to the ``num_slices`` argument.
        end_key (NestedKey, optional): the key indicating the end of a
            trajectory (or episode). Defaults to ``("next", "done")``.
        traj_key (NestedKey, optional): the key indicating the trajectories.
            Defaults to ``"episode"`` (commonly used across datasets in TorchRL).
        cache_values (bool, optional): to be used with static datasets.
            Will cache the start and end signal of the trajectory.

    .. note:: To recover the trajectory splits in the storage,
        :class:`~torchrl.data.replay_buffers.samplers.SliceSampler` will first
        attempt to find the ``traj_key`` entry in the storage. If it cannot be
        found, the ``end_key`` will be used to reconstruct the episodes.

    Examples:
        >>> import torch
        >>> from tensordict import TensorDict
        >>> from torchrl.data.replay_buffers import LazyMemmapStorage, TensorDictReplayBuffer
        >>> from torchrl.data.replay_buffers.samplers import SliceSampler
        >>>
        >>> rb = TensorDictReplayBuffer(
        ...     storage=LazyMemmapStorage(1_000_000),
        ...     sampler=SliceSampler(cache_values=True, num_slices=10),
        ...     batch_size=320,
        ... )
        >>> episode = torch.zeros(1000, dtype=torch.int)
        >>> episode[:300] = 1
        >>> episode[300:550] = 2
        >>> episode[550:700] = 3
        >>> episode[700:] = 4
        >>> data = TensorDict(
        ...     {
        ...         "episode": episode,
        ...         "obs": torch.randn((3, 4, 5)).expand(1000, 3, 4, 5),
        ...         "act": torch.randn((20,)).expand(1000, 20),
        ...         "other": torch.randn((20, 50)).expand(1000, 20, 50),
        ...     }, [1000]
        ... )
        ... rb.extend(data)
        >>> print("sample:", rb.sample())

    :class:`torchrl.data.replay_buffers.SliceSampler` is default-compatible with
    most of TorchRL's datasets:

    Examples:
        >>> import torch
        >>>
        >>> from torchrl.data.datasets import RobosetExperienceReplay
        >>> from torchrl.data import SliceSampler
        >>>
        >>> torch.manual_seed(0)
        >>> num_slices = 10
        >>> dataid = list(RobosetExperienceReplay.available_datasets)[0]
        >>> data = RobosetExperienceReplay(dataid, batch_size=320, sampler=SliceSampler(num_slices=num_slices))
        >>> for batch in data:
        ...     batch = batch.reshape(num_slices, -1)
        ...     break
        >>> print("check that each batch only has one episode:", batch["episode"].unique(dim=1))
        check that each batch only has one episode: tensor([[19],
                [14],
                [ 8],
                [10],
                [13],
                [ 4],
                [ 2],
                [ 3],
                [22],
                [ 8]])

    """

    def __init__(
        self,
        *,
        num_slices: int,
        end_key: NestedKey = None,
        traj_key: NestedKey = None,
        cache_values: bool = False,
    ) -> object:
        if end_key is None:
            end_key = ("next", "done")
        if traj_key is None:
            traj_key = "episode"
        self.num_slices = num_slices
        self.end_key = end_key
        self.traj_key = traj_key
        self.cache_values = cache_values
        self._fetch_traj = True
        self._cache = {}

    def _find_start_stop_traj(self, *, trajectory=None, end=None):
        if trajectory is not None:
            end = trajectory[:-1] != trajectory[1:]
            end = torch.cat([end, torch.ones_like(end[:1])], 0)
        else:
            end = torch.index_fill(
                end,
                index=torch.tensor(-1, device=end.device, dtype=torch.long),
                dim=0,
                value=1,
            )
        if end.ndim != 1:
            raise RuntimeError(
                f"Expected the end-of-trajectory signal to be 1-dimensional. Got a {end.ndim} tensor instead."
            )
        stop_idx = end.view(-1).nonzero().view(-1)
        start_idx = torch.cat([torch.zeros_like(stop_idx[:1]), stop_idx[:-1] + 1])
        lengths = stop_idx - start_idx
        return start_idx, stop_idx, lengths

    def _tensor_slices_from_startend(self, seq_length, start):
        return (torch.arange(seq_length).unsqueeze(0) + start.unsqueeze(1)).view(-1)

    def _get_stop_and_length(self, storage, fallback=True):
        if self.cache_values and "stop-and-length" in self._cache:
            return self._cache.get("stop-and-length")

        if self._fetch_traj:
            # We first try with the traj_key
            try:
                # In some cases, the storage hides the data behind "_data".
                # In the future, this may be deprecated, and we don't want to mess
                # with the keys provided by the user so we fall back on a proxy to
                # the traj key.
                try:
                    trajectory = storage.get(self._used_traj_key)
                except KeyError:
                    trajectory = storage.get(("_data", self.traj_key))
                    # cache that value for future use
                    self._used_traj_key = ("_data", self.traj_key)
                return self._cache.setdefault(
                    "stop-and-length", self._find_start_stop_traj(trajectory=trajectory)
                )
            except KeyError:
                if fallback:
                    self._fetch_traj = False
                    return self._get_stop_and_length(storage, fallback=False)
                raise

        else:
            try:
                # In some cases, the storage hides the data behind "_data".
                # In the future, this may be deprecated, and we don't want to mess
                # with the keys provided by the user so we fall back on a proxy to
                # the traj key.
                try:
                    done = storage.get(self._used_end_key)
                except KeyError:
                    done = storage.get(("_data", self.end_key))
                    # cache that value for future use
                    self._used_end_key = ("_data", self.end_key)
                return self._cache.setdefault(
                    "stop-and-length", self._find_start_stop_traj(end=done.squeeze())
                )
            except KeyError:
                if fallback:
                    self._fetch_traj = True
                    return self._get_stop_and_length(storage, fallback=False)
                raise

    def sample(self, storage: Storage, batch_size: int) -> Tuple[torch.Tensor, dict]:
        if not isinstance(storage, TensorStorage):
            raise RuntimeError(
                f"{type(self)} can only sample from TensorStorage subclasses, got {type(storage)} instead."
            )
        seq_length = batch_size // self.num_slices
        # pick up as many trajs as we need
        start_idx, stop_idx, lengths = self._get_stop_and_length(storage)
        if (lengths < seq_length).any():
            raise RuntimeError(
                "Some stored trajectories have a length shorter than the slice that was asked for."
            )
        traj_idx = torch.randint(lengths.shape[0], (self.num_slices,))
        relative_starts = (
            (torch.rand(self.num_slices) * (lengths[traj_idx] - seq_length))
            .floor()
            .to(start_idx.dtype)
        )
        starts = start_idx[traj_idx] + relative_starts
        index = self._tensor_slices_from_startend(seq_length, starts)
        return index.to(torch.long), {}

    @property
    def _used_traj_key(self):
        return self.__dict__.get("__used_traj_key", self.traj_key)

    @_used_traj_key.setter
    def _used_traj_key(self, value):
        self.__used_traj_key = value

    @property
    def _used_end_key(self):
        return self.__dict__.get("__used_end_key", self.end_key)

    @_used_end_key.setter
    def _used_end_key(self, value):
        self.__used_end_key = value

    def _empty(self):
        pass

    def dumps(self, path):
        # no op - cache does not need to be saved
        ...

    def loads(self, path):
        # no op
        ...

    def __getstate__(self):
        state = copy(self.__dict__)
        state["_cache"] = {}
        return state
