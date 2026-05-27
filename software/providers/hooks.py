"""Provider hook 构建工具。"""

from __future__ import annotations

import inspect
from functools import lru_cache
from importlib import import_module
from typing import Any, TypeAlias

from software.providers.contracts import SurveyDefinition, build_survey_definition

HookTarget: TypeAlias = tuple[str, str]


@lru_cache(maxsize=None)
def _load_hook(target: HookTarget) -> Any:
    module_path, attr_name = target
    module = import_module(module_path)
    return getattr(module, attr_name)


async def _invoke(target: HookTarget, *args: Any, **kwargs: Any) -> Any:
    value = _load_hook(target)(*args, **kwargs)
    if not inspect.isawaitable(value):
        raise TypeError(f"provider hook 必须返回 awaitable: {target[0]}.{target[1]}")
    return await value


def build_parse_hook(provider: str, target: HookTarget):
    async def _parse(url: str) -> SurveyDefinition:
        value = _load_hook(target)(url)
        if not inspect.isawaitable(value):
            raise TypeError(f"解析 hook 必须返回 awaitable: {target[0]}.{target[1]}")
        info, title = await value
        return build_survey_definition(provider, title, info)

    return _parse


def build_fill_http_hook(target: HookTarget):
    async def _fill_http(
        config: Any,
        state: Any,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
        proxy_address: str | None = None,
        user_agent: str | None = None,
    ) -> bool:
        return bool(
            await _invoke(
                target,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=psycho_plan,
                proxy_address=proxy_address,
                user_agent=user_agent,
            )
        )

    return _fill_http
