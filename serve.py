#!/usr/bin/env python3
"""Static server for the satellite app + a caching TLE proxy.

The browser fetches /tle?group=NAME instead of hitting CelesTrak directly.
This server fetches each group from CelesTrak at most once per TTL, caches it
on disk, and serves the cached copy otherwise -- so reloading the page or
switching catalogs never trips CelesTrak's rate limiter (HTTP 403). If a fresh
fetch fails, the last good copy on disk is served instead.

Usage:  python3 serve.py [port]        (default 8723)
"""
import http.server
import os
import socketserver
import sys
import time
import urllib.request
from urllib.parse import urlparse, parse_qs

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8723
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, ".tlecache")
TTL = 2 * 3600  # seconds; CelesTrak asks clients not to refetch a group within ~2h

# Only allow the catalogs the app exposes (also prevents using us as an open proxy).
ALLOWED = {"active", "visual", "stations", "starlink", "gps-ops", "science"}

os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_tle(group):
    """Return (text, source) where source describes cache freshness."""
    path = os.path.join(CACHE_DIR, group + ".tle")
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TTL
    if fresh:
        age = int((time.time() - os.path.getmtime(path)) / 60)
        with open(path, encoding="utf-8") as f:
            return f.read(), f"cache ({age}m old)"

    url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
    req = urllib.request.Request(url, headers={"User-Agent": "satellites-overhead/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        if "\n1 " not in ("\n" + text):  # sanity: looks like TLE data
            raise ValueError("response did not look like TLE data")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return text, "celestrak (fresh)"
    except Exception as e:
        if os.path.exists(path):  # serve stale rather than fail
            age = int((time.time() - os.path.getmtime(path)) / 60)
            with open(path, encoding="utf-8") as f:
                return f.read(), f"stale cache ({age}m old; live fetch failed: {e})"
        raise


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/tle":
            group = (parse_qs(parsed.query).get("group", ["active"])[0]).lower()
            if group not in ALLOWED:
                self.send_error(400, "unknown group")
                return
            try:
                text, source = fetch_tle(group)
            except Exception as e:
                self.send_error(502, f"could not obtain TLE data: {e}")
                return
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-TLE-Source", source)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            sys.stderr.write(f"[tle] {group}: {source}, {len(body)} bytes\n")
            return
        super().do_GET()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {ROOT} on http://localhost:{PORT}  (TLE proxy at /tle?group=active)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
