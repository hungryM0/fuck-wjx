from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from software.update import updater


class UpdateHelperTests:
    def test_check_updates_returns_unsupported_on_macos(self) -> None:
        with (
            patch.object(updater.sys, "platform", "darwin"),
            patch.object(updater, "__VERSION__", "4.0.0"),
        ):
            result = updater.UpdateManager.check_updates()
        assert result == {
            "has_update": False,
            "status": "unsupported",
            "current_version": "4.0.0",
        }

    def test_preview_release_notes_strips_markdown_and_truncates(self) -> None:
        preview = updater._preview_release_notes('# 标题\n\n---\n\n**加粗** 和 ~~删除线~~\n\n* 列表项\n\n普通段落', 18)
        assert preview == '标题\n\n加粗 和 删除线\n- 列表项\n...'

    def test_check_updates_uses_velopack_feed_when_manager_missing(self) -> None:
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "__VERSION__", "3.1.1"),
            patch.object(updater, "_safe_create_update_manager", return_value=None),
            patch.object(
                updater,
                "_fetch_latest_velopack_feed_release",
                return_value={"Version": "3.1.2", "Type": "Full"},
            ),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["has_update"] is True
        assert result["version"] == "3.1.2"
        assert result["manual_only"] is True
        assert result["manual_release_url"].endswith("/v3.1.2")

    def test_check_updates_returns_unknown_when_feed_fallback_missing(self) -> None:
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=None),
            patch.object(updater, "_fetch_latest_velopack_feed_release", return_value=None),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "unknown"
        assert result["has_update"] is False

    def test_check_updates_returns_preview_when_feed_latest_is_older(self) -> None:
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=None),
            patch.object(
                updater,
                "_fetch_latest_velopack_feed_release",
                return_value={"Version": "3.1.0", "Type": "Full"},
            ),
            patch.object(updater, "__VERSION__", "3.1.2b1"),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "preview"
        assert result["has_update"] is False
        assert result["latest_version"] == "3.1.0"

    def test_check_updates_returns_latest_when_no_release_available(self) -> None:
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = None
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_latest_velopack_feed_release", return_value={"Version": "3.1.2", "Type": "Full"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result == {
            "has_update": False,
            "status": "latest",
            "current_version": "3.1.2",
            "latest_version": "3.1.2",
            "release_notes": "",
        }

    def test_check_updates_returns_outdated_when_release_exists(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="修复一堆破事", Size=123456)
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["has_update"] is True
        assert result["version"] == "3.2.0"
        assert result["release_notes"] == "修复一堆破事"
        assert result["package_size"] == 123456

    def test_check_updates_falls_back_to_github_release_body_when_velopack_notes_missing(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="", NotesHtml="")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_github_release_by_tag", return_value={"body": "GitHub 里的发行说明"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["release_notes"] == "GitHub 里的发行说明"

    def test_check_updates_falls_back_to_release_list_when_tag_lookup_missing(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="", NotesHtml="")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_github_release_by_tag", return_value=None),
            patch.object(updater, "_fetch_github_release_from_list", return_value={"body": "列表里的发行说明"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["release_notes"] == "列表里的发行说明"

    def test_check_updates_keeps_empty_notes_when_github_release_body_missing(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="", NotesHtml="")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_github_release_by_tag", return_value=None),
            patch.object(updater, "_fetch_github_release_from_list", return_value=None),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["release_notes"] == ""

    def test_check_updates_returns_preview_when_local_version_is_newer(self) -> None:
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.4"
        manager.check_for_updates.return_value = None
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_latest_velopack_feed_release", return_value={"Version": "3.1.3", "Type": "Full"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "preview"
        assert result["current_version"] == "3.1.4"
        assert result["latest_version"] == "3.1.3"

    def test_fetch_latest_velopack_feed_release_uses_highest_full_version(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "Assets": [
                {"Version": "3.1.3", "Type": "Delta"},
                {"Version": "3.1.2", "Type": "Full"},
                {"Version": "3.1.3", "Type": "Full"},
            ]
        }
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "VELOPACK_FEED_URL", "https://dl.example/surveycontroller/win/stable/"),
            patch.object(updater, "VELOPACK_CHANNEL", "stable"),
            patch.object(updater.http_client, "get", return_value=response),
        ):
            result = updater._fetch_latest_velopack_feed_release()
        assert result == {"Version": "3.1.3", "Type": "Full"}

    def test_check_updates_returns_unknown_when_manager_raises(self) -> None:
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.side_effect = RuntimeError("network down")
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "unknown"

    def test_download_update_reports_progress(self) -> None:
        manager = MagicMock()
        progress_values: list[tuple[int, int, float]] = []
        def on_progress(downloaded: int, total: int, speed: float) -> None:
            progress_values.append((downloaded, total, speed))

        def fake_download(_update_info, callback):
            callback(5)
            callback(100)

        manager.download_updates.side_effect = fake_download
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
        ):
            assert updater.UpdateManager.download_update(object(), progress_callback=on_progress)
        assert progress_values == [(5, 100, 0.0), (100, 100, 0.0)]

    def test_apply_downloaded_update_uses_apply_updates_and_exit(self) -> None:
        manager = MagicMock()
        update_info = object()
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
        ):
            updater.UpdateManager.apply_downloaded_update(update_info)
        manager.apply_updates_and_exit.assert_called_once_with(update_info)

    def test_apply_downloaded_update_uses_wait_exit_then_apply_updates_in_ci_probe_mode(self) -> None:
        manager = MagicMock()
        update_info = object()
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.dict(updater.os.environ, {"SURVEYCONTROLLER_UPDATE_TEST_MODE": "1"}, clear=False),
        ):
            updater.UpdateManager.apply_downloaded_update(update_info)
        manager.wait_exit_then_apply_updates.assert_called_once_with(
            update_info,
            silent=True,
            restart=True,
            restart_args=["--ci-update-probe"],
        )

    def test_build_github_update_result_returns_unknown_when_version_cannot_be_parsed(self) -> None:
        with (
            patch.object(updater, "__VERSION__", "3.1.2"),
            patch.object(updater, "_fetch_latest_github_release", return_value={"tag_name": "???", "body": "说明"}),
        ):
            result = updater._build_github_update_result("3.1.2")
        assert result["status"] == "unknown"
        assert result["latest_version"] == "???"

    def test_normalize_release_helpers_and_resolve_notes_cover_html_and_tag_fallback(self) -> None:
        asset = SimpleNamespace(NotesMarkdown="", NotesHtml="<p>HTML 说明</p>")
        assert updater._normalize_release_release_notes(asset) == "<p>HTML 说明</p>"
        assert updater._normalize_release_tag("3.2.0") == "v3.2.0"
        assert updater._normalize_release_tag("v3.2.0") == "v3.2.0"
        assert updater._normalize_release_tag("") == ""

        update_info = SimpleNamespace(TargetFullRelease=asset)
        with patch.object(updater, "_fetch_github_release_by_tag", return_value=None), patch.object(
            updater,
            "_fetch_github_release_from_list",
            return_value={"body": "列表说明"},
        ):
            assert updater._resolve_release_notes(update_info, "3.2.0") == "<p>HTML 说明</p>"

        update_info_empty = SimpleNamespace(TargetFullRelease=SimpleNamespace(NotesMarkdown="", NotesHtml=""))
        with patch.object(updater, "_fetch_github_release_by_tag", return_value={"body": "GitHub 说明"}):
            assert updater._resolve_release_notes(update_info_empty, "3.2.0") == "GitHub 说明"

    def test_build_remote_version_result_covers_unknown_latest_preview_and_outdated(self) -> None:
        assert updater._build_remote_version_result("3.1.2", "???", release_notes="说明") == {
            "has_update": False,
            "status": "unknown",
            "current_version": "3.1.2",
            "latest_version": "???",
            "release_notes": "说明",
        }
        assert updater._build_remote_version_result("3.1.2", "3.1.2", release_notes="说明") == {
            "has_update": False,
            "status": "latest",
            "current_version": "3.1.2",
            "latest_version": "3.1.2",
            "release_notes": "说明",
        }
        assert updater._build_remote_version_result("3.1.3", "3.1.2")["status"] == "preview"
        outdated = updater._build_remote_version_result("3.1.2", "3.1.4")
        assert outdated["status"] == "outdated"
        assert outdated["manual_release_url"].endswith("/v3.1.4")

    def test_get_all_releases_returns_empty_when_request_fails(self) -> None:
        with patch.object(updater.http_client, "get", side_effect=RuntimeError("boom")):
            assert updater.UpdateManager.get_all_releases() == []

    def test_get_all_releases_normalizes_payload(self) -> None:
        response = MagicMock()
        response.json.return_value = [
            {
                "tag_name": "v3.2.0",
                "name": "稳定版",
                "body": "修复说明",
                "published_at": "2026-05-08T00:00:00Z",
                "prerelease": False,
                "html_url": "https://example.com/release",
            }
        ]
        with patch.object(updater.http_client, "get", return_value=response):
            result = updater.UpdateManager.get_all_releases()
        assert result == [
            {
                "version": "3.2.0",
                "name": "稳定版",
                "body": "修复说明",
                "published_at": "2026-05-08T00:00:00Z",
                "prerelease": False,
                "html_url": "https://example.com/release",
            }
        ]

    def test_show_update_notification_opens_browser_for_manual_only_update(self) -> None:
        gui = SimpleNamespace(
            update_info={
                "version": "3.2.0",
                "current_version": "3.1.2",
                "release_notes": "修了几个坑",
                "manual_only": True,
                "manual_release_url": "https://example.com/release",
            },
            show_confirm_dialog=MagicMock(return_value=True),
        )
        with patch.object(updater, "log_action"), patch.object(updater.webbrowser, "open") as open_mock:
            updater.show_update_notification(gui)
        open_mock.assert_called_once_with("https://example.com/release")

    def test_perform_update_emits_invalid_message_when_payload_missing_velopack_update(self) -> None:
        gui = SimpleNamespace(
            update_info={"version": "3.2.0"},
            downloadFailed=SimpleNamespace(emit=MagicMock()),
        )
        updater.perform_update(gui)
        gui.downloadFailed.emit.assert_called_once()

    def test_perform_update_reports_progress_completion_and_failure(self) -> None:
        class _Thread:
            def __init__(self, *, target, **_kwargs) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        gui = SimpleNamespace(
            update_info={"version": "3.2.0", "package_size": 400, "_velopack_update": object()},
            _emit_download_progress=MagicMock(),
            downloadStarted=SimpleNamespace(emit=MagicMock()),
            downloadFinished=SimpleNamespace(emit=MagicMock()),
            downloadFailed=SimpleNamespace(emit=MagicMock()),
        )
        reported: list[tuple[int, int, float]] = []

        def _download_success(_payload, *, progress_callback):
            progress_callback(25, 100, 12.5)
            progress_callback(75, 100, 9.5)
            return True

        with patch.object(updater, "Thread", _Thread), patch.object(updater.UpdateManager, "download_update", side_effect=_download_success):
            updater.perform_update(gui, on_progress=lambda d, t, s: reported.append((d, t, s)))

        gui.downloadStarted.emit.assert_called_once()
        gui.downloadFinished.emit.assert_called_once_with(gui.update_info)
        assert reported == [(100, 400, 12.5), (300, 400, 9.5), (100, 100, 0.0)]

        cancelled_gui = SimpleNamespace(
            update_info={"version": "3.2.0", "_velopack_update": object()},
            _emit_download_progress=MagicMock(),
            downloadStarted=SimpleNamespace(emit=MagicMock()),
            downloadFinished=SimpleNamespace(emit=MagicMock()),
            downloadFailed=SimpleNamespace(emit=MagicMock()),
        )

        def _download_cancel(_payload, *, progress_callback):
            progress_callback(50, 100, 0.0)
            cancelled_gui._download_cancelled = True
            return True

        with patch.object(updater, "Thread", _Thread), patch.object(updater.UpdateManager, "download_update", side_effect=_download_cancel):
            updater.perform_update(cancelled_gui)

        cancelled_gui.downloadFinished.emit.assert_not_called()

        failed_gui = SimpleNamespace(
            update_info={"version": "3.2.0", "_velopack_update": object()},
            _emit_download_progress=MagicMock(),
            downloadStarted=SimpleNamespace(emit=MagicMock()),
            downloadFinished=SimpleNamespace(emit=MagicMock()),
            downloadFailed=SimpleNamespace(emit=MagicMock()),
        )
        with patch.object(updater, "Thread", _Thread), patch.object(updater.UpdateManager, "download_update", side_effect=RuntimeError("boom")):
            updater.perform_update(failed_gui)
        failed_gui.downloadFailed.emit.assert_called_once()
