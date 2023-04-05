# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import Optional, Sequence, Union

import torch
import torch.distributions as D

__all__ = [
    "OneHotCategorical",
    "MaskedCategorical",
]


def _treat_categorical_params(
    params: Optional[torch.Tensor] = None,
) -> Optional[torch.Tensor]:
    if params is None:
        return None
    if params.shape[-1] == 1:
        params = params[..., 0]
    return params


def rand_one_hot(values: torch.Tensor, do_softmax: bool = True) -> torch.Tensor:
    if do_softmax:
        values = values.softmax(-1)
    out = values.cumsum(-1) > torch.rand_like(values[..., :1])
    out = (out.cumsum(-1) == 1).to(torch.long)
    return out


class OneHotCategorical(D.Categorical):
    """One-hot categorical distribution.

    This class behaves excacly as torch.distributions.Categorical except that it reads and produces one-hot encodings
    of the discrete tensors.

    Args:
        logits (torch.Tensor): event log probabilities (unnormalized)
        probs (torch.Tensor): event probabilities

    Examples:
        >>> torch.manual_seed(0)
        >>> logits = torch.randn(4)
        >>> dist = OneHotCategorical(logits=logits)
        >>> print(dist.rsample((3,)))
        tensor([[1., 0., 0., 0.],
                [0., 0., 0., 1.],
                [1., 0., 0., 0.]])

    """

    num_params: int = 1

    def __init__(
        self,
        logits: Optional[torch.Tensor] = None,
        probs: Optional[torch.Tensor] = None,
        **kwargs,
    ) -> None:
        logits = _treat_categorical_params(logits)
        probs = _treat_categorical_params(probs)
        super().__init__(probs=probs, logits=logits, **kwargs)

    def log_prob(self, value: torch.Tensor) -> torch.Tensor:
        return super().log_prob(value.argmax(dim=-1))

    @property
    def mode(self) -> torch.Tensor:
        if hasattr(self, "logits"):
            return (self.logits == self.logits.max(-1, True)[0]).to(torch.long)
        else:
            return (self.probs == self.probs.max(-1, True)[0]).to(torch.long)

    def sample(
        self, sample_shape: Optional[Union[torch.Size, Sequence]] = None
    ) -> torch.Tensor:
        if sample_shape is None:
            sample_shape = torch.Size([])
        out = super().sample(sample_shape=sample_shape)
        out = torch.nn.functional.one_hot(out, self.logits.shape[-1]).to(torch.long)
        return out

    def rsample(self, sample_shape: Union[torch.Size, Sequence] = None) -> torch.Tensor:
        if sample_shape is None:
            sample_shape = torch.Size([])
        if hasattr(self, "logits") and self.logits is not None:
            logits = self.logits
            probs = None
        else:
            logits = None
            probs = self.probs
        d = D.relaxed_categorical.RelaxedOneHotCategorical(
            1.0, probs=probs, logits=logits
        )
        out = d.rsample(sample_shape)
        out.data.copy_((out == out.max(-1)[0].unsqueeze(-1)).to(out.dtype))
        return out


