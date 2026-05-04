# -*- coding: utf-8 -*-
"""兼容旧启动方式的入口文件。"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / 'src'
sys.path.insert(0, str(SRC_DIR))

from ironmail.main import main  # noqa: E402


if __name__ == '__main__':
    main()
