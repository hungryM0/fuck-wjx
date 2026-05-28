from __future__ import annotations

import importlib
from pathlib import Path

from software.ui.pages import community as community_module
from software.ui.widgets import config_drawer as config_drawer_module


def test_config_ignores_dotenv_file_and_reads_process_env(monkeypatch, tmp_path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("CONTACT_API_URL=https://dotenv.example\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CONTACT_API_URL", raising=False)

    import software.app.config as config_module

    reloaded = importlib.reload(config_module)
    assert reloaded.CONTACT_API_URL == "https://bot.hungrym0.top"

    monkeypatch.setenv("CONTACT_API_URL", "https://env.example")
    reloaded = importlib.reload(config_module)
    assert reloaded.CONTACT_API_URL == "https://env.example"


def test_config_drawer_opens_config_directory_via_qdesktopservices(monkeypatch, tmp_path, qtbot) -> None:
    opened: list[str] = []
    monkeypatch.setattr(config_drawer_module, "get_user_config_directory", lambda: str(tmp_path))
    monkeypatch.setattr(
        config_drawer_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    drawer = config_drawer_module.ConfigDrawer()
    qtbot.addWidget(drawer)
    drawer._open_config_folder()

    assert [Path(path) for path in opened] == [tmp_path]


def test_community_page_opens_qr_image_via_qdesktopservices(monkeypatch, tmp_path, qtbot) -> None:
    opened: list[str] = []
    image_path = tmp_path / "community_qr.jpg"
    image_path.write_bytes(b"jpg")
    monkeypatch.setattr(community_module, "get_assets_directory", lambda: str(tmp_path))
    monkeypatch.setattr(
        community_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    page = community_module.CommunityPage()
    qtbot.addWidget(page)
    page._open_qq_qr_image()

    assert [Path(path) for path in opened] == [image_path]
