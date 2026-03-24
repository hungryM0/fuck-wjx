#!/usr/bin/env python
"""
fuck-wjx CLI 独立入口脚本

使用方法:
    python fuck-wjx-cli.py --help
    python fuck-wjx-cli.py run --url <url> --count 10
"""

import sys
from wjx.cli.main import main

if __name__ == "__main__":
    sys.exit(main())