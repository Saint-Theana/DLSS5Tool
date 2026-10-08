"""Open the real realtime UI for a bounded visual acceptance session."""
import argparse
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dlss5tool.realtime_ui import RealtimeWindow

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, default=90)
args = parser.parse_args()
root = tk.Tk()
root.withdraw()
workspace = RealtimeWindow(root)

def finish():
    workspace.close()
    root.destroy()

root.after(args.seconds * 1000, finish)
root.mainloop()
