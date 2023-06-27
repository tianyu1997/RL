from typing import Callable, Dict, Iterator, List, OrderedDict, Union, Optional

import copy
import torch
import itertools
from tensordict import TensorDict
from tensordict.tensordict import TensorDictBase
from torch import nn
import torch
from tensordict import TensorDict


def set_grad(p):
    p.grad = torch.zeros_like(p.data)
    return p


class GradientWorker:
    """Worker that computes gradients for a given objective."""

    def __init__(
        self,
        objective,
        device: torch.device = "cpu",
    ):

        self.device = device
        self.objective = objective

        with torch.no_grad():
            self.weights = TensorDict(dict(self.objective.named_parameters()), [])
            self.weights.apply(set_grad)
            self.weights.lock_()

    def update_policy_weights_(
            self,
            weights,
    ) -> None:

        # self.weights = self.weights.detach()  # Seems required
        # RuntimeError: a leaf Variable that requires grad is being used in an in-place operation.
        self.weights.update_(weights)
        self.weights.apply(set_grad)

    def compute_gradients(self, mini_batch):
        """Computes next gradient in each iteration."""

        mini_batch = mini_batch.to("cuda")

        # Compute loss
        loss = self.objective(mini_batch)
        loss_sum = loss["loss_critic"] + loss["loss_objective"] + loss["loss_entropy"]

        # Backprop loss
        print("Computing remote gradients...")
        loss_sum.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(self.objective.parameters(), max_norm=0.5)

        # Get gradients
        grads = self.weights.apply(lambda p: p.grad)

        return grads
