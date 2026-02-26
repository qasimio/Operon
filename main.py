# main.py — Operon v3
import sys
from tui.app import OperonUI

print("hello operon")
if __name__ == "__main__":
    try:
        print("hello operon")
        OperonUI().run()
    except KeyboardInterrupt:
        print("\nOperon shut down safely.")
        sys.exit(0)
