"""``python -m telegram_parser`` — альтернативний спосіб запуску."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
