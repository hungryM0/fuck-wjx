"""QFluentWidgets 稳定性补丁。"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import (
    QAbstractAnimation,
    QByteArray,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


def install_qfluentwidgets_animation_guards() -> None:
    """为已知的 QFluentWidgets 动画/消息条兼容问题打补丁。"""
    try:
        from qfluentwidgets import IndeterminateProgressBar
        from qfluentwidgets.components.widgets.info_bar import InfoBarManager
    except Exception:
        return

    if getattr(
        IndeterminateProgressBar,
        "_surveycontroller_resume_guard_installed",
        False,
    ):
        _install_infobar_manager_guards(InfoBarManager)
        return

    original_start = IndeterminateProgressBar.start

    def _safe_resume(self):
        state = self.aniGroup.state()
        if state == QAbstractAnimation.State.Paused:
            self.aniGroup.resume()
        elif state == QAbstractAnimation.State.Stopped and not getattr(self, "_isError", False):
            original_start(self)
            return

        self.update()

    def _safe_set_paused(self, isPaused: bool):
        is_paused = bool(isPaused)
        state = self.aniGroup.state()
        if is_paused:
            if state == QAbstractAnimation.State.Running:
                self.aniGroup.pause()
                self.update()
            return

        if state == QAbstractAnimation.State.Paused:
            self.aniGroup.resume()
            self.update()
        elif state == QAbstractAnimation.State.Stopped and not getattr(self, "_isError", False):
            original_start(self)
        else:
            self.update()

    progress_cls = cast(Any, IndeterminateProgressBar)
    progress_cls.resume = _safe_resume
    progress_cls.setPaused = _safe_set_paused
    setattr(progress_cls, "_surveycontroller_resume_guard_installed", True)
    _install_infobar_manager_guards(InfoBarManager)


def _install_infobar_manager_guards(info_bar_manager_cls) -> None:
    """为 InfoBar 管理器补充已销毁对象保护，避免双重关闭时崩溃。"""
    manager_classes = {
        info_bar_manager_cls,
        *getattr(info_bar_manager_cls, "managers", {}).values(),
    }
    pending_classes = [
        manager_cls
        for manager_cls in manager_classes
        if not getattr(manager_cls, "_surveycontroller_remove_guard_installed", False)
    ]
    if not pending_classes:
        return

    def _is_alive(obj) -> bool:
        if obj is None:
            return False
        try:
            return bool(isValid(obj))
        except Exception:
            return False

    def _prune_invalid_bars(self, parent) -> list:
        if not _is_alive(parent):
            return []
        if parent not in self.infoBars:
            return []
        alive = [bar for bar in list(self.infoBars[parent]) if _is_alive(bar)]
        current = self.infoBars[parent]
        if len(alive) != len(current):
            current[:] = alive
        return alive

    def _get_signal_callback_store(self) -> dict[int, tuple[Any, Any]]:
        store = getattr(self, "_surveycontroller_signal_callbacks", None)
        if not isinstance(store, dict):
            store = {}
            setattr(self, "_surveycontroller_signal_callbacks", store)
        return store

    def _drop_signal_callbacks(self, info_bar) -> None:
        _get_signal_callback_store(self).pop(id(info_bar), None)

    def _safe_add(self, info_bar) -> None:
        try:
            parent = info_bar.parent()
        except RuntimeError:
            parent = None

        if not parent or not _is_alive(parent) or not _is_alive(info_bar):
            return

        if parent not in self.infoBars:
            try:
                parent.installEventFilter(self)
            except RuntimeError:
                return
            self.infoBars[parent] = []
            self.aniGroups[parent] = QParallelAnimationGroup(self)

        bars = _prune_invalid_bars(self, parent)
        if info_bar in bars:
            return

        if bars:
            try:
                drop_ani = QPropertyAnimation(info_bar, QByteArray(b"pos"))
                drop_ani.setDuration(200)
                target_pos = self._pos(info_bar)
                drop_ani.setStartValue(target_pos)
                drop_ani.setEndValue(target_pos)
                self.aniGroups[parent].addAnimation(drop_ani)
                self.dropAnis.append(drop_ani)
                info_bar.setProperty("dropAni", drop_ani)
            except RuntimeError:
                pass

        self.infoBars[parent].append(info_bar)

        try:
            slide_ani = self._createSlideAni(info_bar)
            self.slideAnis.append(slide_ani)
            info_bar.setProperty("slideAni", slide_ani)
        except RuntimeError:
            try:
                self.infoBars[parent].remove(info_bar)
            except ValueError:
                pass
            return

        bar_key = id(info_bar)

        def _on_closed() -> None:
            _safe_remove(self, info_bar)
            _drop_signal_callbacks(self, info_bar)

        def _on_destroyed(*_args, p=parent, _key=bar_key) -> None:
            _prune_invalid_bars(self, p)
            _get_signal_callback_store(self).pop(_key, None)

        _get_signal_callback_store(self)[bar_key] = (_on_closed, _on_destroyed)
        info_bar.closedSignal.connect(_on_closed)
        info_bar.destroyed.connect(_on_destroyed)

        try:
            slide_ani.start()
        except RuntimeError:
            pass

    def _safe_update_drop_ani(self, parent):
        for bar in _prune_invalid_bars(self, parent):
            try:
                ani = bar.property("dropAni")
            except RuntimeError:
                continue
            if not ani:
                continue
            try:
                ani.setStartValue(bar.pos())
                ani.setEndValue(self._pos(bar))
            except (RuntimeError, ValueError):
                continue

    def _safe_remove(self, info_bar):
        try:
            parent = info_bar.parent()
        except RuntimeError:
            parent = None
        if not parent or parent not in self.infoBars:
            return

        bars = _prune_invalid_bars(self, parent)
        if info_bar not in bars:
            return

        bars.remove(info_bar)
        _drop_signal_callbacks(self, info_bar)

        if _is_alive(info_bar):
            try:
                drop_ani = info_bar.property("dropAni")
            except RuntimeError:
                drop_ani = None
            if drop_ani:
                try:
                    self.aniGroups[parent].removeAnimation(drop_ani)
                except RuntimeError:
                    pass
                try:
                    self.dropAnis.remove(drop_ani)
                except ValueError:
                    pass

            try:
                slide_ani = info_bar.property("slideAni")
            except RuntimeError:
                slide_ani = None
            if slide_ani:
                try:
                    self.slideAnis.remove(slide_ani)
                except ValueError:
                    pass

        _safe_update_drop_ani(self, parent)
        try:
            self.aniGroups[parent].start()
        except RuntimeError:
            pass

    def _safe_event_filter(self, obj, e):
        try:
            if obj not in self.infoBars:
                return False

            if e.type() in (QEvent.Type.Resize, QEvent.Type.WindowStateChange):
                size = e.size() if e.type() == QEvent.Type.Resize else None
                for bar in _prune_invalid_bars(self, obj):
                    try:
                        bar.move(self._pos(bar, size))
                    except (RuntimeError, ValueError):
                        continue

            return False
        except Exception:
            return False

    for manager_cls in pending_classes:
        manager_cls.add = _safe_add
        manager_cls._updateDropAni = _safe_update_drop_ani
        manager_cls.remove = _safe_remove
        manager_cls.eventFilter = _safe_event_filter
        setattr(manager_cls, "_surveycontroller_remove_guard_installed", True)


def set_indeterminate_progress_ring_active(ring: Any, active: bool) -> None:
    """统一控制 ProgressRing 动画状态，避免隐藏控件还在后台乱转。"""
    if ring is None:
        return

    try:
        ani_group = getattr(ring, "aniGroup", None)
        if active:
            ring.show()
            if ani_group is not None:
                state = ani_group.state()
                if state == QAbstractAnimation.State.Paused:
                    ani_group.resume()
                elif state != QAbstractAnimation.State.Running:
                    ring.start()
            else:
                ring.start()
            return

        if ani_group is not None and ani_group.state() != QAbstractAnimation.State.Stopped:
            ring.stop()
        elif hasattr(ring, "stop"):
            ring.stop()
        ring.hide()
    except RuntimeError:
        pass
    except Exception:
        try:
            ring.hide()
        except Exception:
            pass


def resolve_mask_dialog_parent(parent: QWidget | None) -> QWidget:
    """为 MessageBoxBase 提供可靠的父窗口，避免空父窗口直接崩。"""
    if parent is not None and parent.width() > 0 and parent.height() > 0:
        return parent

    active_window = QApplication.activeWindow()
    if (
        isinstance(active_window, QWidget)
        and active_window.isVisible()
        and active_window.width() > 0
        and active_window.height() > 0
    ):
        return active_window

    for widget in reversed(QApplication.topLevelWidgets()):
        if widget.isVisible() and widget.width() > 0 and widget.height() > 0:
            return widget

    fallback_parent = QWidget()
    fallback_parent.setWindowFlag(Qt.WindowType.Tool, True)
    fallback_parent.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    fallback_parent.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    fallback_parent.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    fallback_parent.setWindowOpacity(0.0)
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        geometry = screen.availableGeometry()
        fallback_parent.resize(max(1, geometry.width()), max(1, geometry.height()))
    else:
        fallback_parent.resize(1280, 800)
    fallback_parent.show()
    return fallback_parent


__all__ = [
    "install_qfluentwidgets_animation_guards",
    "resolve_mask_dialog_parent",
    "set_indeterminate_progress_ring_active",
]
