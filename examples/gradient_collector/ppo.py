# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
"""PPO Example.

This is a self-contained example of a PPO training script.

Both state and pixel-based environments are supported.

The helper functions are coded in the utils.py associated with this script.
"""
import hydra
from torchrl.gradient_collector import GradientCollector
from tensordict import TensorDict


@hydra.main(config_path=".", config_name="config")
def main(cfg: "DictConfig"):  # noqa: F821

    import torch
    from utils import (
        make_collector,
        make_data_buffer,
        make_logger,
        make_loss,
        make_optim,
        make_ppo_models,
        make_test_env,
    )

    # Correct for frame_skip
    cfg.collector.total_frames = cfg.collector.total_frames // cfg.env.frame_skip
    cfg.collector.frames_per_batch = (
        cfg.collector.frames_per_batch // cfg.env.frame_skip
    )
    cfg.loss.mini_batch_size = cfg.loss.mini_batch_size // cfg.env.frame_skip
    num_mini_batches = (cfg.collector.frames_per_batch // cfg.loss.mini_batch_size) * cfg.loss.ppo_epochs

    # Create local modules
    local_model_device = cfg.optim.device
    local_actor, local_critic = make_ppo_models(cfg)
    local_actor = local_actor.to(local_model_device)
    local_critic = local_critic.to(local_model_device)
    local_loss_module = make_loss(cfg.loss, actor_network=local_actor, value_network=local_critic)
    local_optim = make_optim(cfg.optim, actor_network=local_actor, value_network=local_critic)

    grad_worker = GradientCollector(
        configuration=cfg,
        make_actor_critic=make_ppo_models,
        make_collector=make_collector,
        make_objective=make_loss,
        make_buffer=make_data_buffer,
        updates_per_batch=num_mini_batches,
        device=cfg.optim.device,
    )

    logger = None
    if cfg.logger.backend:
        logger = make_logger(cfg.logger)
    test_env = make_test_env(cfg.env)
    record_interval = cfg.logger.log_interval
    frames_in_batch = cfg.collector.frames_per_batch
    collected_frames = 0

    params = TensorDict(dict(local_loss_module.named_parameters()), [])

    for remote_grads in grad_worker:

        params.apply(lambda x, y: setattr(x, 'grad', y), remote_grads)

        # Update local policy
        local_optim.step()
        print("optimisation step!")

        # Update grad collector policy
        objective_params = TensorDict(dict(local_loss_module.named_parameters()), [])
        grad_worker.update_policy_weights_(objective_params)

        # Update counter
        collected_frames += frames_in_batch

        # Test current policy
        if (
            logger is not None
            and (collected_frames - frames_in_batch) // record_interval
            < collected_frames // record_interval
        ):

            with torch.no_grad():
                test_env.eval()
                local_actor.eval()
                td_test = test_env.rollout(
                    policy=local_actor,
                    max_steps=10_000_000,
                    auto_reset=True,
                    auto_cast_to_device=True,
                    break_when_any_done=True,
                ).clone()
                logger.log_scalar(
                    "reward_testing",
                    td_test["next", "reward"].sum().item(),
                    collected_frames,
                )
                local_actor.train()
                del td_test

        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
