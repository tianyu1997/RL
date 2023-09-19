# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
This script reproduces the IMPALA Algorithm
results from Espeholt et al. 2018 for the on Atari Environments.
"""
import hydra


@hydra.main(config_path=".", config_name="config", version_base="1.1")
def main(cfg: "DictConfig"):  # noqa: F821

    import time

    import numpy as np
    import torch.optim
    import tqdm

    from tensordict import TensorDict
    from torchrl.collectors import MultiaSyncDataCollector
    from torchrl.collectors.distributed import RPCDataCollector
    from torchrl.data import LazyMemmapStorage, TensorDictReplayBuffer
    from torchrl.data.replay_buffers.samplers import SamplerWithoutReplacement
    from torchrl.envs import ExplorationType, set_exploration_type
    from torchrl.objectives import A2CLoss
    from torchrl.record.loggers import generate_exp_name, get_logger
    from torchrl.objectives.value.vtrace import VTrace
    from utils import make_parallel_env, make_ppo_models, eval_model

    device = "cpu" if not torch.cuda.is_available() else "cuda"

    # Correct for frame_skip
    frame_skip = 4
    total_frames = cfg.collector.total_frames // frame_skip
    frames_per_batch = cfg.collector.frames_per_batch // frame_skip
    mini_batch_size = cfg.loss.mini_batch_size // frame_skip
    test_interval = cfg.logger.test_interval // frame_skip

    # Create models (check utils.py)
    actor, critic, critic_head = make_ppo_models(cfg.env.env_name)
    actor, critic, critic_head = (
        actor.to(device),
        critic.to(device),
        critic_head.to(device),
    )

    # Create collector
    # collector = RPCDataCollector(
    #     create_env_fn=[make_parallel_env(cfg.env.env_name, device)] * 2,
    #     policy=actor,
    #     frames_per_batch=frames_per_batch,
    #     total_frames=total_frames,
    #     storing_device="cpu",
    #     max_frames_per_traj=-1,
    #     sync=False,
    # )
    collector = MultiaSyncDataCollector(
        create_env_fn=[make_parallel_env(cfg.env.env_name, device)] * cfg.collector.num_workers,
        policy=actor,
        frames_per_batch=frames_per_batch,
        total_frames=total_frames,
        device=device,
        storing_device=device,
        max_frames_per_traj=-1,
    )

    # Create data buffer
    sampler = SamplerWithoutReplacement()
    data_buffer = TensorDictReplayBuffer(
        storage=LazyMemmapStorage(frames_per_batch),
        sampler=sampler,
        batch_size=mini_batch_size,
    )

    # Create loss and adv modules
    vtrace_module = VTrace(
        gamma=cfg.loss.gamma,
        value_network=critic,
        actor_network=actor,
        average_adv=True,
    )
    loss_module = A2CLoss(
        actor=actor,
        critic=critic,
        loss_critic_type=cfg.loss.loss_critic_type,
        entropy_coef=cfg.loss.entropy_coef,
        critic_coef=cfg.loss.critic_coef,
    )

    # Create optimizer
    optim_actor = torch.optim.Adam(
        actor.parameters(),
        lr=cfg.optim.lr,
        weight_decay=cfg.optim.weight_decay,
        eps=cfg.optim.eps,
    )
    optim_critic = torch.optim.Adam(
        critic.parameters(),
        lr=cfg.optim.lr,
        weight_decay=cfg.optim.weight_decay,
        eps=cfg.optim.eps,
    )

    # Create logger
    logger = None
    if cfg.logger.backend:
        exp_name = generate_exp_name("IMPALA", f"{cfg.logger.exp_name}_{cfg.env.env_name}")
        logger = get_logger(cfg.logger.backend, logger_name="impala", experiment_name=exp_name)

    # Create test environment
    test_env = make_parallel_env(cfg.env.env_name, device, is_test=True)
    test_env.eval()

    # Main loop
    collected_frames = 0
    num_network_updates = 0
    start_time = time.time()
    pbar = tqdm.tqdm(total=total_frames)
    num_mini_batches = frames_per_batch // mini_batch_size
    total_network_updates = (total_frames // frames_per_batch) * num_mini_batches

    sampling_start = time.time()
    for data in collector:

        log_info = {}
        sampling_time = time.time() - sampling_start
        frames_in_batch = data.numel()
        collected_frames += frames_in_batch * frame_skip
        pbar.update(data.numel())

        # Get train reward
        episode_rewards = data["next", "episode_reward"][data["next", "done"]]
        if len(episode_rewards) > 0:
            log_info.update({"train/reward": episode_rewards.mean().item()})

        # Apply episodic end of life
        data["done"].copy_(data["end_of_life"])
        data["next", "done"].copy_(data["next", "end_of_life"])

        losses = TensorDict({}, batch_size=[num_mini_batches])
        training_start = time.time()

        # Compute VTrace
        with torch.no_grad():
            data = vtrace_module(data)
        data_reshape = data.reshape(-1)

        # Update the data buffer
        data_buffer.extend(data_reshape)

        for i, batch in enumerate(data_buffer):

            # Linearly decrease the learning rate and clip epsilon
            alpha = 1 - (num_network_updates / total_network_updates)
            if cfg.optim.anneal_lr:
                for group in optim_actor.param_groups:
                    group["lr"] = cfg.optim.lr * alpha
                for group in optim_critic.param_groups:
                    group["lr"] = cfg.optim.lr * alpha
            num_network_updates += 1

            # Get a data batch
            batch = batch.to(device)

            # Forward pass A2C loss
            loss = loss_module(batch)
            losses[i] = loss.select(
                "loss_critic", "loss_entropy", "loss_objective"
            ).detach()
            loss_actor = loss["loss_objective"] + loss["loss_entropy"]
            loss_critic = loss["loss_critic"]

            # Backward pass
            loss_actor.backward()
            loss_critic.backward()
            torch.nn.utils.clip_grad_norm_(
                list(loss_module.parameters()), max_norm=cfg.optim.max_grad_norm
            )

            # Update the networks
            optim_actor.step()
            optim_critic.step()
            optim_actor.zero_grad()
            optim_critic.zero_grad()

        training_time = time.time() - training_start
        losses = losses.apply(lambda x: x.float().mean(), batch_size=[])
        for key, value in losses.items():
            log_info.update({f"train/{key}": value.item()})
        log_info.update(
            {
                "train/lr": alpha * cfg.optim.lr,
                "train/sampling_time": sampling_time,
                "train/training_time": training_time,
            }
        )

        # Test logging
        with torch.no_grad(), set_exploration_type(ExplorationType.MODE):
            if (collected_frames - frames_in_batch) // test_interval < (
                    collected_frames // test_interval
            ):
                actor.eval()
                eval_start = time.time()
                test_rewards = eval_model(
                    actor, test_env, num_episodes=cfg.logger.num_test_episodes
                )
                eval_time = time.time() - eval_start
                log_info.update(
                    {
                        "test/reward": test_rewards.mean(),
                        "test/eval_time": eval_time,
                    }
                )
                actor.train()

        if logger:
            for key, value in log_info.items():
                logger.log_scalar(key, value, collected_frames)

        collector.update_policy_weights_()
        sampling_start = time.time()

    end_time = time.time()
    execution_time = end_time - start_time
    print(f"Training took {execution_time:.2f} seconds to finish")


if __name__ == "__main__":
    main()
