# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from .batched_envs import ParallelEnv, SerialEnv
from .common import EnvBase, EnvMetaData, make_tensordict
from .env_creator import EnvCreator, get_env_metadata
from .gym_like import default_info_dict_reader, GymLikeEnv
from .libs import (
    BraxEnv,
    BraxWrapper,
    DMControlEnv,
    DMControlWrapper,
    gym_backend,
    GymEnv,
    GymWrapper,
    HabitatEnv,
    IsaacGymEnv,
    IsaacGymWrapper,
    JumanjiEnv,
    JumanjiWrapper,
    MOGymEnv,
    MOGymWrapper,
    MultiThreadedEnv,
    MultiThreadedEnvWrapper,
    OpenMLEnv,
    PettingZooEnv,
    PettingZooWrapper,
    RoboHiveEnv,
    set_gym_backend,
    SMACv2Env,
    SMACv2Wrapper,
    VmasEnv,
    VmasWrapper,
)
from .model_based import ModelBasedEnvBase
from .transforms import (
    ActionMask,
    BinarizeReward,
    CatFrames,
    CatTensors,
    CenterCrop,
    ClipTransform,
    Compose,
    DeviceCastTransform,
    DiscreteActionProjection,
    DoubleToFloat,
    DTypeCastTransform,
    EndOfLifeTransform,
    ExcludeTransform,
    FiniteTensorDictCheck,
    FlattenObservation,
    FrameSkipTransform,
    GrayScale,
    gSDENoise,
    InitTracker,
    KLRewardTransform,
    NoopResetEnv,
    ObservationNorm,
    ObservationTransform,
    PermuteTransform,
    PinMemoryTransform,
    R3MTransform,
    RandomCropTensorDict,
    RenameTransform,
    Resize,
    Reward2GoTransform,
    RewardClipping,
    RewardScaling,
    RewardSum,
    SelectTransform,
    SqueezeTransform,
    StepCounter,
    TargetReturn,
    TensorDictPrimer,
    TimeMaxPool,
    ToTensorImage,
    Transform,
    TransformedEnv,
    UnsqueezeTransform,
    VC1Transform,
    VecGymEnvTransform,
    VecNorm,
    VIPRewardTransform,
    VIPTransform,
    History
)
from .utils import (
    check_env_specs,
    check_marl_grouping,
    exploration_mode,
    exploration_type,
    ExplorationType,
    make_composite_from_td,
    MarlGroupMapType,
    set_exploration_mode,
    set_exploration_type,
    step_mdp,
)
