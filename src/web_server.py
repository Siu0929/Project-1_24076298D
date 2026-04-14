"""Core HTTP server implementation for the COMP2322 assignment.

The server accepts TCP connections directly with ``socket``, parses a limited
subset of HTTP/1.0 and HTTP/1.1 requests, and serves files from a configured
document root using one worker thread per client connection.
"""

from __future__ import annotations

import argparse
import email.utils
import mimetypes
import os
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlsplit


SERVER_NAME = "COMP2322PythonServer/1.0"
BUFFER_SIZE = 4096
MAX_HEADER_SIZE = 64 * 1024
SUPPORTED_METHODS = {"GET", "HEAD"}
DEFAULT_TIMEOUT_SECONDS = 5.0
STATUS_TEXT = {
    200: "OK",
    304: "Not Modified",
    400: "Bad Request",
    403: "Forbidden",
    404: "File Not Found",
}


class HTTPRequestError(Exception):
    """Raised when the incoming request is malformed."""


@dataclass
class HTTPRequest:
    """Represents the parsed start line and headers of one HTTP request."""

    method: str
    target: str
    version: str
    headers: Dict[str, str]


@dataclass
class HTTPResponse:
    """Represents a complete HTTP response ready to be sent to the client."""

    version: str
    status_code: int
    headers: Dict[str, str]
    body: bytes
    keep_alive: bool

    def to_bytes(self) -> bytes:
        """Serialize the response into the wire format expected by HTTP clients."""
        status_line = f"{self.version} {self.status_code} {STATUS_TEXT[self.status_code]}\r\n"
        header_lines = "".join(f"{name}: {value}\r\n" for name, value in self.headers.items())
        return (status_line + header_lines + "\r\n").encode("iso-8859-1") + self.body


def format_http_date(dt: datetime) -> str:
    """Format a ``datetime`` using the RFC 7231 HTTP-date representation."""
    return email.utils.format_datetime(dt.astimezone(timezone.utc), usegmt=True)


def parse_http_date(value: str) -> Optional[datetime]:
    """Parse an HTTP date string and normalize it to UTC."""
    try:
        return email.utils.parsedate_to_datetime(value).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


