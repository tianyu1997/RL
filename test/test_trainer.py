# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import argparse
import os
import tempfile
from argparse import Namespace
from collections import OrderedDict
from os import path, walk
from time import sleep

import pytest
import torch
from torch import nn
from torch.testing._internal.common_utils import TemporaryFileName

try:
    from tensorboard.backend.event_processing import event_accumulator
    from torchrl.trainers.loggers.tensorboard import TensorboardLogger

    _has_tb = True
except ImportError:
    _has_tb = False

from torchrl.data import (
    TensorDict,
    TensorDictPrioritizedReplayBuffer,
    TensorDictReplayBuffer,
    ListStorage,
    LazyMemmapStorage,
)
from torchrl.envs.libs.gym import _has_gym
from torchrl.trainers import Recorder, Trainer
from torchrl.trainers.helpers import transformed_env_constructor
from torchrl.trainers.trainers import (
    _has_tqdm,
    BatchSubSampler,
    CountFramesLog,
    LogReward,
    mask_batch,
    ReplayBufferTrainer,
    RewardNormalizer,
    SelectKeys,
    UpdateWeights,
)


class MockingOptim:
    param_groups = [{"params": []}]


class MockingCollector:
    called_update_policy_weights_ = False

    def set_seed(self, seed, **kwargs):
        return seed

    def update_policy_weights_(self):
        self.called_update_policy_weights_ = True

    def shutdown(self):
        pass

    def state_dict(self):
        return dict()

    def load_state_dict(self, state_dict):
        pass


class MockingLossModule(nn.Module):
    pass


def mocking_trainer(file=None) -> Trainer:
    trainer = Trainer(
        MockingCollector(),
        *[
            None,
        ]
        * 2,
        loss_module=MockingLossModule(),
        optimizer=MockingOptim(),
        save_trainer_file=file,
    )
    trainer._pbar_str = OrderedDict()
    return trainer


class TestSelectKeys:
    def test_selectkeys(self):
        trainer = mocking_trainer()
        key1 = "first key"
        key2 = "second key"
        td = TensorDict(
            {
                key1: torch.randn(3),
                key2: torch.randn(3),
            },
            [],
        )
        trainer.register_op("batch_process", SelectKeys([key1]))
        td_out = trainer._process_batch_hook(td)
        assert key1 in td_out.keys()
        assert key2 not in td_out.keys()

    def test_selectkeys_statedict(self):
        trainer = mocking_trainer()
        key1 = "first key"
        key2 = "second key"
        td = TensorDict(
            {
                key1: torch.randn(3),
                key2: torch.randn(3),
            },
            [],
        )
        trainer.register_op("batch_process", SelectKeys([key1]))
        trainer._process_batch_hook(td)

        trainer2 = mocking_trainer()
        trainer2.register_op("batch_process", SelectKeys([key1]))
        sd = trainer.state_dict()
        assert not len(sd["_batch_process_ops"][0][0])  # state_dict is empty
        trainer2.load_state_dict(sd)

    @pytest.mark.parametrize("backend", ["torchsnapshot", "torch"])
    def test_selectkeys_save(self, backend):
        # we overwrite the method to make sure that load_state_dict and state_dict are being called
        state_dict_fun = SelectKeys.state_dict
        load_state_dict_fun = SelectKeys.load_state_dict
        state_dict_has_been_called = [False]
        load_state_dict_has_been_called = [False]
        def new_state_dict(self):
            state_dict_has_been_called[0] = True
            return state_dict_fun(self)

        def new_load_state_dict(self, state_dict):
            load_state_dict_has_been_called[0] = True
            return load_state_dict_fun(self, state_dict)

        SelectKeys.state_dict = new_state_dict
        SelectKeys.load_state_dict = new_load_state_dict

        os.environ["CKPT_BACKEND"] = backend

        with tempfile.TemporaryDirectory() as tmpdirname:
            if backend == "torch":
                file = path.join(tmpdirname, "file.pt")
            else:
                file = tmpdirname
            trainer = mocking_trainer(file=file)
            key1 = "first key"
            key2 = "second key"
            td = TensorDict(
                {
                    key1: torch.randn(3),
                    key2: torch.randn(3),
                },
                [],
            )
            select_keys = SelectKeys([key1])
            select_keys.register(trainer)
            trainer._process_batch_hook(td)
            trainer.save_trainer(force_save=True)
            assert state_dict_has_been_called[0]

            trainer2 = mocking_trainer()
            select_keys2 = SelectKeys([key1])
            select_keys2.register(trainer2)

            trainer2.load_from_file(file)
            assert state_dict_has_been_called[0]
            if backend == "torch":
                assert load_state_dict_has_been_called[0]

        SelectKeys.state_dict = state_dict_fun
        SelectKeys.load_state_dict = load_state_dict_fun

