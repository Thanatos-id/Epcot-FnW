"""Serve the built pages locally, opening on the studio.

    python tools/data_ledger/serve.py          # http://localhost:8123
    python tools/data_ledger/serve.py 9000

Serves docs/ exactly as GitHub Pages would, so the studio, the ledger, the
survey and the client feed all resolve the same relative paths they do in
production. The one difference: `/` opens the studio rather than the
ledger's index.html, because the studio is what this is run to see.

Resolves docs/ from this file's own location rather than from wherever it is
started, which is what the launch configuration it replaced got wrong - it
pointed at a session's scratch folder, served an empty directory, and looked
exactly like a broken page.
"""

import functools
import http.server
import socketserver
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
LANDING = "/studio.html"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", LANDING)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        # A page load is ~5 MB of inline photos in one request; per-request
        # logging is noise. Errors still surface through send_error.
        pass


class Server(socketserver.ThreadingTCPServer):
    # Restarting right after a stop would otherwise fail on a port the OS is
    # still holding in TIME_WAIT.
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    if not (DOCS / "studio.html").exists():
        sys.exit(f"{DOCS / 'studio.html'} is missing - run tools/data_ledger/build_artifact.py first")
    handler = functools.partial(Handler, directory=str(DOCS))
    with Server(("", port), handler) as httpd:
        print(f"serving {DOCS} at http://localhost:{port}{LANDING}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
