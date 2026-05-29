"""应用更新检测与执行。"""
from __future__ import annotations

import logging
import importlib
import os
import re
import sys
import webbrowser
from threading import Thread
from typing import Any, Callable, Optional, cast

import software.network.http as http_client
from software.app.config import VELOPACK_CHANNEL, VELOPACK_FEED_URL
from software.app.version import __VERSION__, GITHUB_API_URL, GITHUB_RELEASES_URL, GITHUB_RELEASE_TAG_URL
from software.logging.action_logger import log_action

try:
    from packaging import version
except ImportError:  # pragma: no cover
    version = None

_VELOPACK_MODULE_NAME = "velopack"


def _get_velopack_module() -> Optional[Any]:
    try:
        return cast(Any, importlib.import_module(_VELOPACK_MODULE_NAME))
    except Exception:
        return None


def _preview_release_notes(text: str, limit: int) -> str:
    if not text:
        return "暂无更新说明"
    text = re.sub(r"^#{1,6}\s*", "", str(text), flags=re.MULTILINE)
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\n)\*(.+?)\*", r"\1", text)
    text = re.sub(r"^\s*[\*\-]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    preview = text[:limit]
    if len(text) > limit:
        preview += "\n..."
    return preview


def _parse_version_text(value: str):
    if not version:
        return None
    try:
        return version.parse(str(value or "").strip())
    except Exception:
        return None


def _normalize_release_release_notes(asset: Any) -> str:
    markdown = str(getattr(asset, "NotesMarkdown", "") or "").strip()
    if markdown:
        return markdown
    html = str(getattr(asset, "NotesHtml", "") or "").strip()
    return html


def _normalize_release_tag(version_text: str) -> str:
    normalized = str(version_text or "").strip()
    if not normalized:
        return ""
    return normalized if normalized.lower().startswith("v") else f"v{normalized}"


def _fetch_github_release_by_tag(version_text: str) -> Optional[dict[str, Any]]:
    tag_name = _normalize_release_tag(version_text)
    if not tag_name:
        return None
    try:
        response = http_client.get(
            f"{GITHUB_RELEASES_URL}/tags/{tag_name}",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        logging.warning("按标签获取发行版说明失败: %s", exc)
    return None


def _fetch_github_release_from_list(version_text: str) -> Optional[dict[str, Any]]:
    normalized_tag = _normalize_release_tag(version_text)
    if not normalized_tag:
        return None
    try:
        response = http_client.get(
            GITHUB_RELEASES_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logging.warning("从发行版列表回退获取说明失败: %s", exc)
        return None
    if not isinstance(payload, list):
        return None
    for release in payload:
        if not isinstance(release, dict):
            continue
        tag_name = _normalize_release_tag(release.get("tag_name", ""))
        if tag_name == normalized_tag:
            return release
    return None


def _resolve_release_notes(update_info: Any, version_text: str) -> str:
    target_release = getattr(update_info, "TargetFullRelease", None)
    release_notes = _normalize_release_release_notes(target_release)
    if release_notes:
        return release_notes
    github_release = _fetch_github_release_by_tag(version_text)
    if not github_release:
        github_release = _fetch_github_release_from_list(version_text)
    if not github_release:
        return ""
    return str(github_release.get("body", "") or "").strip()


def _fetch_latest_github_release() -> Optional[dict[str, Any]]:
    try:
        response = http_client.get(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        logging.warning("获取最新发行版失败: %s", exc)
    return None


def _fetch_latest_velopack_feed_release() -> Optional[dict[str, Any]]:
    if sys.platform != "win32" or not VELOPACK_FEED_URL or not VELOPACK_CHANNEL:
        return None
    feed_url = f"{VELOPACK_FEED_URL.rstrip('/')}/releases.{VELOPACK_CHANNEL}.json"
    try:
        response = http_client.get(feed_url, timeout=(10, 30))
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logging.warning("获取 Velopack 远端 feed 失败: %s", exc)
        return None

    assets = payload.get("Assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        return None

    latest_asset: Optional[dict[str, Any]] = None
    latest_parsed = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("Type", "")).lower() != "full":
            continue
        version_text = str(asset.get("Version", "") or "").strip()
        parsed = _parse_version_text(version_text)
        if parsed is None:
            continue
        if latest_parsed is None or parsed > latest_parsed:
            latest_parsed = parsed
            latest_asset = asset
    return latest_asset


def _build_remote_version_result(
    current_version: str,
    latest_version: str,
    *,
    release_notes: str = "",
) -> dict[str, Any]:
    latest_parsed = _parse_version_text(latest_version)
    current_parsed = _parse_version_text(current_version)
    if latest_parsed is None or current_parsed is None:
        return {
            "has_update": False,
            "status": "unknown",
            "current_version": current_version,
            "latest_version": latest_version,
            "release_notes": release_notes,
        }

    if latest_parsed > current_parsed:
        return {
            "has_update": True,
            "status": "outdated",
            "version": latest_version,
            "latest_version": latest_version,
            "release_notes": release_notes,
            "current_version": current_version,
            "manual_only": True,
            "manual_release_url": f"{GITHUB_RELEASE_TAG_URL}/v{latest_version}",
        }

    if current_parsed > latest_parsed:
        return {
            "has_update": False,
            "status": "preview",
            "current_version": current_version,
            "latest_version": latest_version,
            "release_notes": release_notes,
        }

    return {
        "has_update": False,
        "status": "latest",
        "current_version": current_version,
        "latest_version": latest_version,
        "release_notes": release_notes,
    }


def _build_github_update_result(current_version: str) -> dict[str, Any]:
    github_release = _fetch_latest_github_release()
    if not github_release:
        return {"has_update": False, "status": "unknown", "current_version": current_version}

    latest_version = str(github_release.get("tag_name", "")).lstrip("v").strip()
    release_notes = str(github_release.get("body", "") or "").strip()
    result = _build_remote_version_result(
        current_version,
        latest_version,
        release_notes=release_notes,
    )
    if result.get("status") == "outdated":
        result["manual_release_url"] = (
            str(github_release.get("html_url", "") or "").strip()
            or f"{GITHUB_RELEASE_TAG_URL}/v{latest_version}"
        )
    return result


def _build_velopack_feed_update_result(current_version: str) -> dict[str, Any]:
    latest_asset = _fetch_latest_velopack_feed_release()
    if not latest_asset:
        return {"has_update": False, "status": "unknown", "current_version": current_version}
    latest_version = str(latest_asset.get("Version", "") or "").strip()
    return _build_remote_version_result(current_version, latest_version)


def _safe_create_update_manager():
    if sys.platform != "win32":
        return None
    velopack_module = _get_velopack_module()
    if velopack_module is None:
        return None
    try:
        options = velopack_module.UpdateOptions(False, 3, VELOPACK_CHANNEL)
        return velopack_module.UpdateManager(VELOPACK_FEED_URL, options)
    except Exception as exc:
        logging.info("当前环境未安装到 Velopack，跳过更新管理器初始化: %s", exc)
        return None


def _build_update_result_from_release(update_info: Any, current_version: str) -> dict[str, Any]:
    target_release = getattr(update_info, "TargetFullRelease", None)
    latest_version = str(getattr(target_release, "Version", "") or "").strip()
    release_notes = _resolve_release_notes(update_info, latest_version)
    try:
        package_size = int(getattr(target_release, "Size", 0) or 0)
    except Exception:
        package_size = 0
    return {
        "has_update": True,
        "status": "outdated",
        "version": latest_version,
        "latest_version": latest_version,
        "release_notes": release_notes,
        "current_version": current_version,
        "package_size": max(package_size, 0),
        "_velopack_update": update_info,
    }


class UpdateManager:
    """Velopack 更新管理器。"""

    @staticmethod
    def check_updates() -> dict[str, Any]:
        current_version = str(__VERSION__ or "").strip()
        if sys.platform != "win32":
            return {"has_update": False, "status": "unsupported", "current_version": current_version}
        if not version:
            logging.warning("更新功能依赖 packaging 模块")
            return {"has_update": False, "status": "unknown", "current_version": current_version}

        manager = _safe_create_update_manager()
        if manager is None:
            return _build_velopack_feed_update_result(current_version)

        try:
            installed_version = str(manager.get_current_version() or current_version).strip() or current_version
        except Exception:
            installed_version = current_version

        try:
            update_info = manager.check_for_updates()
        except Exception as exc:
            logging.warning("检查更新失败: %s", exc)
            return {"has_update": False, "status": "unknown", "current_version": installed_version}

        if update_info:
            return _build_update_result_from_release(update_info, installed_version)

        return _build_velopack_feed_update_result(installed_version)

    @staticmethod
    def get_all_releases() -> list[dict[str, Any]]:
        try:
            response = http_client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            releases = response.json()
        except Exception as exc:
            logging.warning("获取发行版列表失败: %s", exc)
            return []

        result: list[dict[str, Any]] = []
        for release in releases:
            result.append(
                {
                    "version": str(release.get("tag_name", "")).lstrip("v"),
                    "name": release.get("name", ""),
                    "body": release.get("body", ""),
                    "published_at": release.get("published_at", ""),
                    "prerelease": bool(release.get("prerelease", False)),
                    "html_url": release.get("html_url", ""),
                }
            )
        return result

    @staticmethod
    def download_update(
        update_info: Any,
        *,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> bool:
        if sys.platform != "win32":
            raise RuntimeError("当前平台不支持自动更新")
        manager = _safe_create_update_manager()
        if manager is None:
            raise RuntimeError("当前运行环境不支持 Velopack 更新")

        def _on_progress(percent: int) -> None:
            if progress_callback is None:
                return
            normalized = max(0, min(100, int(percent or 0)))
            progress_callback(normalized, 100, 0.0)

        manager.download_updates(update_info, _on_progress)
        return True

    @staticmethod
    def apply_downloaded_update(update_info: Any) -> None:
        if sys.platform != "win32":
            raise RuntimeError("当前平台不支持自动更新")
        manager = _safe_create_update_manager()
        if manager is None:
            raise RuntimeError("当前运行环境不支持 Velopack 更新")
        if str(os.environ.get("SURVEYCONTROLLER_UPDATE_TEST_MODE", "") or "").strip() == "1":
            restart_args = ["--ci-update-probe"]
            os.environ["SURVEYCONTROLLER_UPDATE_TEST_RESTARTED"] = "1"
            manager.wait_exit_then_apply_updates(update_info, silent=True, restart=True, restart_args=restart_args)
            return
        manager.apply_updates_and_exit(update_info)


def show_update_notification(gui) -> None:
    """显示更新通知（如果 gui.update_info 存在）。"""
    if not getattr(gui, "update_info", None):
        return

    info = gui.update_info
    log_action(
        "UPDATE",
        "show_update_notification",
        "update_dialog",
        "update",
        result="shown",
        payload={"version": info.get("version", "unknown")},
    )
    release_notes_preview = _preview_release_notes(info.get("release_notes", ""), 300)
    manual_release_url = str(info.get("manual_release_url", "") or "").strip() or f"{GITHUB_RELEASE_TAG_URL}/v{info.get('version', '')}"
    manual_only = bool(info.get("manual_only", False))
    action_line = "是否要立即前往发布页下载更新？" if manual_only else "是否要立即下载更新？"
    msg = (
        f"检测到新版本 v{info['version']}\n"
        f"当前版本 v{info['current_version']}\n\n"
        f"发布说明:\n{release_notes_preview}\n\n"
        f"如果自动更新失败，可手动前往发布页下载安装：\n{manual_release_url}\n\n"
        f"{action_line}"
    )

    if gui.show_confirm_dialog("检查到更新", msg):
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="accepted",
            payload={"version": info.get("version", "unknown")},
        )
        if manual_only:
            webbrowser.open(manual_release_url)
        else:
            perform_update(gui)
    else:
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="declined",
            payload={"version": info.get("version", "unknown")},
        )


def perform_update(
    gui,
    *,
    on_progress: Optional[Callable[[int, int, float], None]] = None,
) -> None:
    """执行更新：下载 Velopack 更新包并等待应用安装。"""
    if not getattr(gui, "update_info", None):
        return

    update_payload = gui.update_info
    velopack_update = update_payload.get("_velopack_update")
    if velopack_update is None:
        gui.downloadFailed.emit("当前更新信息无效，请稍后重试")
        return
    try:
        package_size = int(update_payload.get("package_size", 0) or 0)
    except Exception:
        package_size = 0

    gui._download_cancelled = False

    def update_progress(percent: int, total: int, speed: float = 0) -> None:
        normalized_percent = max(0, min(100, int(percent or 0)))
        if package_size > 0:
            downloaded = min(package_size, int(package_size * normalized_percent / 100))
            total_value = package_size
        else:
            downloaded = normalized_percent
            total_value = 100
        try:
            gui._emit_download_progress(downloaded, total_value, speed)
        except Exception:
            logging.info("GUI 进度回调失败", exc_info=True)
        if on_progress is not None:
            try:
                on_progress(downloaded, total_value, speed)
            except Exception:
                logging.info("更新进度回调失败", exc_info=True)

    gui.downloadStarted.emit()

    def do_update() -> None:
        try:
            UpdateManager.download_update(velopack_update, progress_callback=update_progress)
            if getattr(gui, "_download_cancelled", False):
                return
            if on_progress is not None:
                on_progress(100, 100, 0.0)
            gui.downloadFinished.emit(update_payload)
        except Exception as exc:
            if not getattr(gui, "_download_cancelled", False):
                logging.error("更新过程中出错: %s", exc)
                gui.downloadFailed.emit(f"更新失败：{exc}")

    Thread(target=do_update, daemon=True, name="VelopackUpdateDownload").start()


__all__ = [
    "UpdateManager",
    "_preview_release_notes",
    "perform_update",
    "show_update_notification",
]
