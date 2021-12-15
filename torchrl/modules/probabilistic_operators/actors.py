import torch
from torch import nn, distributions as d

from torchrl.modules.distributions import Delta, Categorical
from torchrl.modules.distributions.discrete import rand_one_hot
from .common import ProbabilisticOperator, ProbabilisticOperatorWrapper
from ..models.models import DistributionalDQNnet

__all__ = ["Actor", "ActorCriticOperator", "QValueActor", "DistributionalQValueActor", ]


class Actor(ProbabilisticOperator):
    def __init__(
            self,
            action_spec,
            mapping_operator: nn.Module,
            distribution_class: d.Distribution = Delta,
            distribution_kwargs: dict = dict(),
            default_interaction_mode: str = "mode",
            _n_empirical_est=1000,
            safe=False,
            in_keys=None,
            out_keys=None,
            **kwargs,
    ):
        if in_keys is None:
            in_keys = ["observation"]
        if out_keys is None:
            out_keys = ["action"]

        super().__init__(
            action_spec,
            mapping_operator=mapping_operator,
            distribution_class=distribution_class,
            distribution_kwargs=distribution_kwargs,
            default_interaction_mode=default_interaction_mode,
            _n_empirical_est=_n_empirical_est,
            safe=safe,
            in_keys=in_keys,
            out_keys=out_keys,
            **kwargs,
        )

    def random_sample(self, out_shape):
        raise NotImplementedError


class QValueHook:
    def __init__(
            self, action_space, var_nums=None,
    ):
        self.action_space = action_space
        self.var_nums = var_nums
        self.fun_dict = {
            "one_hot": self._one_hot,
            "mult_one_hot": self._mult_one_hot,
            "binary": self._binary,
        }

    def __call__(self, net, observation, values: torch.Tensor):
        return self.fun_dict[self.action_space](values), values

    @staticmethod
    def _one_hot(value: torch.Tensor):
        out = (value == value.max(dim=-1, keepdim=True)[0]).to(torch.long)
        return out

    def _mult_one_hot(self, value: torch.Tensor, support):
        values = value.split(self.var_nums, dim=-1)
        return torch.cat([QValueHook._one_hot(_value, ) for _value in values], -1, )

    @staticmethod
    def _binary(value, support):
        raise NotImplementedError


class DistributionalQValueHook(QValueHook):
    def __init__(
            self, action_space, support, var_nums=None,
    ):
        self.action_space = action_space
        self.support = support
        self.var_nums = var_nums
        self.fun_dict = {
            "one_hot": self._one_hot,
            "mult_one_hot": self._mult_one_hot,
            "binary": self._binary,
        }

    def __call__(self, net, observation, values: torch.Tensor):
        return self.fun_dict[self.action_space](values, self.support), values

    def _support_expected(self, log_softmax_values: torch.Tensor, support: torch.Tensor):
        support = support.to(log_softmax_values.device)
        assert log_softmax_values.shape[-2] == support.shape[-1], (
            "Support length and number of atoms in mapping_operator output should match, "
            f"got self.support.shape={support.shape} and mapping_operator(...).shape={log_softmax_values.shape}"
        )
        assert (log_softmax_values <= 0).all(), (
            f"input to QValueHook must be log-softmax values (which are expected to be non-positive numbers). "
            f"got a maximum value of {log_softmax_values.max():4.4f}")
        return (log_softmax_values.exp() * support.unsqueeze(-1)).sum(-2)

    def _one_hot(self, value: torch.Tensor, support: torch.Tensor):
        assert isinstance(value, torch.Tensor), f"got value of type {value.__class__.__name__}"
        assert isinstance(support, torch.Tensor), f"got support of type {support.__class__.__name__}"
        value = self._support_expected(value, support)
        out = (value == value.max(dim=-1, keepdim=True)[0]).to(torch.long)
        return out

    def _mult_one_hot(self, value: torch.Tensor, support: torch.Tensor):
        values = value.split(self.var_nums, dim=-1)
        return torch.cat(
            [
                self._one_hot(_value, _support)
                for _value, _support in zip(values, support)
            ],
            -1,
        )

    @staticmethod
    def _binary(value, support):
        raise NotImplementedError


class QValueActor(Actor):

    def __init__(self, *args, action_space="one_hot", **kwargs):
        out_keys = [
            "action",
            "action_value",
        ]
        super().__init__(*args, out_keys=out_keys, **kwargs)
        self.action_space = action_space
        self.mapping_operator.register_forward_hook(QValueHook(self.action_space))
        assert self.distribution_class is Delta, (
            f"{self.__class__.__name__} expects a distribution_class Delta, "
            f"but got {self.distribution_class.__name__} instead."
        )

    def random_sample(self, out_shape):
        if self.action_space == "one_hot":
            values = torch.randn(out_shape, device=next(self.parameters()).device)
            out = rand_one_hot(values)
        else:
            raise NotImplementedError(
                f"{self.__class__.__name__}.random_sample is not implemented yet"
                f" for action_space of type {self.action_space}"
            )
        return out


