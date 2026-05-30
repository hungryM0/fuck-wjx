"""额度兑换弹窗"""

from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IndeterminateProgressRing,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PushButton,
    SimpleCardWidget,
    StrongBodyLabel,
    isDarkTheme,
)

from software.app.runtime_paths import get_resource_path
from software.ui.helpers.qfluent_compat import set_indeterminate_progress_ring_active
from software.ui.helpers.proxy_access import (
    RandomIPAuthError,
    format_quota_value,
    format_random_ip_error,
    get_session_snapshot,
    has_authenticated_session,
    redeem_card_async,
)


class QuotaRedeemDialog(MessageBoxBase):
    """额度兑换弹窗"""

    _redeemFinished = Signal(bool, object)
    _SHOP_URL = "https://pay.ldxp.cn/shop/surveycontroller"
    _SHOP_ICON_PATH = "assets/pay_ldxp_favicon.ico"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("额度兑换")
        self.widget.setFixedWidth(540)
        self.widget.setMinimumHeight(320)
        self._redeeming = False
        self._redeemFinished.connect(
            self._on_redeem_finished,
            Qt.ConnectionType.QueuedConnection,
        )

        self.titleRow = QWidget(self.widget)
        title_layout = QHBoxLayout(self.titleRow)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        self.heroIcon = IconWidget(FluentIcon.SHOPPING_CART, self.titleRow)
        self.heroIcon.setFixedSize(22, 22)
        title_layout.addWidget(self.heroIcon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.heroLabel = StrongBodyLabel("额度兑换", self.titleRow)
        self.heroLabel.setWordWrap(True)
        self.heroLabel.setStyleSheet("font-size: 20px; font-weight: 700;")
        title_layout.addWidget(self.heroLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        title_layout.addStretch(1)

        self.accountHintLabel = CaptionLabel("", self.widget)
        self.accountHintLabel.setWordWrap(True)
        self._apply_account_hint_style()

        self.formCard = SimpleCardWidget(self.widget)
        self.formCard.setStyleSheet(
            "SimpleCardWidget {"
            "padding: 0px;"
            "border: 1px solid rgba(120, 120, 120, 0.18);"
            "border-radius: 12px;"
            "}"
        )
        form_layout = QVBoxLayout(self.formCard)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        self.cardCodeTitleLabel = CaptionLabel("请输入额度卡密：", self.formCard)
        self.cardCodeEdit = LineEdit(self.formCard)
        self.cardCodeEdit.setPlaceholderText("请输入卡密")
        self.cardCodeEdit.setClearButtonEnabled(True)
        self.cardCodeEdit.setMaxLength(128)

        store_row = QWidget(self.formCard)
        store_layout = QHBoxLayout(store_row)
        store_layout.setContentsMargins(0, 0, 0, 0)
        store_layout.setSpacing(10)
        self.storeHintLabel = CaptionLabel(
            "如果你是大学生的话，可以加入社区群聊申请优惠🥰",
            store_row,
        )
        self.storeHintLabel.setWordWrap(True)
        self.storeButton = PushButton("前往卡密店铺", store_row)
        self._apply_shop_button_icon()
        self.storeButton.clicked.connect(self._open_shop)
        store_layout.addWidget(self.storeHintLabel, 1)
        store_layout.addWidget(self.storeButton, 0, Qt.AlignmentFlag.AlignRight)

        form_layout.addWidget(self.cardCodeTitleLabel)
        form_layout.addWidget(self.cardCodeEdit)
        form_layout.addWidget(store_row)

        self.loadingLabel = BodyLabel("", self.widget)
        self.loadingLabel.hide()

        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(self.titleRow)
        self.viewLayout.addWidget(self.accountHintLabel)
        self.viewLayout.addWidget(self.formCard)
        self.viewLayout.addWidget(self.loadingLabel)

        self.yesButton.setText("立即兑换")
        self.yesButton.installEventFilter(self)
        self.yesButtonSpinner = IndeterminateProgressRing(self.yesButton)
        self.yesButtonSpinner.setFixedSize(16, 16)
        self.yesButtonSpinner.setStrokeWidth(2)
        self.yesButtonSpinner.hide()
        self.cancelButton.setText("取消")
        self._layout_yes_button_spinner()
        self._refresh_account_hint()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._apply_account_hint_style()
        self._refresh_account_hint()
        self._layout_yes_button_spinner()

    def eventFilter(self, obj, e) -> bool:
        yes_button = getattr(self, "yesButton", None)
        if yes_button is not None and obj is yes_button and e.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.FontChange,
        }:
            self._layout_yes_button_spinner()
        return super().eventFilter(obj, e)

    def validate(self) -> bool:
        self._refresh_account_hint()
        if self._redeeming:
            self._show_pending_warning()
            return False
        if not has_authenticated_session():
            InfoBar.warning(
                "",
                "请先去测试随机ip是否真的可用，再来兑换卡密",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2600,
            )
            return False

        card_code = str(self.cardCodeEdit.text() or "").strip()
        if not card_code:
            InfoBar.warning(
                "",
                "请输入卡密",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return False

        confirm_box = MessageBox(
            "确认兑换",
            "兑换后无法撤回，确认继续？",
            self,
        )
        confirm_box.yesButton.setText("确认兑换")
        confirm_box.cancelButton.setText("取消")
        if not confirm_box.exec():
            return False

        self._set_redeeming(True)

        def _redeem() -> None:
            try:
                import asyncio

                result = asyncio.run(redeem_card_async(card_code))
                self._redeemFinished.emit(True, result)
            except Exception as exc:
                self._redeemFinished.emit(False, exc)

        threading.Thread(target=_redeem, daemon=True, name="QuotaRedeemDialog").start()
        return False

    def reject(self) -> None:
        if self._redeeming:
            self._show_pending_warning()
            return
        super().reject()

    def _refresh_account_hint(self) -> None:
        self._apply_account_hint_style()
        snapshot = get_session_snapshot()
        if not has_authenticated_session():
            self.accountHintLabel.setText(
                "请先启用一次随机 IP，经测试确认随机 IP 可用后再来兑换卡密"
            )
            return
        user_id = int(snapshot.get("user_id") or 0)
        self.accountHintLabel.setText(f"用户 ID：{user_id}")

    def _apply_account_hint_style(self) -> None:
        color = "rgba(255, 255, 255, 0.68)" if isDarkTheme() else "rgba(32, 32, 32, 0.72)"
        self.accountHintLabel.setStyleSheet(f"color: {color}; font-size: 12px;")

    def _set_redeeming(self, redeeming: bool) -> None:
        self._redeeming = bool(redeeming)
        self.cardCodeEdit.setEnabled(not redeeming)
        self.storeButton.setEnabled(not redeeming)
        self.cancelButton.setEnabled(not redeeming)
        self.yesButton.setEnabled(not redeeming)
        self.yesButton.setText("兑换中..." if redeeming else "立即兑换")
        self._layout_yes_button_spinner()
        set_indeterminate_progress_ring_active(self.yesButtonSpinner, redeeming)
        if redeeming:
            self.loadingLabel.setText("正在兑换，请稍等...")
            self.loadingLabel.show()
        else:
            self.loadingLabel.hide()
            self.loadingLabel.clear()

    def _layout_yes_button_spinner(self) -> None:
        text = self.yesButton.text() or ""
        text_width = self.yesButton.fontMetrics().horizontalAdvance(text)
        content_left = max(10, (self.yesButton.width() - text_width) // 2)
        x = max(10, content_left - self.yesButtonSpinner.width() - 6)
        y = max(0, (self.yesButton.height() - self.yesButtonSpinner.height()) // 2)
        self.yesButtonSpinner.move(x, y)

    def _show_pending_warning(self) -> None:
        InfoBar.warning(
            "",
            "额度兑换还未完成，请稍等...",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2200,
        )

    def _apply_shop_button_icon(self) -> None:
        icon = load_shop_icon()
        if icon is not None:
            self.storeButton.setIcon(icon)

    def _open_shop(self) -> None:
        QDesktopServices.openUrl(QUrl(self._SHOP_URL))

    @Slot(bool, object)
    def _on_redeem_finished(self, success: bool, payload: object) -> None:
        self._set_redeeming(False)
        self._refresh_account_hint()

        if success:
            data = payload if isinstance(payload, dict) else {}
            quota = format_quota_value(float(data.get("card_quota") or 0.0))
            InfoBar.success(
                "",
                f"兑换成功，已到账 {quota}！",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3200,
            )
            self.cardCodeEdit.clear()
            QTimer.singleShot(1400, self.accept)
            return

        exc = (
            payload
            if isinstance(payload, BaseException)
            else RuntimeError(str(payload or "兑换失败"))
        )
        if isinstance(exc, RandomIPAuthError):
            message = format_random_ip_error(exc)
            detail = str(exc.detail or "").strip()
            if detail == "redeem_card_code_required":
                message = "卡密不能为空"
            elif detail == "invalid_redeem_card_code":
                message = "卡密格式错误，复制错了？"
            elif detail == "redeem_card_not_found":
                message = "该卡密不存在，请检查是否输错"
            elif detail == "redeem_card_already_redeemed":
                message = "这张卡密已经被兑换过了"
        else:
            logging.warning("额度兑换失败", exc_info=exc)
            message = f"兑换失败：{exc}"
        InfoBar.error(
            "",
            message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3200,
        )


def load_shop_icon() -> QIcon | None:
    """加载发卡店铺图标"""
    icon_path = get_resource_path(QuotaRedeemDialog._SHOP_ICON_PATH)
    if not os.path.exists(icon_path):
        return None
    return QIcon(icon_path)
