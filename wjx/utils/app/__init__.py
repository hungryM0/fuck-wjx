"""应用配置与版本信息"""
from wjx.utils.app.config import (
    DEFAULT_HTTP_HEADERS,
    USER_AGENT_PRESETS,
    BROWSER_PREFERENCE,
    QUESTION_TYPE_LABELS,
    DEFAULT_FILL_TEXT,
)
from wjx.utils.app.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO
from wjx.utils.app.runtime_paths import (
    _get_runtime_directory,
    _get_resource_path,
)

__all__ = [
    "DEFAULT_HTTP_HEADERS",
    "USER_AGENT_PRESETS",
    "BROWSER_PREFERENCE",
    "QUESTION_TYPE_LABELS",
    "DEFAULT_FILL_TEXT",
    "__VERSION__",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "_get_runtime_directory",
    "_get_resource_path",
]