@pytest.mark.parametrize("prioritized", [True, False])
class TestRB:
    def test_rb_trainer(self, prioritized):
        trainer = mocking_trainer()
        S = 100
        if prioritized:
            replay_buffer = TensorDictPrioritizedReplayBuffer(S, 1.1, 0.9)
        else:
            replay_buffer = TensorDictReplayBuffer(S)

        N = 9
        rb_trainer = ReplayBufferTrainer(replay_buffer=replay_buffer, batch_size=N)

        rb_trainer.register(trainer)

        key1 = "first key"
        key2 = "second key"
        batch = 101
        td = TensorDict(
            {
                key1: torch.randn(batch, 3),
                key2: torch.randn(batch, 3),
            },
            [batch],
        )
        td_out = trainer._process_batch_hook(td)
        assert td_out is td

        td_out = trainer._process_optim_batch_hook(td)
        assert td_out is not td
        assert td_out.shape[0] == N

        if prioritized:
            td_out.set(replay_buffer.priority_key, torch.rand(N))

        td_out = trainer._post_loss_hook(td_out)
        if prioritized:
            for idx in range(min(S, batch)):
                if idx in td_out.get("index"):
                    assert replay_buffer._sum_tree[idx] != 1.0
                else:
                    assert replay_buffer._sum_tree[idx] == 1.0
        else:
            assert "index" not in td_out.keys()

    @pytest.mark.parametrize(
        "storage_type",
        [
            "memmap",
            "list",
        ],
    )
    def test_rb_trainer_state_dict(self, prioritized, storage_type):
        trainer = mocking_trainer()
        S = 100
        if storage_type == "list":
            storage = ListStorage(S)
            collate_fn = lambda x: torch.stack(x, 0)
        elif storage_type == "memmap":
            storage = LazyMemmapStorage(S)
            collate_fn = lambda x: x
        else:
            raise NotImplementedError

        if prioritized:
            replay_buffer = TensorDictPrioritizedReplayBuffer(
                S, 1.1, 0.9, storage=storage, collate_fn=collate_fn
            )
        else:
            replay_buffer = TensorDictReplayBuffer(
                S, storage=storage, collate_fn=collate_fn
            )

        N = 9
        rb_trainer = ReplayBufferTrainer(replay_buffer=replay_buffer, batch_size=N)

        rb_trainer.register(trainer)

        key1 = "first key"
        key2 = "second key"
        batch = 101
        td = TensorDict(
            {
                key1: torch.randn(batch, 3),
                key2: torch.randn(batch, 3),
            },
            [batch],
        )
        trainer._process_batch_hook(td)
        td_out = trainer._process_optim_batch_hook(td)
        if prioritized:
            td_out.set(replay_buffer.priority_key, torch.rand(N))
        trainer._post_loss_hook(td_out)

        trainer2 = mocking_trainer()
        if prioritized:
            replay_buffer2 = TensorDictPrioritizedReplayBuffer(
                S, 1.1, 0.9, storage=storage
            )
        else:
            replay_buffer2 = TensorDictReplayBuffer(S, storage=storage)
        N = 9
        rb_trainer2 = ReplayBufferTrainer(replay_buffer=replay_buffer2, batch_size=N)
        rb_trainer2.register(trainer2)
        sd = trainer.state_dict()
        trainer2.load_state_dict(sd)

        assert rb_trainer2.replay_buffer.cursor > 0
        assert rb_trainer2.replay_buffer.cursor == rb_trainer.replay_buffer.cursor

        if storage_type == "list":
            assert len(rb_trainer2.replay_buffer._storage._storage) > 0
            assert len(rb_trainer2.replay_buffer._storage._storage) == len(
                rb_trainer.replay_buffer._storage._storage
            )
            for i, s in enumerate(rb_trainer2.replay_buffer._storage._storage):
                assert (s == rb_trainer.replay_buffer._storage._storage[i]).all()
        elif storage_type == "memmap":
            assert rb_trainer2.replay_buffer._storage._len > 0
            assert (
                rb_trainer2.replay_buffer._storage._storage
                == rb_trainer.replay_buffer._storage._storage
            ).all()

    @pytest.mark.parametrize(
        "storage_type",
        [
            "memmap",
            "list",
        ],
    )
    @pytest.mark.parametrize("backend", ["torch", "torchsnapshot",])
    def test_rb_trainer_save(self, prioritized, storage_type, backend):
        # we overwrite the method to make sure that load_state_dict and state_dict are being called
        state_dict_fun = ReplayBufferTrainer.state_dict
        load_state_dict_fun = ReplayBufferTrainer.load_state_dict
        state_dict_has_been_called = [False]
        load_state_dict_has_been_called = [False]

        def new_state_dict(self):
            state_dict_has_been_called[0] = True
            return state_dict_fun(self)

        def new_load_state_dict(self, state_dict):
            load_state_dict_has_been_called[0] = True
            return load_state_dict_fun(self, state_dict)

        ReplayBufferTrainer.state_dict = new_state_dict
        ReplayBufferTrainer.load_state_dict = new_load_state_dict

        os.environ["CKPT_BACKEND"] = backend
        def make_storage():
            if storage_type == "list":
                storage = ListStorage(S)
                collate_fn = lambda x: torch.stack(x, 0)
            elif storage_type == "memmap":
                storage = LazyMemmapStorage(S)
                collate_fn = lambda x: x
            else:
                raise NotImplementedError
            return storage, collate_fn

        with tempfile.TemporaryDirectory() as tmpdirname:
            if backend == "torch":
                file = path.join(tmpdirname, "file.pt")
            else:
                file = tmpdirname
            trainer = mocking_trainer(file)
            S = 100
            storage, collate_fn = make_storage()
            if prioritized:
                replay_buffer = TensorDictPrioritizedReplayBuffer(
                    S, 1.1, 0.9, storage=storage, collate_fn=collate_fn
                )
            else:
                replay_buffer = TensorDictReplayBuffer(
                    S, storage=storage, collate_fn=collate_fn
                )

            N = 9
            rb_trainer = ReplayBufferTrainer(replay_buffer=replay_buffer, batch_size=N)
            rb_trainer.register(trainer)
            key1 = "first key"
            key2 = "second key"
            batch = 101
            td = TensorDict(
                {
                    key1: torch.randn(batch, 3),
                    key2: torch.randn(batch, 3),
                },
                [batch],
            )
            trainer._process_batch_hook(td)
            td_out = trainer._process_optim_batch_hook(td)
            if prioritized:
                td_out.set(replay_buffer.priority_key, torch.rand(N))
            trainer._post_loss_hook(td_out)
            trainer.save_trainer(True)

            trainer2 = mocking_trainer()
            storage2, _ = make_storage()
            if prioritized:
                replay_buffer2 = TensorDictPrioritizedReplayBuffer(
                    S, 1.1, 0.9, storage=storage2
                )
            else:
                replay_buffer2 = TensorDictReplayBuffer(S, storage=storage2)
            N = 9
            rb_trainer2 = ReplayBufferTrainer(replay_buffer=replay_buffer2, batch_size=N)
            rb_trainer2.register(trainer2)
            trainer2._process_batch_hook(td.to_tensordict().zero_())
            trainer2.load_from_file(file)
            assert state_dict_has_been_called[0]
            if backend == "torch":
                assert load_state_dict_has_been_called[0]
            else:
                td1 = trainer.app_state["state"]["replay_buffer.replay_buffer._storage._storage"]
                td2 = trainer2.app_state["state"]["replay_buffer.replay_buffer._storage._storage"]
                assert (td1 == td2).all()

        ReplayBufferTrainer.state_dict = state_dict_fun
        ReplayBufferTrainer.load_state_dict = load_state_dict_fun


