"""A very small HTTP server, for both Python and MicroPython."""
import json
import socket


def read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(512)
        if not chunk or len(data) > 8192:
            return None
        data += chunk
    split = data.index(b"\r\n\r\n")
    lines = data[:split].decode().split("\r\n")
    body = data[split + 4:]
    words = lines[0].split(" ")
    if len(words) < 2:
        return None
    length = 0
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    while len(body) < length:
        chunk = conn.recv(512)
        if not chunk:
            break
        body += chunk
    return words[0], words[1].split("?")[0], body.decode()


def respond(conn, body, content_type="application/json", status="200 OK"):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    conn.sendall(
        ("HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
         "Cache-Control: no-store\r\nConnection: close\r\n\r\n" % (status, content_type, len(body))).encode()
    )
    conn.sendall(body)


def serve(target, port, host, handle):
    """Answer requests forever, one at a time, with handle(connection, target)."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(socket.getaddrinfo(host, port)[0][-1])
    server.listen(4)
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            continue
        try:
            conn.settimeout(2)
            handle(conn, target)
        except Exception:
            pass
        finally:
            conn.close()
