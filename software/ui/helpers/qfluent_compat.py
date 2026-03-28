"""QFluentWidgets 稳定性补丁。"""
from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEvent, QParallelAnimationGroup, QPropertyAnimation
from shiboken6 import isValid


def install_qfluentwidgets_animation_guards() -> None:
    """为已知的 QFluentWidgets 动画/消息条兼容问题打补丁。"""
    try:
        from qfluentwidgets import IndeterminateProgressBar
        from qfluentwidgets.components.widgets.info_bar import InfoBarManager
    except Exception:
        return

    if getattr(IndeterminateProgressBar, "_surveycontroller_resume_guard_installed", False):
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

    def _safe_set_paused(self, is_paused: bool):
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

    IndeterminateProgressBar.resume = _safe_resume
    IndeterminateProgressBar.setPaused = _safe_set_paused
    IndeterminateProgressBar._surveycontroller_resume_guard_installed = True
    _install_infobar_manager_guards(InfoBarManager)


def _install_infobar_manager_guards(info_bar_manager_cls) -> None:
    """为 InfoBar 管理器补充已销毁对象保护，避免双重关闭时崩溃。"""
    manager_classes = {info_bar_manager_cls, *getattr(info_bar_manager_cls, "managers", {}).values()}
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
                drop_ani = QPropertyAnimation(info_bar, b"pos")
                drop_ani.setDuration(200)
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

        info_bar.closedSignal.connect(lambda: _safe_remove(self, info_bar))
        info_bar.destroyed.connect(lambda *_args, p=parent: _prune_invalid_bars(self, p))

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
        manager_cls._surveycontroller_remove_guard_installed = True
__all__ = [
    "install_qfluentwidgets_animation_guards",
]