@pytest.mark.parametrize("logname", ["a", "b"])
@pytest.mark.parametrize("pbar", [True, False])
def test_log_reward(logname, pbar):
    trainer = mocking_trainer()
    trainer.collected_frames = 0

    log_reward = LogReward(logname, log_pbar=pbar)
    trainer.register_op("pre_steps_log", log_reward)
    td = TensorDict({"reward": torch.ones(3)}, [3])
    trainer._pre_steps_log_hook(td)
    if _has_tqdm and pbar:
        assert trainer._pbar_str[logname] == 1
    else:
        assert logname not in trainer._pbar_str
    assert trainer._log_dict[logname][-1] == 1


class TestRewardNorm:
    def test_reward_norm(self):
        torch.manual_seed(0)
        trainer = mocking_trainer()

        reward_normalizer = RewardNormalizer()
        reward_normalizer.register(trainer)

        batch = 10
        reward = torch.randn(batch, 1)
        td = TensorDict({"reward": reward.clone()}, [batch])
        td_out = trainer._process_batch_hook(td)
        assert (td_out.get("reward") == reward).all()
        assert not reward_normalizer._normalize_has_been_called

        td_norm = trainer._process_optim_batch_hook(td)
        assert reward_normalizer._normalize_has_been_called
        torch.testing.assert_close(td_norm.get("reward").mean(), torch.zeros([]))
        torch.testing.assert_close(td_norm.get("reward").std(), torch.ones([]))

    def test_reward_norm_state_dict(self):
        torch.manual_seed(0)
        trainer = mocking_trainer()

        reward_normalizer = RewardNormalizer()
        reward_normalizer.register(trainer)

        batch = 10
        reward = torch.randn(batch, 1)
        td = TensorDict({"reward": reward.clone()}, [batch])
        trainer._process_batch_hook(td)
        trainer._process_optim_batch_hook(td)
        state_dict = trainer.state_dict()

        trainer2 = mocking_trainer()

        reward_normalizer2 = RewardNormalizer()
        reward_normalizer2.register(trainer2)
        trainer2.load_state_dict(state_dict)
        for key, item in reward_normalizer._reward_stats.items():
            assert item == reward_normalizer2._reward_stats[key]


