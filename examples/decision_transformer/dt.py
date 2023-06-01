# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
"""Decision Transformer Example.
This is a self-contained example of an offline Decision Transformer training script.
The helper functions are coded in the utils.py associated with this script.
"""

import hydra
import torch
import tqdm
from torchrl.envs.utils import ExplorationType, set_exploration_type

from utils import (
    make_dt_loss,
    make_dt_model,
    make_dt_optimizer,
    make_env,
    make_logger,
    make_offline_replay_buffer,
)


@hydra.main(config_path=".", config_name="dt_config")
def main(cfg: "DictConfig"):  # noqa: F821
    model_device = cfg.optim.device

    test_env = make_env(cfg.env)
    logger = make_logger(cfg.logger)
    offline_buffer = make_offline_replay_buffer(
        cfg.replay_buffer, cfg.env.reward_scaling
    )

    inference_actor, actor = make_dt_model(cfg)
    policy = actor.to(model_device)
    inference_policy = inference_actor.to(model_device)

    loss_module = make_dt_loss(actor)
    transformer_optim, scheduler = make_dt_optimizer(cfg.optim, policy, loss_module)

    pbar = tqdm.tqdm(total=cfg.optim.pretrain_gradient_steps)

    r0 = None
    l0 = None
    print(" ***Pretraining*** ")
    # Pretraining
    for i in range(cfg.optim.pretrain_gradient_steps):
        pbar.update(i)
        data = offline_buffer.sample()
        # loss
        loss_vals = loss_module(data)
        # backprop
        transformer_loss = loss_vals["loss"]

        transformer_optim.zero_grad()
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 0.25)
        transformer_loss.backward()
        transformer_optim.step()

        scheduler.step()

        # evaluation
        with set_exploration_type(ExplorationType.MEAN), torch.no_grad():
            if i % cfg.logger.pretrain_log_interval == 0:
                eval_td = test_env.rollout(
                    max_steps=cfg.logger.eval_steps,
                    policy=inference_policy,
                    auto_cast_to_device=True,
                )
        if r0 is None:
            r0 = eval_td["next", "reward"].sum(1).mean().item() / cfg.env.reward_scaling
        if l0 is None:
            l0 = transformer_loss.item()

        for key, value in loss_vals.items():
            logger.log_scalar(key, value.item(), i)
        eval_reward = (
            eval_td["next", "reward"].sum(1).mean().item() / cfg.env.reward_scaling
        )
        logger.log_scalar("evaluation reward", eval_reward, i)

        pbar.set_description(
            f"[Pre-Training] loss: {transformer_loss.item(): 4.4f} (init: {l0: 4.4f}), evaluation reward: {eval_reward: 4.4f} (init={r0: 4.4f})"
        )


if __name__ == "__main__":
    main()
