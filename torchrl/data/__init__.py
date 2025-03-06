# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from .llm import (
    AdaptiveKLController,
    ConstantKLController,
    create_infinite_iterator,
    get_dataloader,
    LLMData,
    LLMInput,
    LLMOutput,
    PairwiseDataset,
    PromptData,
    PromptTensorDictTokenizer,
    RewardData,
    RolloutFromModel,
    TensorDictTokenizer,
    TokenizedDatasetLoader,
)
from .map import (
    BinaryToDecimal,
    HashToInt,
    MCTSForest,
    QueryModule,
    RandomProjectionHash,
    SipHash,
    TensorDictMap,
    TensorMap,
    Tree,
)
from .postprocs import DensifyReward, MultiStep
from .replay_buffers import (
    Flat2TED,
    FlatStorageCheckpointer,
    H5Combine,
    H5Split,
    H5StorageCheckpointer,
    ImmutableDatasetWriter,
    LazyMemmapStorage,
    LazyStackStorage,
    LazyTensorStorage,
    ListStorage,
    ListStorageCheckpointer,
    Nested2TED,
    NestedStorageCheckpointer,
    PrioritizedReplayBuffer,
    PrioritizedSampler,
    PrioritizedSliceSampler,
    RandomSampler,
    RayReplayBuffer,
    RemoteTensorDictReplayBuffer,
    ReplayBuffer,
    ReplayBufferEnsemble,
    RoundRobinWriter,
    SamplerEnsemble,
    SamplerWithoutReplacement,
    SliceSampler,
    SliceSamplerWithoutReplacement,
    Storage,
    StorageCheckpointerBase,
    StorageEnsemble,
    StorageEnsembleCheckpointer,
    TED2Flat,
    TED2Nested,
    TensorDictMaxValueWriter,
    TensorDictPrioritizedReplayBuffer,
    TensorDictReplayBuffer,
    TensorDictRoundRobinWriter,
    TensorStorage,
    TensorStorageCheckpointer,
    Writer,
    WriterEnsemble,
)
from .tensor_specs import (
    Binary,
    BinaryDiscreteTensorSpec,
    Bounded,
    BoundedContinuous,
    BoundedTensorSpec,
    Categorical,
    Choice,
    Composite,
    CompositeSpec,
    DEVICE_TYPING,
    DiscreteTensorSpec,
    LazyStackedCompositeSpec,
    LazyStackedTensorSpec,
    MultiCategorical,
    MultiDiscreteTensorSpec,
    MultiOneHot,
    MultiOneHotDiscreteTensorSpec,
    NonTensor,
    NonTensorSpec,
    OneHot,
    OneHotDiscreteTensorSpec,
    Stacked,
    StackedComposite,
    TensorSpec,
    Unbounded,
    UnboundedContinuous,
    UnboundedContinuousTensorSpec,
    UnboundedDiscrete,
    UnboundedDiscreteTensorSpec,
)
from .utils import check_no_exclusive_keys, consolidate_spec, contains_lazy_spec

__all__ = [
    "AdaptiveKLController",
    "Binary",
    "BinaryDiscreteTensorSpec",
    "BinaryToDecimal",
    "Bounded",
    "BoundedContinuous",
    "BoundedTensorSpec",
    "Categorical",
    "Choice",
    "Composite",
    "CompositeSpec",
    "ConstantKLController",
    "DEVICE_TYPING",
    "DensifyReward",
    "DiscreteTensorSpec",
    "Flat2TED",
    "FlatStorageCheckpointer",
    "H5Combine",
    "H5Split",
    "H5StorageCheckpointer",
    "HashToInt",
    "ImmutableDatasetWriter",
    "LLMData",
    "LLMInput",
    "LLMOutput",
    "LazyMemmapStorage",
    "LazyStackStorage",
    "LazyStackedCompositeSpec",
    "LazyStackedTensorSpec",
    "LazyTensorStorage",
    "ListStorage",
    "ListStorageCheckpointer",
    "MCTSForest",
    "MultiCategorical",
    "MultiDiscreteTensorSpec",
    "MultiOneHot",
    "MultiOneHotDiscreteTensorSpec",
    "MultiStep",
    "Nested2TED",
    "NestedStorageCheckpointer",
    "NonTensor",
    "NonTensorSpec",
    "OneHot",
    "OneHotDiscreteTensorSpec",
    "PairwiseDataset",
    "PrioritizedReplayBuffer",
    "PrioritizedSampler",
    "PrioritizedSliceSampler",
    "PromptData",
    "PromptTensorDictTokenizer",
    "QueryModule",
    "RandomProjectionHash",
    "RandomSampler",
    "RemoteTensorDictReplayBuffer",
    "ReplayBuffer",
    "ReplayBufferEnsemble",
    "RewardData",
    "RolloutFromModel",
    "RoundRobinWriter",
    "SamplerEnsemble",
    "SamplerWithoutReplacement",
    "SipHash",
    "SliceSampler",
    "SliceSamplerWithoutReplacement",
    "Stacked",
    "StackedComposite",
    "Storage",
    "StorageCheckpointerBase",
    "StorageEnsemble",
    "StorageEnsembleCheckpointer",
    "TED2Flat",
    "TED2Nested",
    "TensorDictMap",
    "TensorDictMaxValueWriter",
    "TensorDictPrioritizedReplayBuffer",
    "TensorDictReplayBuffer",
    "TensorDictRoundRobinWriter",
    "TensorDictTokenizer",
    "TensorMap",
    "TensorSpec",
    "TensorStorage",
    "TensorStorageCheckpointer",
    "TokenizedDatasetLoader",
    "Binary",
    "BinaryDiscreteTensorSpec",
    "Bounded",
    "BoundedContinuous",
    "BoundedTensorSpec",
    "Categorical",
    "Choice",
    "Composite",
    "CompositeSpec",
    "DEVICE_TYPING",
    "DiscreteTensorSpec",
    "LazyStackedCompositeSpec",
    "LazyStackedTensorSpec",
    "MultiCategorical",
    "MultiDiscreteTensorSpec",
    "MultiOneHot",
    "MultiOneHotDiscreteTensorSpec",
    "RayReplayBuffer",
    "NonTensor",
    "NonTensorSpec",
    "OneHot",
    "OneHotDiscreteTensorSpec",
    "Stacked",
    "StackedComposite",
    "TensorSpec",
    "Tree",
    "Unbounded",
    "UnboundedContinuous",
    "UnboundedContinuousTensorSpec",
    "UnboundedDiscrete",
    "UnboundedDiscreteTensorSpec",
    "Writer",
    "WriterEnsemble",
    "check_no_exclusive_keys",
    "consolidate_spec",
    "contains_lazy_spec",
    "create_infinite_iterator",
    "get_dataloader",
]