class ThreadedWebServer:
    """Serve static files over HTTP using a thread per accepted client."""

    def __init__(
        self,
        host: str,
        port: int,
        document_root: Path,
        log_path: Path,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host
        self.port = port
        self.document_root = document_root.resolve()
        self.log_path = log_path
        self.timeout_seconds = timeout_seconds
        self._socket: Optional[socket.socket] = None
        self._shutdown = threading.Event()
        self._log_lock = threading.Lock()

    def serve_forever(self) -> None:
        """Bind the listening socket and accept clients until shutdown is requested."""
        self.document_root.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            self._socket = server_socket

            print(f"Serving {self.document_root} on http://{self.host}:{self.port}")

            while not self._shutdown.is_set():
                try:
                    client_socket, client_address = server_socket.accept()
                except OSError:
                    break

                # Each connection is handled independently so one slow client
                # does not block other requests from being served.
                worker = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_address),
                    daemon=True,
                )
                worker.start()

    def shutdown(self) -> None:
        """Request shutdown and close the listening socket if it exists."""
        self._shutdown.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def handle_client(self, client_socket: socket.socket, client_address: Tuple[str, int]) -> None:
        """Serve one client socket, supporting multiple requests on keep-alive connections."""
        client_socket.settimeout(self.timeout_seconds)
        remaining = b""

        with client_socket:
            while not self._shutdown.is_set():
                try:
                    request, remaining = self.read_request(client_socket, remaining)
                    if request is None:
                        break

                    response, requested_resource = self.build_response(request)
                    client_socket.sendall(response.to_bytes())
                    self.write_log(client_address[0], requested_resource, response.status_code)

                    # Stop after one response when the connection should not be reused.
                    if not response.keep_alive:
                        break
                except (socket.timeout, ConnectionResetError, BrokenPipeError):
                    break
                except HTTPRequestError:
                    # Malformed requests receive a 400 response and the
                    # connection is closed to keep parser state simple.
                    response = self.build_error_response(
                        status_code=400,
                        version="HTTP/1.1",
                        keep_alive=False,
                    )
                    try:
                        client_socket.sendall(response.to_bytes())
                    except OSError:
                        pass
                    self.write_log(client_address[0], "-", 400)
                    break

    def read_request(
        self, client_socket: socket.socket, buffered_data: bytes
    ) -> Tuple[Optional[HTTPRequest], bytes]:
        """Read until the end of the header block and return one parsed request."""
        data = buffered_data

        while b"\r\n\r\n" not in data:
            chunk = client_socket.recv(BUFFER_SIZE)
            if not chunk:
                if not data:
                    return None, b""
                raise HTTPRequestError("Incomplete request headers.")

            data += chunk
            if len(data) > MAX_HEADER_SIZE:
                raise HTTPRequestError("Request headers are too large.")

        # Leave any bytes after the header terminator in ``remaining`` so the
        # next request on the same connection can reuse them.
        raw_headers, remaining = data.split(b"\r\n\r\n", 1)
        request = self.parse_request(raw_headers)
        return request, remaining

    def parse_request(self, raw_headers: bytes) -> HTTPRequest:
        """Validate the request line and headers for the supported HTTP subset."""
        try:
            header_text = raw_headers.decode("iso-8859-1")
        except UnicodeDecodeError as error:
            raise HTTPRequestError("Invalid request encoding.") from error

        lines = header_text.split("\r\n")
        if not lines or not lines[0]:
            raise HTTPRequestError("Missing request line.")

        request_line = lines[0].split()
        if len(request_line) != 3:
            raise HTTPRequestError("Malformed request line.")

        method, target, version = request_line
        method = method.upper()

        if method not in SUPPORTED_METHODS:
            raise HTTPRequestError("Unsupported method.")
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            raise HTTPRequestError("Unsupported HTTP version.")

        headers: Dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                raise HTTPRequestError("Malformed header line.")
            name, value = line.split(":", 1)
            name = name.strip().lower()
            if not name:
                raise HTTPRequestError("Empty header name.")
            headers[name] = value.strip()

        return HTTPRequest(method=method, target=target, version=version, headers=headers)

    def build_response(self, request: HTTPRequest) -> Tuple[HTTPResponse, str]:
        """Create the correct HTTP response for a parsed request."""
        keep_alive = self.should_keep_alive(request)
        requested_resource = urlsplit(request.target).path or "/"

        try:
            file_path = self.resolve_file_path(requested_resource)
        except PermissionError:
            return (
                self.build_error_response(403, request.version, keep_alive=False),
                requested_resource,
            )

        if not file_path.exists() or not file_path.is_file():
            return self.build_error_response(404, request.version, keep_alive), requested_resource

        if not os.access(file_path, os.R_OK):
            return self.build_error_response(403, request.version, keep_alive=False), requested_resource

        # HTTP conditional requests can avoid sending the body when the client
        # already has a fresh enough cached copy.
        last_modified = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).replace(
            microsecond=0
        )
        if_modified_since = request.headers.get("if-modified-since")
        if if_modified_since:
            condition_time = parse_http_date(if_modified_since)
            if condition_time is None:
                return self.build_error_response(400, request.version, keep_alive=False), requested_resource
            if last_modified <= condition_time.replace(microsecond=0):
                headers = self.build_common_headers(
                    keep_alive=keep_alive,
                    content_length=0,
                    content_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
                    last_modified=last_modified,
                )
                return (
                    HTTPResponse(
                        version=request.version,
                        status_code=304,
                        headers=headers,
                        body=b"",
                        keep_alive=keep_alive,
                    ),
                    requested_resource,
                )

        # ``HEAD`` returns the same metadata as ``GET`` but without the body.
        body = file_path.read_bytes() if request.method == "GET" else b""
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        headers = self.build_common_headers(
            keep_alive=keep_alive,
            content_length=file_path.stat().st_size,
            content_type=content_type,
            last_modified=last_modified,
        )
        return (
            HTTPResponse(
                version=request.version,
                status_code=200,
                headers=headers,
                body=body,
                keep_alive=keep_alive,
            ),
            requested_resource,
        )

    def resolve_file_path(self, request_path: str) -> Path:
        """Resolve a request path safely within the configured document root."""
        path = unquote(request_path)
        if path == "/":
            path = "/index.html"

        relative_path = path.lstrip("/")
        candidate = (self.document_root / relative_path).resolve()

        # Reject traversal attempts such as ``/../secret.txt`` that would escape
        # the document root after path normalization.
        if self.document_root not in candidate.parents and candidate != self.document_root:
            raise PermissionError("Path traversal is forbidden.")

        if candidate.is_dir():
            candidate = (candidate / "index.html").resolve()

        if self.document_root not in candidate.parents and candidate != self.document_root:
            raise PermissionError("Path traversal is forbidden.")

        return candidate

    def build_common_headers(
        self,
        *,
        keep_alive: bool,
        content_length: int,
        content_type: str,
        last_modified: Optional[datetime] = None,
    ) -> Dict[str, str]:
        """Build headers shared by both success and error responses."""
        headers = {
            "Date": format_http_date(datetime.now(tz=timezone.utc)),
            "Server": SERVER_NAME,
            "Content-Length": str(content_length),
            "Content-Type": content_type,
            "Connection": "keep-alive" if keep_alive else "close",
        }
        if last_modified is not None:
            headers["Last-Modified"] = format_http_date(last_modified)
        return headers

    def build_error_response(self, status_code: int, version: str, keep_alive: bool) -> HTTPResponse:
        """Return a simple HTML error page for supported error status codes."""
        message = STATUS_TEXT[status_code]
        body = (
            "<html><head><title>{0}</title></head>"
            "<body><h1>{0}</h1><p>The request could not be completed.</p></body></html>"
        ).format(message).encode("utf-8")
        headers = self.build_common_headers(
            keep_alive=keep_alive,
            content_length=len(body),
            content_type="text/html; charset=utf-8",
        )
        return HTTPResponse(
            version=version,
            status_code=status_code,
            headers=headers,
            body=body,
            keep_alive=keep_alive,
        )

    def should_keep_alive(self, request: HTTPRequest) -> bool:
        """Apply the default keep-alive rules for HTTP/1.0 and HTTP/1.1."""
        connection_header = request.headers.get("connection", "").lower()
        if request.version == "HTTP/1.1":
            return connection_header != "close"
        return connection_header == "keep-alive"

    def write_log(self, client_ip: str, requested_file: str, status_code: int) -> None:
        """Append one formatted request record to the server log."""
        try:
            host_name = socket.gethostbyaddr(client_ip)[0]
        except (socket.herror, socket.gaierror):
            host_name = client_ip

        record = (
            f"{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"client={host_name} ({client_ip}) | "
            f"file={requested_file} | "
            f"status={status_code} {STATUS_TEXT[status_code]}\n"
        )
        with self._log_lock:
            with self.log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(record)


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line interface used to configure the server."""
    parser = argparse.ArgumentParser(description="Multi-threaded HTTP web server for COMP2322.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind the server to.")
    parser.add_argument("--port", type=int, default=8080, help="Port number to listen on.")
    parser.add_argument(
        "--root",
        default="www",
        help="Document root used to serve files.",
    )
    parser.add_argument(
        "--log",
        default="logs/server.log",
        help="Path to the request log file.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Idle timeout in seconds for each client connection.",
    )
    return parser


def main() -> None:
    """Parse command-line arguments and start the web server."""
    parser = build_argument_parser()
    args = parser.parse_args()

    server = ThreadedWebServer(
        host=args.host,
        port=args.port,
        document_root=Path(args.root),
        log_path=Path(args.log),
        timeout_seconds=args.timeout,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