class DistributionalQValueActor(QValueActor):
    def __init__(self, *args, support, action_space="one_hot", **kwargs):
        out_keys = [
            "action",
            "action_value",
        ]
        super(QValueActor, self).__init__(*args, out_keys=out_keys, **kwargs)
        self.action_space = action_space

        self.register_buffer('support', support)
        self.action_space = action_space
        if not isinstance(self.mapping_operator, DistributionalDQNnet):
            self.mapping_operator = DistributionalDQNnet(self.mapping_operator)
        self.mapping_operator.register_forward_hook(
            DistributionalQValueHook(self.action_space, self.support)
        )
        assert self.distribution_class is Delta, (
            f"{self.__class__.__name__} expects a distribution_class Delta, "
            f"but got {self.distribution_class.__name__} instead."
        )


class ActorCriticOperator(ProbabilisticOperator):

    def __init__(
            self,
            spec,
            in_keys,
            common_mapping_operator: nn.Module,
            policy_operator: nn.Module,
            value_operator: nn.Module,
            out_keys=None,
            policy_distribution_class: type = Categorical,
            policy_distribution_kwargs: dict = dict(),
            value_distribution_class: d.Distribution = Delta,
            value_distribution_kwargs: dict = dict(),
            policy_interaction_mode: str = "mode",  # mode, random, mean
            value_interaction_mode: str = "mode",  # mode, random, mean
            **kwargs,
    ):
        assert not out_keys, f"PolicyValueOperator out_keys are pre-defined and cannot be changed, got out_keys={out_keys}"
        value_out_keys = ["state_value"]
        policy_out_keys = ["action", "action_log_prob"]
        out_keys = policy_out_keys + value_out_keys
        super().__init__(
            spec=spec,
            mapping_operator=common_mapping_operator,
            in_keys=in_keys,
            out_keys=out_keys,
            **kwargs,
        )

        self.value_po = ProbabilisticOperator(
            spec,
            in_keys=["hidden_obs"],
            out_keys=value_out_keys,
            mapping_operator=value_operator,
            distribution_class=value_distribution_class,
            distribution_kwargs=value_distribution_kwargs,
            default_interaction_mode=value_interaction_mode,
            **kwargs,
        )
        self.policy_po = Actor(
            spec,
            in_keys=["hidden_obs"],
            out_keys=policy_out_keys,
            mapping_operator=policy_operator,
            distribution_class=policy_distribution_class,
            distribution_kwargs=policy_distribution_kwargs,
            default_interaction_mode=policy_interaction_mode,
            return_log_prob=True,
            **kwargs,
        )
        self.out_keys = out_keys

    def _get_mapping(self, tensor_dict):
        values = [tensor_dict.get(key) for key in self.in_keys]
        hidden_obs = self.mapping_operator(*values)
        tensor_dict.set("hidden_obs", hidden_obs)
        return tensor_dict

    def get_dist(self, tensor_dict):
        self._get_mapping(tensor_dict)
        value_dist, *value_tensors = self.value_po.get_dist(tensor_dict)
        policy_dist, *action_tensors = self.policy_po.get_dist(tensor_dict)
        return (policy_dist, value_dist, *action_tensors, *value_tensors)

    def forward(self, tensor_dict):
        self._get_mapping(tensor_dict)
        self.policy_po(tensor_dict)
        self.value_po(tensor_dict)
        return tensor_dict

    def get_policy_operator(self):
        return OperatorMaskWrapper(self, "policy_po")

    def get_value_operator(self):
        return OperatorMaskWrapper(self, "value_po")


class OperatorMaskWrapper(ProbabilisticOperatorWrapper):
    def __init__(self, parent_operator: ActorCriticOperator, target):
        super().__init__(getattr(parent_operator, target))
        self.target = target
        self.parent_operator = parent_operator
        self.in_keys = parent_operator.in_keys
        assert hasattr(
            parent_operator, target
        ), f"{target} of OperatorMaskWrapper not found in the operator {type(parent_operator)}"

    @property
    def target_operator(self):
        return getattr(self.parent_operator, self.target)

    def get_dist(self, tensor_dict):
        self.parent_operator._get_mapping(tensor_dict)
        dist, *tensors = self.target_operator.get_dist(tensor_dict)
        return (dist, *tensors)

    def named_parameters(
            self, prefix: str="", recurse: bool=True, exclude_common_operator=False
    ):
        assert recurse

        for n, p in self.target_operator.named_parameters(prefix=prefix):
            yield n, p
        if not exclude_common_operator:
            for n, p in self.parent_operator.mapping_operator.named_parameters(prefix=prefix):
                yield n, p