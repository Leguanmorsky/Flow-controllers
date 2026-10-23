"""Starts Flow controllers from code, e.g. with Run in VS Code (same as run.bat).

    python main.py           start screen: connect to the instruments or test mode
    python main.py --sim     straight into test mode (no gas flows)
    python main.py COM9      connect to the instruments on COM9 straight away
"""

import sys

from flowapp.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
