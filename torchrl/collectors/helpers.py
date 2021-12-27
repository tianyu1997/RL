from typing import Union, Callable, List, Optional, Type

from .collectors import MultiaSyncDataCollector, MultiSyncDataCollector, MultiDataCollector
from ..envs import ParallelEnv

__all__ = ["sync_sync_collector", "sync_async_collector"]


def sync_async_collector(
        env_fns: Union[Callable, List[Callable]],
        env_kwargs: Optional[Union[dict, List[dict]]],
        policy: Callable,
        max_steps_per_traj: int = -1,
        frames_per_batch: int = 200,
        total_frames: Optional[int] = None,
        batcher: Optional[Callable] = None,
        num_env_per_collector: Optional[int] = None,
        num_collectors: Optional[int] = None,
        passing_device="cpu",
        **kwargs) -> MultiaSyncDataCollector:
    """
    Runs asynchronous collectors, each running synchronous environments, e.g.
    |            MultiConcurrentCollector                 |              |
    |   Collector 1   |   Collector 2   |   Collector 3   |     main     |
    |  env1  |  env2  |  env3  |  env4  |  env5  |  env6  |              |
    |=================|=================|=================|==============|
    | reset  | reset  | reset  | reset  | reset  | reset  |              |
    |      actor      |        |        |      actor      |              |
    |  step  |  step  |      actor      |                 |              |
    |        |        |                 |  step  |  step  |              |
    |      actor      |  step  |  step  |      actor      |              |
    |  yield batch 1  |      actor      |                 |collect, train|
    |  step  |  step  |                 |  yield batch 2  |collect, train|
    |                 |  yield batch 3  |                 |collect, train|
    etc.
    Environment types can be identical or different. In the latter case, env_fns should be a list with all the creator
    fns for the various envs,
    and the policy should handle those envs in batch.

    Args:
        env_fns:
        env_kwargs:
        policy:
        max_steps_per_traj:
        frames_per_batch:
        total_frames:
        batcher:
        num_env_per_collector:
        num_collectors:
        passing_device:
        **kwargs:

    Returns:

    """

    return _make_collector(MultiaSyncDataCollector,
                           env_fns=env_fns,
                           env_kwargs=env_kwargs,
                           policy=policy,
                           max_steps_per_traj=max_steps_per_traj,
                           frames_per_batch=frames_per_batch,
                           total_frames=total_frames,
                           batcher=batcher,
                           num_env_per_collector=num_env_per_collector,
                           num_collectors=num_collectors,
                           passing_device=passing_device,
                           **kwargs)


def sync_sync_collector(
        env_fns: Union[Callable, List[Callable]],
        env_kwargs: Optional[Union[dict, List[dict]]],
        policy: Callable,
        max_steps_per_traj: int = -1,
        frames_per_batch: int = 200,
        total_frames: Optional[int] = None,
        batcher: Optional[Callable] = None,
        num_env_per_collector: Optional[int] = None,
        num_collectors: Optional[int] = None,
        passing_device="cpu",
        **kwargs) -> MultiSyncDataCollector:
    """
    Runs synchronous collectors, each running synchronous environments, e.g.
    |            MultiConcurrentCollector                 |              |
    |   Collector 1   |   Collector 2   |   Collector 3   |     main     |
    |  env1  |  env2  |  env3  |  env4  |  env5  |  env6  |              |
    |=================|=================|=================|==============|
    | reset  | reset  | reset  | reset  | reset  | reset  |              |
    |      actor      |        |        |      actor      |              |
    |  step  |  step  |      actor      |                 |              |
    |        |        |                 |  step  |  step  |              |
    |      actor      |  step  |  step  |      actor      |              |
    |                 |      actor      |                 |              |
    |                yield batch of traj 1                |collect, train|
    |  step  |  step  |  step  |  step  |  step  |  step  |              |
    |      actor      |      actor      |        |        |              |
    |                 |  step  |  step  |      actor      |              |
    |  step  |  step  |      actor      |  step  |  step  |              |
    |      actor      |                 |      actor      |              |
    |                yield batch of traj 2                |collect, train|

    etc.
    Envs can be identical or different. In the latter case, env_fns should be a list with all the creator fns
    for the various envs,
    and the policy should handle those envs in batch.

    Args:
        env_fns:
        env_kwargs:
        policy:
        max_steps_per_traj:
        frames_per_batch:
        total_frames:
        batcher:
        num_env_per_collector:
        num_collectors:
        passing_device:
        **kwargs:

    Returns:

    """
    return _make_collector(MultiSyncDataCollector,
                           env_fns=env_fns,
                           env_kwargs=env_kwargs,
                           policy=policy,
                           max_steps_per_traj=max_steps_per_traj,
                           frames_per_batch=frames_per_batch,
                           total_frames=total_frames,
                           batcher=batcher,
                           num_env_per_collector=num_env_per_collector,
                           num_collectors=num_collectors,
                           passing_device=passing_device, **kwargs)


def _make_collector(
        collector_class: Type,
        env_fns: Union[Callable, List[Callable]],
        env_kwargs: Optional[Union[dict, List[dict]]],
        policy: Callable,
        max_steps_per_traj: int = -1,
        frames_per_batch: int = 200,
        total_frames: Optional[int] = None,
        batcher: Optional[Callable] = None,
        num_env_per_collector: Optional[int] = None,
        num_collectors: Optional[int] = None,
        passing_device="cpu",
        **kwargs) -> MultiDataCollector:
    if env_kwargs is None:
        env_kwargs = dict()
    if isinstance(env_fns, list):
        num_env = len(env_fns)
        if num_env_per_collector is None:
            num_env_per_collector = - (num_env // -num_collectors)
        elif num_collectors is None:
            num_collectors = - (num_env // -num_env_per_collector)
        else:
            assert num_env_per_collector * num_collectors >= num_env
    else:
        try:
            num_env = num_env_per_collector * num_collectors
            env_fns = [env_fns for _ in range(num_env)]
        except(TypeError):
            raise Exception(
                "num_env was not a list but num_env_per_collector and num_collectors were not both specified,"
                f"got num_env_per_collector={num_env_per_collector} and num_collectors={num_collectors}")
    if not isinstance(env_kwargs, list):
        env_kwargs = [env_kwargs for _ in range(num_env)]

    env_fns_split = [env_fns[i:i + num_env_per_collector] for i in range(0, num_env, num_env_per_collector)]
    env_kwargs_split = [env_kwargs[i:i + num_env_per_collector] for i in range(0, num_env, num_env_per_collector)]
    assert len(env_fns_split) == num_collectors

    if num_env_per_collector == 1:
        env_fns = [lambda: _env_fn[0](**_env_kwargs[0])
                   for _env_fn, _env_kwargs in zip(env_fns_split, env_kwargs_split)]
    else:
        env_fns = [lambda: ParallelEnv(num_workers=len(_env_fn), create_env_fn=_env_fn, create_env_kwargs=_env_kwargs)
                   for _env_fn, _env_kwargs in zip(env_fns_split, env_kwargs_split)]
    return collector_class(
        create_env_fn=env_fns,
        create_env_kwargs=None,
        policy=policy,
        total_frames=total_frames,
        max_steps_per_traj=max_steps_per_traj,
        frames_per_batch=frames_per_batch,
        batcher=batcher,
        passing_device=passing_device,
        **kwargs,
    )
