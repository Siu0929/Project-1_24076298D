COMP2322 Project Report

Cover Page

Name:
Student ID:
GitHub Link:

1. Project Summary

This project implements a multi-threaded HTTP web server in Python using low-level socket programming. Each client connection is handled by a separate thread, and the server supports GET, HEAD, conditional requests with If-Modified-Since, and both persistent and non-persistent connections.

2. Design and Implementation

2.1 Overall Architecture

- The main thread creates a TCP listening socket and accepts client connections.
- A new worker thread is created for each client connection.
- Each worker thread reads one or more HTTP requests from the same socket depending on the Connection header.
- Requested files are read from the www/ document root.
- Every request is appended to logs/server.log.

2.2 Supported HTTP Features

- GET for text files
- GET for image files
- HEAD
- 200 OK
- 400 Bad Request
- 403 Forbidden
- 404 File Not Found
- 304 Not Modified
- Last-Modified
- If-Modified-Since
- Connection: keep-alive
- Connection: close

2.3 Error Handling

- Malformed requests or unsupported methods return 400 Bad Request.
- Requests outside the document root return 403 Forbidden.
- Missing files return 404 File Not Found.
- Unmodified resources return 304 Not Modified.

3. Execution Demonstration

Insert screenshots and short explanations for the following:

1. Starting the server
2. GET /
3. GET /about.txt
4. GET /sample.png
5. HEAD /about.txt
6. 404 File Not Found
7. 403 Forbidden
8. 400 Bad Request
9. 304 Not Modified
10. Persistent connection example
11. Non-persistent connection example
12. Log file output

4. Sample Commands Used

Use the following sample commands in your report:

python3 server.py --host 127.0.0.1 --port 8080
curl -i http://127.0.0.1:8080/
curl -i http://127.0.0.1:8080/about.txt
curl -I http://127.0.0.1:8080/about.txt
curl -i http://127.0.0.1:8080/missing.html
curl -i -H "If-Modified-Since: Wed, 31 Dec 2099 23:59:59 GMT" http://127.0.0.1:8080/about.txt

To show 400 Bad Request, use:

python3 - <<'PY'
import socket

with socket.create_connection(("127.0.0.1", 8080)) as sock:
    sock.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\n\r\n")
    print(sock.recv(4096).decode("iso-8859-1"))
PY

5. Log File

Paste a meaningful excerpt from logs/server.log here after running the demonstrations.

6. Conclusion

This project demonstrates how HTTP services can be built from raw TCP sockets and threads without using a high-level web server framework. The implementation satisfies the required request methods, status codes, cache validation behavior, connection handling, and logging requirements.
