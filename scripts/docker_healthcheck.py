"""Image healthcheck: API 探活；worker/beat 不监听 8000 则视为健康。"""

from __future__ import annotations

import socket
import sys
import urllib.request


def main() -> int:
    sock = socket.socket()
    sock.settimeout(2)
    bound = sock.connect_ex(("127.0.0.1", 8000)) == 0
    sock.close()
    if not bound:
        return 0
    urllib.request.urlopen("http://127.0.0.1:8000/public/health", timeout=3)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(1)
