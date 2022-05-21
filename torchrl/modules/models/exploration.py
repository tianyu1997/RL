# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import math
from typing import Optional, Sequence, Union

import torch
from torch import nn, distributions as d
from torch.nn.modules.lazy import LazyModuleMixin
from torch.nn.parameter import UninitializedBuffer, UninitializedParameter

__all__ = ["NoisyLinear", "NoisyLazyLinear", "reset_noise"]

from torchrl.data.utils import DEVICE_TYPING
from torchrl.envs.utils import exploration_mode
from torchrl.modules.distributions.utils import _cast_transform_device
from torchrl.modules.utils import inv_softplus


class NoisyLinear(nn.Linear):
    """
    Noisy Linear Layer, as presented in "Noisy Networks for Exploration", https://arxiv.org/abs/1706.10295v3

    A Noisy Linear Layer is a linear layer with parametric noise added to the weights. This induced stochasticity can
    be used in RL networks for the agent's policy to aid efficient exploration. The parameters of the noise are learned
    with gradient descent along with any other remaining network weights. Factorized Gaussian
    noise is the type of noise usually employed.


    Args:
        in_features (int): input features dimension
        out_features (int): out features dimension
        bias (bool): if True, a bias term will be added to the matrix multiplication: Ax + b.
            default: True
        device (str, int or torch.device, optional): device of the layer.
            default: "cpu"
        dtype (torch.dtype, optional): dtype of the parameters.
            default: None
        std_init (scalar): initial value of the Gaussian standard deviation before optimization.
            default: 1.0
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = True,
        device: Optional[DEVICE_TYPING] = None,
        dtype: Optional[torch.dtype] = None,
        std_init: float = 0.1,
    ):
        nn.Module.__init__(self)
        self.in_features = int(in_features)
        self.out_features = int(out_features)
        self.std_init = std_init

        self.weight_mu = nn.Parameter(
            torch.empty(
                out_features,
                in_features,
                device=device,
                dtype=dtype,
                requires_grad=True,
            )
        )
        self.weight_sigma = nn.Parameter(
            torch.empty(
                out_features,
                in_features,
                device=device,
                dtype=dtype,
                requires_grad=True,
            )
        )
        self.register_buffer(
            "weight_epsilon",
            torch.empty(out_features, in_features, device=device, dtype=dtype),
        )
        if bias:
            self.bias_mu = nn.Parameter(
                torch.empty(
                    out_features,
                    device=device,
                    dtype=dtype,
                    requires_grad=True,
                )
            )
            self.bias_sigma = nn.Parameter(
                torch.empty(
                    out_features,
                    device=device,
                    dtype=dtype,
                    requires_grad=True,
                )
            )
            self.register_buffer(
                "bias_epsilon",
                torch.empty(out_features, device=device, dtype=dtype),
            )
        else:
            self.bias_mu = None
        self.reset_parameters()
        self.reset_noise()

    def reset_parameters(self) -> None:
        mu_range = 1 / math.sqrt(self.in_features)
        self.weight_mu.data.uniform_(-mu_range, mu_range)
        self.weight_sigma.data.fill_(self.std_init / math.sqrt(self.in_features))
        if self.bias_mu is not None:
            self.bias_mu.data.uniform_(-mu_range, mu_range)
            self.bias_sigma.data.fill_(self.std_init / math.sqrt(self.out_features))

    def reset_noise(self) -> None:
        epsilon_in = self._scale_noise(self.in_features)
        epsilon_out = self._scale_noise(self.out_features)
        self.weight_epsilon.copy_(epsilon_out.outer(epsilon_in))
        if self.bias_mu is not None:
            self.bias_epsilon.copy_(epsilon_out)

    def _scale_noise(self, size: Union[int, torch.Size, Sequence]) -> torch.Tensor:
        if isinstance(size, int):
            size = (size,)
        x = torch.randn(*size, device=self.weight_mu.device)
        return x.sign().mul_(x.abs().sqrt_())

    @property
    def weight(self) -> torch.Tensor:
        if self.training:
            return self.weight_mu + self.weight_sigma * self.weight_epsilon
        else:
            return self.weight_mu

    @property
    def bias(self) -> Optional[torch.Tensor]:
        if self.bias_mu is not None:
            if self.training:
                return self.bias_mu + self.bias_sigma * self.bias_epsilon
            else:
                return self.bias_mu
        else:
            return None


class NoisyLazyLinear(LazyModuleMixin, NoisyLinear):
    """
    Noisy Lazy Linear Layer.

    This class makes the Noisy Linear layer lazy, in that the in_feature argument does not need to be passed at
    initialization (but is inferred after the first call to the layer).

    For more context on noisy layers, see the NoisyLinear class.

    Args:
        out_features (int): out features dimension
        bias (bool): if True, a bias term will be added to the matrix multiplication: Ax + b.
            default: True
        device (str, int or torch.device, optional): device of the layer.
            default: "cpu"
        dtype (torch.dtype, optional): dtype of the parameters.
            default: None
        std_init (scalar): initial value of the Gaussian standard deviation before optimization.
            default: 1.0
    """

    def __init__(
        self,
        out_features: int,
        bias: bool = True,
        device: Optional[DEVICE_TYPING] = None,
        dtype: Optional[torch.dtype] = None,
        std_init: float = 0.1,
    ):
        super().__init__(0, 0, False)
        self.out_features = out_features
        self.std_init = std_init

        self.weight_mu = UninitializedParameter(device=device, dtype=dtype)
        self.weight_sigma = UninitializedParameter(device=device, dtype=dtype)
        self.register_buffer(
            "weight_epsilon", UninitializedBuffer(device=device, dtype=dtype)
        )
        if bias:
            self.bias_mu = UninitializedParameter(device=device, dtype=dtype)
            self.bias_sigma = UninitializedParameter(device=device, dtype=dtype)
            self.register_buffer(
                "bias_epsilon", UninitializedBuffer(device=device, dtype=dtype)
            )
        else:
            self.bias_mu = None
        self.reset_parameters()

    def reset_parameters(self) -> None:
        if not self.has_uninitialized_params() and self.in_features != 0:
            super().reset_parameters()

    def reset_noise(self) -> None:
        if not self.has_uninitialized_params() and self.in_features != 0:
            super().reset_noise()

    def initialize_parameters(self, input: torch.Tensor) -> None:
        if self.has_uninitialized_params():
            with torch.no_grad():
                self.in_features = input.shape[-1]
                self.weight_mu.materialize((self.out_features, self.in_features))
                self.weight_sigma.materialize((self.out_features, self.in_features))
                self.weight_epsilon.materialize((self.out_features, self.in_features))
                if self.bias_mu is not None:
                    self.bias_mu.materialize((self.out_features,))
                    self.bias_sigma.materialize((self.out_features,))
                    self.bias_epsilon.materialize((self.out_features,))
                self.reset_parameters()
                self.reset_noise()

    @property
    def weight(self) -> torch.Tensor:
        if not self.has_uninitialized_params() and self.in_features != 0:
            return super().weight

    @property
    def bias(self) -> torch.Tensor:
        if not self.has_uninitialized_params() and self.in_features != 0:
            return super().bias


def reset_noise(layer: nn.Module) -> None:
    if hasattr(layer, "reset_noise"):
        layer.reset_noise()


class gSDEModule(nn.Module):
    """A gSDE exploration wrapper as presented in "Smooth Exploration for
    Robotic Reinforcement Learning" by Antonin Raffin, Jens Kober,
    Freek Stulp (https://arxiv.org/abs/2005.05719)

    gSDEWrapper encapsulates nn.Module that outputs the average of a
    normal distribution and adds a state-dependent exploration noise to it.
    It outputs the mean, scale (standard deviation) of the normal
    distribution as well as the chosen action.

    For now, only vector states are considered, but the distribution can
    read other inputs (e.g. hidden states etc.)

    The noise input should be reset through a `torchrl.envs.transforms.gSDENoise`
    instance: each time the environment is reset, the gSDENoise will be erased
    and resampled inside this wrapper.
    Finally, a regular normal distribution should be used to sample the
    actions, the `ProbabilisticTensorDictModule` should be created
    in safe mode (in order for the action to be clipped in the desired
    range) and its input keys should include `"_eps_gSDE"` which is the
    default gSDE noise key:

        >>> actor = ProbabilisticActor(
        ...     TDModule(wrapped_module, in_keys=["observation"], out_keys=["loc", "scale", "action", "_eps_gSDE"]),
        ...     dist_param_keys=["loc", "scale"],
        ...     spec=spec,
        ...     distribution_class=IndependentNormal,  # or TanhNormal, etc.
        ...     safe=True)

    Args:
        policy_model (nn.Module): a model that reads observations and
            outputs a distribution average.
        action_dim (int): the dimension of the action.
        state_dim (int): the state dimension.
        sigma_init (float): the initial value of the standard deviation. The
            softplus non-linearity is used to map the log_sigma parameter to a
            positive value.
        scale_min (float, optional): min value of the scale.
        scale_max (float, optional): max value of the scale.
        transform (torch.distribution.Transform, optional): a transform to apply
            to the sampled action.

    Examples:
        >>> batch, state_dim, action_dim = 3, 7, 5
        >>> model = nn.Linear(state_dim, action_dim)
        >>> wrapped_model = gSDEWrapper(model, action_dim=action_dim,
        ...     state_dim=state_dim)
        >>> state = torch.randn(batch, state_dim)
        >>> eps_gSDE = torch.randn(batch, action_dim, state_dim)
        >>> # the module takes inputs (state, *additional_vectors, noise_param)
        >>> mu, sigma, action, noise = wrapped_model(state, eps_gSDE)
        >>> print(mu.shape, sigma.shape, action.shape)
        torch.Size([3, 5]) torch.Size([3, 5]) torch.Size([3, 5])
    """

    def __init__(
        self,
        action_dim: int,
        state_dim: int,
        sigma_init: float = None,
        scale_min: float = 0.1,
        scale_max: float = 10.0,
        learn_sigma: bool = True,
        transform: Optional[d.Transform] = None,
    ) -> None:
        super().__init__()
        self.action_dim = action_dim
        self.state_dim = state_dim
        self.scale_min = scale_min
        self.scale_max = scale_max
        self.transform = transform
        self.learn_sigma = learn_sigma
        if learn_sigma:
            if sigma_init is None:
                sigma_init = inv_softplus(math.sqrt((1.0 - scale_min) / state_dim))
            self.register_parameter(
                "log_sigma",
                nn.Parameter(torch.zeros((action_dim, state_dim), requires_grad=True)),
            )
        else:
            if sigma_init is None:
                sigma_init = math.sqrt((1.0 - scale_min) / state_dim)
            self.register_buffer(
                "_sigma",
                torch.full((action_dim, state_dim), sigma_init),
            )

        self.register_buffer("sigma_init", torch.tensor(sigma_init))

    @property
    def sigma(self):
        if self.learn_sigma:
            sigma = (
                torch.nn.functional.softplus(self.log_sigma + self.sigma_init)
                + self.scale_min
            )
            return sigma
        else:
            return self._sigma

    def forward(self, mu, state, _eps_gSDE):
        sigma = self.sigma.clamp_max(self.scale_max)
        _err_explo = f"gSDE behaviour for exploration mode {exploration_mode()} is not defined. Choose from 'random' or 'mode'."

        if state.shape[:-1] != mu.shape[:-1]:
            _err_msg = f"mu and state are expected to have matching batch size, got shapes {mu.shape} and {state.shape}"
            raise RuntimeError(_err_msg)
        if _eps_gSDE is not None and (
            _eps_gSDE.shape[: state.ndimension() - 1] != state.shape[:-1]
        ):
            _err_msg = f"noise and state are expected to have matching batch size, got shapes {_eps_gSDE.shape} and {state.shape}"
            raise RuntimeError(_err_msg)

        if _eps_gSDE is None and exploration_mode() == "mode":
            # noise is irrelevant in with no exploration
            _eps_gSDE = torch.zeros(
                *state.shape[:-1], *sigma.shape, device=sigma.device, dtype=sigma.dtype
            )
        elif (_eps_gSDE is None and exploration_mode() == "random") or (
            _eps_gSDE is not None
            and _eps_gSDE.numel() == math.prod(state.shape[:-1])
            and (_eps_gSDE == 0).all()
        ):
            _eps_gSDE = torch.randn(
                *state.shape[:-1], *sigma.shape, device=sigma.device, dtype=sigma.dtype
            )
        elif _eps_gSDE is None:
            raise RuntimeError(_err_explo)

        gSDE_noise = sigma * _eps_gSDE
        eps = (gSDE_noise @ state.unsqueeze(-1)).squeeze(-1)

        if exploration_mode() in ("random",):
            action = mu + eps
        elif exploration_mode() in ("mode",):
            action = mu
        else:
            raise RuntimeError(_err_explo)

        sigma = (sigma * state.unsqueeze(-2)).pow(2).sum(-1).clamp_min(1e-5).sqrt()
        if not torch.isfinite(sigma).all():
            print("inf sigma")

        if self.transform is not None:
            action = self.transform(action)
        return mu, sigma, action, _eps_gSDE

    def to(self, device_or_dtype: Union[torch.dtype, DEVICE_TYPING]):
        if isinstance(device_or_dtype, DEVICE_TYPING):
            self.transform = _cast_transform_device(self.transform, device_or_dtype)
        return self.to(device_or_dtype)


class LazygSDEModule(LazyModuleMixin, gSDEModule):
    cls_to_become = gSDEModule
    log_sigma: UninitializedParameter
    _sigma: UninitializedBuffer
    sigma_init: UninitializedBuffer

    def __init__(
        self,
        sigma_init: float = None,
        scale_min: float = 0.1,
        scale_max: float = 10.0,
        learn_sigma: bool = True,
        transform: Optional[d.Transform] = None,
    ) -> None:
        factory_kwargs = {
            "device": torch.device("cpu"),
            "dtype": torch.get_default_dtype(),
        }
        super().__init__(
            0,
            0,
            sigma_init=0.0,
            scale_min=scale_min,
            scale_max=scale_max,
            learn_sigma=learn_sigma,
            transform=transform,
        )
        self._sigma_init = sigma_init
        if learn_sigma:
            self.log_sigma = UninitializedParameter(**factory_kwargs)
        else:
            self._sigma = UninitializedBuffer(**factory_kwargs)

    def reset_parameters(self) -> None:
        pass

    def initialize_parameters(
        self, mu: torch.Tensor, state: torch.Tensor, _eps_gSDE: torch.Tensor
    ) -> None:
        if self.has_uninitialized_params():
            action_dim = mu.shape[-1]
            state_dim = state.shape[-1]
            with torch.no_grad():
                if self._sigma_init is None:
                    if state.ndimension() > 2:
                        state_flatten = state.flatten(0, -2)
                    else:
                        state_flatten = state
                    state_flatten_var = state_flatten.var(dim=0)
                if self.learn_sigma:
                    if self._sigma_init is None:
                        self.sigma_init.data += inv_softplus(
                            ((state_flatten_var - self.scale_min) / state_dim).sqrt()
                        )
                    else:
                        self.sigma_init.data += inv_softplus(self._sigma_init)

                    self.log_sigma.materialize((action_dim, state_dim))
                    self.log_sigma.data.fill_(self.sigma_init)

                else:
                    self._sigma.materialize((action_dim, state_dim))
                    if self._sigma_init is None:
                        self.sigma_init.data += (
                            (state_flatten_var - self.scale_min) / state_dim
                        ).sqrt()
                    else:
                        self.sigma_init.data += self._sigma_init
                    self._sigma.data.fill_(self.sigma_init)
