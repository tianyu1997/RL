# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import hydra


@hydra.main(config_path=".", config_name="config_atari", version_base="1.1")
def main(cfg: "DictConfig"):  # noqa: F821

    import time

    import numpy as np
    import torch.optim
    import tqdm

    from tensordict import TensorDict
    from torchrl.collectors import SyncDataCollector
    from torchrl.data import LazyMemmapStorage, TensorDictReplayBuffer
    from torchrl.data.replay_buffers.samplers import SamplerWithoutReplacement
    from torchrl.envs import ExplorationType, set_exploration_type
    from torchrl.objectives import A2CLoss
    from torchrl.objectives.value.advantages import GAE
    from torchrl.record.loggers import generate_exp_name, get_logger
    from utils_atari import make_parallel_env, make_ppo_models

    device = "cpu" if not torch.cuda.is_available() else "cuda"

    # Correct for frame_skip
    frame_skip = 4
    total_frames = cfg.collector.total_frames // frame_skip
    frames_per_batch = cfg.collector.frames_per_batch // frame_skip
    mini_batch_size = cfg.loss.mini_batch_size // frame_skip
    test_interval = cfg.logger.test_interval // frame_skip

    # Create models (check utils_atari.py)
    actor, critic, critic_head = make_ppo_models(cfg.env.env_name)
    actor, critic, critic_head = (
        actor.to(device),
        critic.to(device),
        critic_head.to(device),
    )

    # Create collector
    collector = SyncDataCollector(
        create_env_fn=make_parallel_env(cfg.env.env_name, cfg.env.num_envs, device),
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
    adv_module = GAE(
        gamma=cfg.loss.gamma,
        lmbda=cfg.loss.gae_lambda,
        value_network=critic,
        average_gae=True,
    )
    loss_module = A2CLoss(
        actor=actor,
        critic=critic,
        loss_critic_type=cfg.loss.loss_critic_type,
        entropy_coef=cfg.loss.entropy_coef,
        critic_coef=cfg.loss.critic_coef,
    )

    # Create optimizer
    optim = torch.optim.Adam(
        loss_module.parameters(),
        lr=cfg.optim.lr,
        weight_decay=cfg.optim.weight_decay,
        eps=cfg.optim.eps,
    )

    # Create logger
    logger = None
    if cfg.logger.backend:
        exp_name = generate_exp_name("A2C", f"{cfg.logger.exp_name}_{cfg.env.env_name}")
        logger = get_logger(
            cfg.logger.backend, logger_name="a2c", experiment_name=exp_name
        )

    # Create test environment
    test_env = make_parallel_env(cfg.env.env_name, 1, device, is_test=True)
    test_env.eval()

    # Main loop
    collected_frames = 0
    num_network_updates = 0
    start_time = time.time()
    pbar = tqdm.tqdm(total=total_frames)
    num_mini_batches = frames_per_batch // mini_batch_size
    total_network_updates = (total_frames // frames_per_batch) * num_mini_batches

    sampling_start = time.time()
    for i, data in enumerate(collector):

        sampling_time = time.time() - sampling_start
        frames_in_batch = data.numel()
        collected_frames += frames_in_batch * frame_skip
        pbar.update(data.numel())

        # Log training rewards and lengths
        episode_rewards = data["next", "episode_reward"][data["next", "done"]]
        if logger and len(episode_rewards) > 0:
            episode_length = data["next", "step_count"][data["next", "done"]]
            logger.log_scalar(
                "train/reward", episode_rewards.mean().item(), collected_frames
            )
            logger.log_scalar(
                "train/episode_length",
                episode_length.sum().item() / len(episode_length),
                collected_frames,
            )

        # Apply episodic end of life
        data["done"].copy_(data["end_of_life"])
        data["next", "done"].copy_(data["next", "end_of_life"])

        losses = TensorDict({}, batch_size=[num_mini_batches])
        training_start = time.time()

        # Compute GAE
        with torch.no_grad():
            data = adv_module(data)
        data_reshape = data.reshape(-1)

        # Update the data buffer
        data_buffer.extend(data_reshape)

        for k, batch in enumerate(data_buffer):

            # Linearly decrease the learning rate and clip epsilon
            alpha = 1 - (num_network_updates / total_network_updates)
            if cfg.optim.anneal_lr:
                for group in optim.param_groups:
                    group["lr"] = cfg.optim.lr * alpha
            num_network_updates += 1

            # Get a data batch
            batch = batch.to(device)

            # Forward pass A2C loss
            loss = loss_module(batch)
            losses[k] = loss.select(
                "loss_critic", "loss_entropy", "loss_objective"
            ).detach()
            loss_sum = (
                loss["loss_critic"] + loss["loss_objective"] + loss["loss_entropy"]
            )

            # Backward pass
            loss_sum.backward()
            torch.nn.utils.clip_grad_norm_(
                list(loss_module.parameters()), max_norm=cfg.optim.max_grad_norm
            )

            # Update the networks
            optim.step()
            optim.zero_grad()

        # Log training losses and times
        training_time = time.time() - training_start
        losses = losses.apply(lambda x: x.float().mean(), batch_size=[])
        if logger:
            for key, value in losses.items():
                logger.log_scalar("train/" + key, value.item(), collected_frames)
            logger.log_scalar("train/lr", alpha * cfg.optim.lr, collected_frames)
            logger.log_scalar("train/sampling_time", sampling_time, collected_frames)
            logger.log_scalar("train/training_time", training_time, collected_frames)

        # Test logging
        with torch.no_grad(), set_exploration_type(ExplorationType.MODE):
            if ((i - 1) * frames_in_batch * frame_skip) // test_interval < (
                i * frames_in_batch * frame_skip
            ) // test_interval and logger:
                eval_start = time.time()
                actor.eval()
                test_rewards = []
                for _ in range(cfg.logger.num_test_episodes):
                    td_test = test_env.rollout(
                        policy=actor,
                        auto_reset=True,
                        auto_cast_to_device=True,
                        break_when_any_done=True,
                        max_steps=10_000_000,
                    )
                    reward = td_test["next", "episode_reward"][td_test["next", "done"]]
                    test_rewards = np.append(test_rewards, reward.cpu().numpy())
                    del td_test
                eval_time = time.time() - eval_start
                logger.log_scalar("eval/time", eval_time, collected_frames)
                logger.log_scalar("eval/reward", test_rewards.mean(), collected_frames)
                actor.train()

        collector.update_policy_weights_()
        sampling_start = time.time()

    end_time = time.time()
    execution_time = end_time - start_time
    print(f"Training took {execution_time:.2f} seconds to finish")


if __name__ == "__main__":
    main()
