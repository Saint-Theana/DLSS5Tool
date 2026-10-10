"""Launch with python -m dlss5tool."""
import multiprocessing


if __name__ == '__main__':
    multiprocessing.freeze_support()
    from dlss5tool.gui import cli
    cli()
