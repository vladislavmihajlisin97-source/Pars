#!/usr/bin/env python3
"""Pars — парсер телеграм-каналів.

Точка входу: python pars.py <команда> [опції]
Довідка: python pars.py --help
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telegram_parser.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
