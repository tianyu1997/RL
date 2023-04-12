# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
"""PPO Example.

This is a self-contained example of a PPO training script.

It works across Gym and DM-control over a variety of tasks.

Both state and pixel-based environments are supported.

The helper functions are coded in the utils.py associated with this script.
"""
import tqdm
import hydra
import torch
from torch.optim.lr_scheduler import LinearLR
from torchrl.trainers.helpers.envs import correct_for_frame_skip


from utils import (
    get_stats,
    make_collector,
    make_ppo_model,
    make_policy,  # needed ???
    make_logger,
    make_loss,
    make_optim,
    make_recorder,
    make_data_buffer,
    make_test_env,
)


@hydra.main(config_path=".", config_name="config")
def main(cfg: "DictConfig"):  # noqa: F821

    # cfg = correct_for_frame_skip(cfg)
    model_device = cfg.optim.device

    actor, critic = make_ppo_model(cfg)
    actor = actor.to(model_device)
    critic = critic.to(model_device)

    collector = make_collector(cfg, policy=actor)
    data_buffer = make_data_buffer(cfg)
    loss_module, adv_module = make_loss(cfg.loss, actor_network=actor, value_network=critic)
    optim = make_optim(cfg.optim, actor_network=actor, value_network=critic)

    batch_size = cfg.collector.total_frames * cfg.env.num_envs
    num_mini_batches = batch_size // cfg.loss.mini_batch_size
    total_network_updates = (cfg.collector.total_frames // batch_size) * cfg.loss.ppo_epochs * num_mini_batches
    scheduler = LinearLR(optim, total_iters=total_network_updates, start_factor=1.0, end_factor=0.1)

    logger = make_logger(cfg.logger)
    recorder = make_recorder(cfg, logger, actor)
    test_env = make_test_env(cfg.env)

    record_interval = cfg.recorder.interval

    pbar = tqdm.tqdm(total=cfg.collector.total_frames)
    collected_frames = 0

    # Main loop
    r0 = None
    l0 = None
    for data in collector:

        frames_in_batch = data.numel()
        collected_frames += frames_in_batch
        pbar.update(data.numel())
        data_view = data.reshape(-1)

        # Compute GAE
        with torch.no_grad():
            data_view = adv_module(data_view)

        # Update the data buffer
        data_buffer.extend(data_view)

        # Logging
        episode_rewards = data["next"]["episode_reward"][data["next"]["done"]]
        if len(episode_rewards) > 0:
            logger.log_scalar("reward_training", episode_rewards.mean().item(), collected_frames)

        for epoch in range(cfg.loss.ppo_epochs):
            for _ in range(frames_in_batch // cfg.loss.mini_batch_size):

                # Get a data batch
                batch = data_buffer.sample().to(model_device)

                # Forward pass PPO loss
                loss = loss_module(batch)
                loss_sum = loss["loss_critic"] + loss["loss_objective"] + loss["loss_entropy"]

                # Backward pass
                loss_sum.backward()
                grad_norm = torch.nn.utils.clip_grad_norm_(list(actor.parameters()) + list(critic.parameters()), max_norm=0.5)
                optim.step()
                scheduler.step()
                optim.zero_grad()

                # Logging
                if r0 is None:
                    r0 = data["reward"].mean().item()
                if l0 is None:
                    l0 = loss_sum.item()
                for key, value in loss.items():
                    logger.log_scalar(key, value.item(), collected_frames)
                pbar.set_description(
                    f"loss: {loss_sum.item(): 4.4f} (init: {l0: 4.4f}), reward: {data['reward'].mean(): 4.4f} (init={r0: 4.4f})"
                )
                logger.log_scalar("grad_norm", grad_norm.item(), collected_frames)

        collector.update_policy_weights_()

        # Test current policy
        if (
            collected_frames - frames_in_batch
        ) // record_interval < collected_frames // record_interval:

            with torch.no_grad():
                test_env.eval()
                actor.eval()
                td_record = test_env.rollout(
                    policy=actor,
                    max_steps=10_000_000,
                    auto_reset=True,
                    auto_cast_to_device=True,
                    break_when_any_done=True,
                ).clone()
                logger.log_scalar("reward_testing", td_record["reward"].sum().item(), collected_frames)
                logger.log_scalar("step_count_testing", td_record["next"]["step_count"][0][-1].item(), collected_frames)
                actor.train()


if __name__ == "__main__":
    main()
