"""LoL Coach – start with:  python main.py   (autostart uses: pythonw main.py --hidden)"""
import socket
import sys

from lolcoach.ui import App


def single_instance_lock():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 47811))
    except OSError:
        return None
    return sock


if __name__ == "__main__":
    lock = single_instance_lock()
    if lock is None:
        sys.exit(0)  # already running
    App(start_hidden="--hidden" in sys.argv).run()
