"""Provider hook 构建工具。"""

from __future__ import annotations

import inspect
from functools import lru_cache
from importlib import import_module
from typing import Any, TypeAlias

from software.core.engine.runtime_actions import ensure_runtime_action_result
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


def build_fill_hook(target: HookTarget):
    async def _fill(
        driver: Any,
        config: Any,
        state: Any,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
    ) -> bool:
        return bool(
            await _invoke(
                target,
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=psycho_plan,
            )
        )

    return _fill


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


def build_predicate_hook(target: HookTarget):
    async def _predicate(driver: Any) -> bool:
        return bool(await _invoke(target, driver))

    return _predicate


def build_text_hook(target: HookTarget):
    async def _text(driver: Any) -> str:
        return str(await _invoke(target, driver) or "").strip()

    return _text


def build_wait_hook(target: HookTarget):
    async def _wait(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        return bool(
            await _invoke(
                target,
                driver,
                timeout=timeout,
                stop_signal=stop_signal,
            )
        )

    return _wait


def build_wait_from_predicate_hook(target: HookTarget):
    async def _wait(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        del timeout, stop_signal
        return bool(await _invoke(target, driver))

    return _wait


def build_action_hook(target: HookTarget):
    async def _action(ctx: Any, stop_signal: Any):
        return ensure_runtime_action_result(await _invoke(target, ctx, stop_signal))

    return _action


def build_submission_recovery_hook(target: HookTarget):
    async def _recovery(
        driver: Any,
        ctx: Any,
        gui_instance: Any,
        stop_signal: Any,
        *,
        thread_name: str = "",
    ) -> bool:
        return bool(
            await _invoke(
                target,
                driver,
                ctx,
                gui_instance,
                stop_signal,
                thread_name=thread_name,
            )
        )

    return _recovery
