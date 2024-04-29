# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from .postprocs import MultiStep
from .replay_buffers import (
    Flat2TED,
    ImmutableDatasetWriter,
    LazyMemmapStorage,
    LazyTensorStorage,
    ListStorage,
    PrioritizedReplayBuffer,
    PrioritizedSampler,
    RandomSampler,
    RemoteTensorDictReplayBuffer,
    ReplayBuffer,
    ReplayBufferEnsemble,
    RoundRobinWriter,
    SamplerEnsemble,
    SamplerWithoutReplacement,
    SliceSampler,
    SliceSamplerWithoutReplacement,
    Storage,
    StorageEnsemble,
    TED2Flat,
    TensorDictMaxValueWriter,
    TensorDictPrioritizedReplayBuffer,
    TensorDictReplayBuffer,
    TensorDictRoundRobinWriter,
    TensorStorage,
    Writer,
    WriterEnsemble,
)
from .rlhf import (
    AdaptiveKLController,
    ConstantKLController,
    create_infinite_iterator,
    get_dataloader,
    PairwiseDataset,
    PromptData,
    PromptTensorDictTokenizer,
    RewardData,
    RolloutFromModel,
    TensorDictTokenizer,
    TokenizedDatasetLoader,
)
from .tensor_specs import (
    BinaryDiscreteTensorSpec,
    BoundedTensorSpec,
    CompositeSpec,
    DEVICE_TYPING,
    DiscreteTensorSpec,
    LazyStackedCompositeSpec,
    LazyStackedTensorSpec,
    MultiDiscreteTensorSpec,
    MultiOneHotDiscreteTensorSpec,
    NonTensorSpec,
    OneHotDiscreteTensorSpec,
    TensorSpec,
    UnboundedContinuousTensorSpec,
    UnboundedDiscreteTensorSpec,
)
from .utils import check_no_exclusive_keys, consolidate_spec, contains_lazy_spec
