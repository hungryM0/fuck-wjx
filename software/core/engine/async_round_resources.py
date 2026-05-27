"""异步运行槽位的单轮答题资源租约。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from software.core.engine.failure_reason import FailureReason
from software.core.engine.provider_common import ensure_joint_psychometric_answer_plan
from software.core.task import ExecutionConfig, ExecutionState

JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS = 45.0
JOINT_SLOT_WAIT_POLL_SECONDS = 0.5
JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS = 0.2
JOINT_PRE_ANSWER_TIMEOUT = object()


class AsyncRoundResources:
    """管理反填样本和联合信效度槽位。"""

    def __init__(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        slot_label: str,
        stop_requested: Callable[[], bool],
        should_stop_loop: Callable[[], Awaitable[bool]],
        set_stop_requested: Callable[[], None],
        update_status: Callable[..., None],
    ) -> None:
        self.config = config
        self.state = state
        self.slot_label = slot_label
        self.stop_requested = stop_requested
        self.should_stop_loop = should_stop_loop
        self.set_stop_requested = set_stop_requested
        self.update_status = update_status

    def expire_stale_joint_reservations(self) -> None:
        try:
            expired_count = self.state.expire_stale_joint_sample_reservations(
                JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS,
            )
        except Exception:
            logging.info("清理过期联合信效度槽位租约失败", exc_info=True)
            return
        if expired_count > 0:
            logging.warning("已释放%s个超时未进入答题的联合信效度槽位", expired_count)

    def requires_joint_sample(self) -> bool:
        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        if joint_answer_plan is None:
            return False
        sample_count = int(
            getattr(joint_answer_plan, "sample_count", self.config.target_num)
            or self.config.target_num
        )
        return sample_count > 0

    async def prepare_round_context(self) -> bool:
        try:
            self.state.reset_pending_distribution(self.slot_label)
        except Exception:
            logging.info("重置本轮比例统计缓存失败", exc_info=True)

        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        sample_count = 0
        if joint_answer_plan is not None:
            sample_count = int(
                getattr(joint_answer_plan, "sample_count", self.config.target_num)
                or self.config.target_num
            )

        while True:
            if self.stop_requested():
                return False
            if await self.should_stop_loop():
                return False
            self.expire_stale_joint_reservations()

            reserved_sample_index = None
            if sample_count > 0:
                reserved_sample_index = self.state.reserve_joint_sample(
                    sample_count,
                    thread_name=self.slot_label,
                )

            reverse_fill_sample = self.state.acquire_reverse_fill_sample(self.slot_label)

            if sample_count > 0 and reserved_sample_index is None:
                if reverse_fill_sample.status == "acquired":
                    try:
                        self.state.release_reverse_fill_sample(self.slot_label, requeue=True)
                    except Exception:
                        logging.info("等待信效度配额时回收反填样本失败", exc_info=True)
                if self.state.is_joint_sample_quota_exhausted(sample_count):
                    message = "联合信效度样本槽位已全部完成"
                    logging.info("%s，剩余会话自动收尾。", message)
                    self.state.mark_terminal_stop("target_reached", message=message)
                    self.set_stop_requested()
                    self.update_status("信效度配额已完成", running=False)
                    return False
                self.update_status("等待信效度配额槽位")
                await asyncio.sleep(JOINT_SLOT_WAIT_POLL_SECONDS)
                continue

            if reverse_fill_sample.status == "waiting":
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(self.slot_label)
                    except Exception:
                        logging.info("等待反填样本时释放联合信效度样本槽位失败", exc_info=True)
                self.update_status("等待反填样本")
                await asyncio.sleep(JOINT_SLOT_WAIT_POLL_SECONDS)
                continue

            if reverse_fill_sample.status == "exhausted":
                message = "反填样本已耗尽，剩余样本不足以完成目标份数"
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(self.slot_label)
                    except Exception:
                        logging.info("反填样本耗尽时释放联合信效度样本槽位失败", exc_info=True)
                self.state.mark_terminal_stop(
                    "reverse_fill_exhausted",
                    failure_reason=FailureReason.FILL_FAILED.value,
                    message=message,
                )
                self.update_status("反填样本不足", running=False)
                self.set_stop_requested()
                return False

            if reverse_fill_sample.status == "acquired" and reverse_fill_sample.sample is not None:
                logging.info(
                    "会话[%s]已锁定反填样本：数据行=%s 工作表行=%s",
                    self.slot_label,
                    reverse_fill_sample.sample.data_row_number,
                    reverse_fill_sample.sample.worksheet_row_number,
                )
            return True

    def release_round_resources(self, *, requeue_reverse_fill: bool) -> None:
        try:
            self.state.release_joint_sample(self.slot_label)
        except Exception:
            logging.info("释放联合信效度样本槽位失败", exc_info=True)
        try:
            self.state.release_reverse_fill_sample(
                self.slot_label,
                requeue=requeue_reverse_fill,
            )
        except Exception:
            logging.info("释放反填样本失败", exc_info=True)

    async def run_pre_answer_step_with_joint_lease(self, label: str, operation: Any) -> Any:
        if self.state.peek_reserved_joint_sample(self.slot_label) is None:
            return await operation()
        try:
            return await asyncio.wait_for(
                operation(),
                timeout=JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS,
            )
        except asyncio.TimeoutError:
            logging.warning(
                "会话[%s]在%s阶段超过%.0f秒未进入答题，释放联合信效度槽位",
                self.slot_label,
                label,
                JOINT_PRE_ANSWER_RESERVATION_LEASE_SECONDS,
            )
            self.release_round_resources(requeue_reverse_fill=True)
            return JOINT_PRE_ANSWER_TIMEOUT


__all__ = [
    "AsyncRoundResources",
    "JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS",
    "JOINT_PRE_ANSWER_TIMEOUT",
]
