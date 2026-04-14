# COMP2322 Multi-threaded Web Server

This project implements a multi-threaded HTTP web server in Python using the `socket` and `threading` modules instead of `HTTPServer`.

## Features

- Multi-threaded server: one worker thread per client connection
- Supports `GET` for both text and image files
- Supports `HEAD`
- Returns only the required status codes:
  - `200 OK`
  - `400 Bad Request`
  - `403 Forbidden`
  - `404 File Not Found`
  - `304 Not Modified`
- Handles `Last-Modified` and `If-Modified-Since`
- Handles both persistent and non-persistent connections through the `Connection` header
- Writes one log record per request to `logs/server.log`

## Project Structure

- `server.py`: simple launcher
- `src/web_server.py`: main web server implementation
- `www/`: sample files served by the server
- `tests/test_web_server.py`: automated tests
- `docs/report_template.md`: report scaffold that can be adapted for submission

## Requirements

- Python 3.9 or above

## Run the Server

From the project root:

```bash
python3 server.py --host 127.0.0.1 --port 8080
```

Optional arguments:

```bash
python3 server.py --host 127.0.0.1 --port 8080 --root www --log logs/server.log --timeout 5
```

Then open:

- `http://127.0.0.1:8080/`
- `http://127.0.0.1:8080/about.txt`
- `http://127.0.0.1:8080/sample.png`

## Demo Commands

Use the following commands to demonstrate the required features:

```bash
curl -i http://127.0.0.1:8080/
curl -i http://127.0.0.1:8080/about.txt
curl -I http://127.0.0.1:8080/about.txt
curl -i http://127.0.0.1:8080/sample.png --output /tmp/sample.png
curl -i http://127.0.0.1:8080/missing.html
```

For the remaining report scenarios:

### 7. `403 Forbidden`

```bash
curl --path-as-is -i http://127.0.0.1:8080/../secret.txt
```

### 8. `400 Bad Request`

```bash
curl -i -X POST http://127.0.0.1:8080/
```

### 9. `304 Not Modified`

```bash
curl -i -H "If-Modified-Since: Wed, 31 Dec 2099 23:59:59 GMT" http://127.0.0.1:8080/about.txt
```

### 10. Persistent connection example

Use a single `curl` command with two URLs and `Connection: keep-alive` so the client can reuse the same socket. Run with `-v` to show the connection reuse in the terminal output.

```bash
curl -v --http1.0 -H "Connection: keep-alive" \
  http://127.0.0.1:8080/about.txt \
  http://127.0.0.1:8080/
```

### 11. Non-persistent connection example

Use `Connection: close` so the server closes the connection after each response. With two URLs, `curl` will need to create a new connection for the second request.

```bash
curl -v --http1.0 -H "Connection: close" \
  http://127.0.0.1:8080/about.txt \
  http://127.0.0.1:8080/
```

### 12. Log file output

First send a request with `curl`:

```bash
curl -i http://127.0.0.1:8080/about.txt
```

Then check that a new record was written to `logs/server.log`.

## Run Tests

```bash
python3 -m unittest discover -s tests -v
```

## Log Output

The server writes records like the following into `logs/server.log`:

```text
2026-04-13 14:00:00 UTC | client=localhost (127.0.0.1) | file=/about.txt | status=200 OK
```