class MaskedCategorical(D.Categorical):
    """MaskedCategorical distribution.

    Reference:
    https://www.tensorflow.org/agents/api_docs/python/tf_agents/distributions/masked/MaskedCategorical

    Args:
        logits (torch.Tensor): event log probabilities (unnormalized)
        probs (torch.Tensor): event probabilities. If provided, the probabilities
            corresponding to to masked items will be zeroed and the probability
            re-normalized along its last dimension.
        mask (torch.Tensor): A boolean mask of the same shape as ``logits``/``probs``
            where ``False`` entries are the ones to be masked. Alternatively,
            if ``sparse_mask`` is True, it represents the list of valid indices
            in the distribution.
        neg_inf (float, optional): TODO
        sparse_mask: ``True`` when we only pass indices of True values in the mask
            tensor.
        padding_value: The padding value in the then mask tensor when
            sparse_mask == True, the padding_value will be ignored.

        >>> torch.manual_seed(0)
        >>> logits = torch.randn(4) / 100  # almost equal probabilities
        >>> mask = torch.tensor([True, False, True, True])
        >>> dist = MaskedCategorical(logits=logits, mask=mask)
        >>> sample = dist.sample((10,))
        >>> print(sample)  # no `1` in the sample
        tensor([2, 3, 0, 2, 2, 0, 2, 0, 2, 2])
        >>> print(dist.log_prob(sample))
        tensor([-1.1203, -1.0928, -1.0831, -1.1203, -1.1203, -1.0831, -1.1203, -1.0831,
                -1.1203, -1.1203])
        >>> print(dist.log_prob(torch.ones_like(sample)))
        tensor([-inf, -inf, -inf, -inf, -inf, -inf, -inf, -inf, -inf, -inf])
        >>> # with probabilities
        >>> prob = torch.ones(10)
        >>> prob = prob / prob.sum()
        >>> mask = torch.tensor([False] + 9 * [True])  # first outcome is masked
        >>> dist = MaskedCategorical(probs=prob, mask=mask)
        >>> print(dist.log_prob(torch.arange(10)))
        tensor([   -inf, -2.1972, -2.1972, -2.1972, -2.1972, -2.1972, -2.1972, -2.1972,
                -2.1972, -2.1972])
    """

    def __init__(
        self,
        probs: Optional[torch.Tensor] = None,
        logits: Optional[torch.Tensor] = None,
        mask: Optional[torch.Tensor] = None,
        neg_inf: float = float("-inf"),
        sparse_mask: bool = False,
        padding_value: Optional[int] = None,
    ) -> None:
        if (probs is None) == (logits is None):
            raise ValueError(
                "Either `probs` or `logits` must be specified, but not both.")

        if logits is None:
            logits = self._mask_probs(probs, mask, sparse_mask,
                                      padding_value).log()
        else:
            logits = self._mask_logits(logits, mask, neg_inf, sparse_mask,
                                       padding_value)

        self._mask = mask
        self._sparse_mask = (mask is not None) and sparse_mask
        self._neg_inf = neg_inf
        self._padding_value = padding_value
        super().__init__(logits=logits)

    def sample(
        self,
        sample_shape: Optional[Union[torch.Size, Sequence[int]]] = None
    ) -> torch.Tensor:
        if sample_shape is None:
            sample_shape = torch.Size()

        ret = super().sample(sample_shape)
        if not self._sparse_mask:
            return ret

        size = ret.size()
        # Python 3.7 doesn't support math.prod
        # outer_dim = prod(sample_shape)
        # inner_dim = prod(self._mask.size()[:-1])
        outer_dim = torch.empty(sample_shape, device="meta").numel()
        inner_dim = self._mask.numel() // self._mask.size(-1)
        idx_3d = self._mask.expand(outer_dim, inner_dim, -1)
        ret = idx_3d.gather(dim=-1, index=ret.view(outer_dim, inner_dim, 1))
        return ret.view(size)

    # TODO: Improve performance here.
    def log_prob(self, value: torch.Tensor) -> torch.Tensor:
        if not self._sparse_mask:
            return super().log_prob(value)

        idx_3d = self._mask.view(1, -1, self._num_events)
        val_3d = value.view(-1, idx_3d.size(1), 1)
        mask = (idx_3d == val_3d)
        idx = mask.int().argmax(dim=-1, keepdim=True)
        ret = super().log_prob(idx.view_as(value))
        # Fill masked values with neg_inf.
        ret.resize_as_(val_3d)
        ret.masked_fill_(torch.logical_not(mask.any(dim=-1, keepdim=True)),
                         self._neg_inf)
        return ret.resize_as_(value)

    @staticmethod
    def _mask_probs(probs: torch.Tensor,
                    mask: Optional[torch.Tensor] = None,
                    sparse_mask: bool = False,
                    padding_value: Optional[int] = None) -> torch.Tensor:
        if mask is None:
            return probs

        if not sparse_mask:
            return torch.where(mask, probs, 0.0)

        if padding_value is not None:
            padding_mask = (mask == padding_value)
            if padding_value != 0:
                # Avoid invalid indices in mask.
                mask = mask.masked_fill(padding_mask, 0)
        probs = probs.gather(dim=-1, index=mask)
        if padding_value is not None:
            probs.masked_fill_(padding_mask, 0.0)
        return probs

    @staticmethod
    def _mask_logits(logits: torch.Tensor,
                     mask: Optional[torch.Tensor] = None,
                     neg_inf: float = float("-inf"),
                     sparse_mask: bool = False,
                     padding_value: Optional[int] = None) -> torch.Tensor:
        if mask is None:
            return logits

        if not sparse_mask:
            return torch.where(mask, logits, neg_inf)

        if padding_value is not None:
            padding_mask = (mask == padding_value)
            if padding_value != 0:
                # Avoid invalid indices in mask.
                mask = mask.masked_fill(padding_mask, 0)
        logits = logits.gather(dim=-1, index=mask)
        if padding_value is not None:
            logits.masked_fill_(padding_mask, neg_inf)
        return logits