def test_masking():
    torch.manual_seed(0)
    trainer = mocking_trainer()

    trainer.register_op("batch_process", mask_batch)
    batch = 10
    td = TensorDict(
        {
            "mask": torch.zeros(batch, dtype=torch.bool).bernoulli_(),
            "tensor": torch.randn(batch, 51),
        },
        [batch],
    )
    td_out = trainer._process_batch_hook(td)
    assert td_out.shape[0] == td.get("mask").sum()
    assert (td["tensor"][td["mask"].squeeze(-1)] == td_out["tensor"]).all()


class TestSubSampler:
    def test_subsampler(self):
        torch.manual_seed(0)
        trainer = mocking_trainer()

        batch_size = 10
        sub_traj_len = 5

        key1 = "key1"
        key2 = "key2"

        trainer.register_op(
            "process_optim_batch",
            BatchSubSampler(batch_size=batch_size, sub_traj_len=sub_traj_len),
        )

        td = TensorDict(
            {
                key1: torch.stack([torch.arange(0, 10), torch.arange(10, 20)], 0),
                key2: torch.stack([torch.arange(0, 10), torch.arange(10, 20)], 0),
            },
            [2, 10],
        )

        td_out = trainer._process_optim_batch_hook(td)
        assert td_out.shape == torch.Size([batch_size // sub_traj_len, sub_traj_len])
        assert (td_out.get(key1) == td_out.get(key2)).all()

    def test_subsampler_state_dict(self):
        trainer = mocking_trainer()

        batch_size = 10
        sub_traj_len = 5

        key1 = "key1"
        key2 = "key2"

        trainer.register_op(
            "process_optim_batch",
            BatchSubSampler(batch_size=batch_size, sub_traj_len=sub_traj_len),
        )

        td = TensorDict(
            {
                key1: torch.stack([torch.arange(0, 10), torch.arange(10, 20)], 0),
                key2: torch.stack([torch.arange(0, 10), torch.arange(10, 20)], 0),
            },
            [2, 10],
        )

        torch.manual_seed(0)
        td0 = trainer._process_optim_batch_hook(td)
        trainer2 = mocking_trainer()
        trainer2.register_op(
            "process_optim_batch",
            BatchSubSampler(batch_size=batch_size, sub_traj_len=sub_traj_len),
        )
        trainer2.load_state_dict(trainer.state_dict())
        torch.manual_seed(0)
        td1 = trainer2._process_optim_batch_hook(td)
        assert (td0 == td1).all()


@pytest.mark.skipif(not _has_gym, reason="No gym library")
@pytest.mark.skipif(not _has_tb, reason="No tensorboard library")
def test_recorder():
    with tempfile.TemporaryDirectory() as folder:
        print(folder)
        logger = TensorboardLogger(exp_name=folder)
        args = Namespace()
        args.env_name = "ALE/Pong-v5"
        args.env_task = ""
        args.grayscale = True
        args.env_library = "gym"
        args.frame_skip = 1
        args.center_crop = []
        args.from_pixels = True
        args.vecnorm = False
        args.norm_rewards = False
        args.reward_scaling = 1.0
        args.reward_loc = 0.0
        args.noops = 0
        args.record_frames = 24 // args.frame_skip
        args.record_interval = 2
        args.catframes = 4
        args.image_size = 84
        args.collector_devices = ["cpu"]

        N = 8

        recorder = transformed_env_constructor(
            args,
            video_tag="tmp",
            norm_obs_only=True,
            stats={"loc": 0, "scale": 1},
            logger=logger,
        )()

        recorder = Recorder(
            record_frames=args.record_frames,
            frame_skip=args.frame_skip,
            policy_exploration=None,
            recorder=recorder,
            record_interval=args.record_interval,
        )

        for _ in range(N):
            recorder(None)

        for (_, _, filenames) in walk(folder):
            filename = filenames[0]
            break
        for _ in range(3):
            ea = event_accumulator.EventAccumulator(
                path.join(folder, filename),
                size_guidance={
                    event_accumulator.IMAGES: 0,
                },
            )
            ea.Reload()
            print(ea.Tags())
            img = ea.Images("tmp_ALE/Pong-v5_video")
            try:
                assert len(img) == N // args.record_interval
                break
            except AssertionError:
                sleep(0.1)


def test_updateweights():
    torch.manual_seed(0)
    trainer = mocking_trainer()

    T = 5
    update_weights = UpdateWeights(trainer.collector, T)
    trainer.register_op("post_steps", update_weights)
    for t in range(T):
        trainer._post_steps_hook()
        assert trainer.collector.called_update_policy_weights_ is (t == T - 1)
    assert trainer.collector.called_update_policy_weights_


def test_countframes():
    torch.manual_seed(0)
    trainer = mocking_trainer()

    frame_skip = 3
    batch = 10
    count_frames = CountFramesLog(frame_skip=frame_skip)
    trainer.register_op("pre_steps_log", count_frames)
    td = TensorDict(
        {"mask": torch.zeros(batch, dtype=torch.bool).bernoulli_()}, [batch]
    )
    trainer._pre_steps_log_hook(td)
    assert count_frames.frame_count == td.get("mask").sum() * frame_skip


if __name__ == "__main__":
    args, unknown = argparse.ArgumentParser().parse_known_args()
    pytest.main([__file__, "--capture", "no", "--exitfirst"] + unknown)
