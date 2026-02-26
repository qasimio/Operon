# main.py
import sys
from tui.app import OperonUI
import json

if __name__ == "__main__":
    try:
        app = OperonUI()
        app.run()
    except KeyboardInterrupt:
        print("\nOperon shut down safely.")
        sys.exit(0)
