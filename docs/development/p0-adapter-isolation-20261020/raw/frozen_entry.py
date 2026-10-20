"""Verification fixture for the same early worker dispatch as the app launcher."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from dlss5tool.adapter_probe import dispatch
    if dispatch():
        raise SystemExit(0)
    raise SystemExit(3)
