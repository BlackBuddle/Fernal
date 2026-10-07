"""Frozen entry script: PyInstaller runs this instead of `python -m fernal`.

Same job as the __main__ block of fernal/__main__.py. Differences: a windowed (no console) build has
sys.stdout / sys.stderr set to None, so the flush is guarded.
"""
import os
import sys

from fernal.__main__ import main

if __name__ == "__main__":
    rc = main()
    # The state is already saved; leave right away so a weather request still in flight cannot keep the
    # process alive after quit (see fernal/__main__.py).
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    os._exit(rc)
