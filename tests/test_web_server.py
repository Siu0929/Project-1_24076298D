"""Regression tests for the multi-threaded web server."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.web_server import HTTPRequest, ThreadedWebServer, format_http_date


class WebServerTests(unittest.TestCase):
    """Exercise the server's request parsing and response generation logic."""

    def setUp(self) -> None:
        """Create an isolated document root and server instance for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "www"
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = Path(self.temp_dir.name) / "server.log"
        self.server = ThreadedWebServer(
            host="127.0.0.1",
            port=8080,
            document_root=self.root,
            log_path=self.log_path,
        )

        (self.root / "about.txt").write_text("hello world\n", encoding="utf-8")
        (self.root / "index.html").write_text("<h1>home</h1>\n", encoding="utf-8")

    def tearDown(self) -> None:
        """Remove temporary files created for the current test case."""
        self.temp_dir.cleanup()

    def test_parse_valid_request(self) -> None:
        """A well-formed request line and headers should be parsed correctly."""
        request = self.server.parse_request(
            b"GET /about.txt HTTP/1.1\r\nHost: localhost\r\nConnection: close"
        )
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.target, "/about.txt")
        self.assertEqual(request.headers["host"], "localhost")

    def test_head_request_has_no_body(self) -> None:
        """HEAD responses must keep metadata while omitting the response body."""
        request = HTTPRequest(method="HEAD", target="/about.txt", version="HTTP/1.1", headers={})
        response, _ = self.server.build_response(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"")
        self.assertEqual(response.headers["Content-Length"], str((self.root / "about.txt").stat().st_size))

    def test_missing_file_returns_404(self) -> None:
        """Requests for absent files should return a 404 response."""
        request = HTTPRequest(method="GET", target="/missing.txt", version="HTTP/1.1", headers={})
        response, _ = self.server.build_response(request)
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_returns_403(self) -> None:
        """Path traversal attempts must be rejected as forbidden."""
        request = HTTPRequest(method="GET", target="/../secret.txt", version="HTTP/1.1", headers={})
        response, _ = self.server.build_response(request)
        self.assertEqual(response.status_code, 403)

    def test_if_modified_since_returns_304(self) -> None:
        """Fresh cached copies should trigger a 304 Not Modified response."""
        file_path = self.root / "about.txt"
        future_time = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc) + timedelta(days=1)
        request = HTTPRequest(
            method="GET",
            target="/about.txt",
            version="HTTP/1.1",
            headers={"if-modified-since": format_http_date(future_time)},
        )

        response, _ = self.server.build_response(request)
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.body, b"")

    def test_keep_alive_rules(self) -> None:
        """The server should apply the expected connection reuse defaults."""
        http11 = HTTPRequest(method="GET", target="/", version="HTTP/1.1", headers={})
        http10 = HTTPRequest(
            method="GET",
            target="/",
            version="HTTP/1.0",
            headers={"connection": "keep-alive"},
        )
        self.assertTrue(self.server.should_keep_alive(http11))
        self.assertTrue(self.server.should_keep_alive(http10))


if __name__ == "__main__":
    # Allow the test module to be executed directly during development.
    unittest.main()
