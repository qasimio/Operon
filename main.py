# main.py — Operon v3
import sys
from tui.app import OperonUI

if __name__ == "__main__":
    try:
        OperonUI().run()
    except KeyboardInterrupt:
        print("\nOperon shut down safely.")
        sys.exit(0)
