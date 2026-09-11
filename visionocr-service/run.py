"""Runs the visionocr-service bound explicitly to 127.0.0.1 and this Mac's
Tailscale IPv4 address -- never to 0.0.0.0/all interfaces.

uvicorn's CLI only accepts a single --host, so this builds the listening
sockets by hand and hands them to uvicorn.Server.run(sockets=...).
"""

import socket
import subprocess
import sys

import uvicorn

from app.main import app

PORT = 8090


def tailscale_ip() -> str:
    result = subprocess.run(
        ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"`tailscale ip -4` failed: {result.stderr.strip()}")
    return result.stdout.strip()


def bound_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    return sock


def main() -> None:
    hosts = ["127.0.0.1", tailscale_ip()]
    sockets = [bound_socket(host, PORT) for host in hosts]
    print(f"visionocr-service listening on {[s.getsockname() for s in sockets]}", file=sys.stderr)

    config = uvicorn.Config(app, log_level="info")
    server = uvicorn.Server(config)
    server.run(sockets=sockets)


if __name__ == "__main__":
    main()
