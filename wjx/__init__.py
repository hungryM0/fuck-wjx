"""WJX 包精简入口。"""

from wjx.utils.app.version import __VERSION__


def main():
    from wjx.main import main as _main

    return _main()


__all__ = [
    "main",
    "__VERSION__",
]
