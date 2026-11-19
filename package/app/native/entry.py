"""Report missing native dependencies, or enter the normal installer/desktop."""
import html
import importlib.util
from http.server import BaseHTTPRequestHandler
import os
from pathlib import Path
import shutil
from socketserver import UnixStreamServer
import sys

here = Path(__file__).resolve().parent
missing = [command for command in ("dpkg-deb", "Xtigervnc", "xauth", "mcookie", "dbus-run-session")
           if not shutil.which(command)]
if not importlib.util.find_spec("aiohttp"):
    missing.append("python3-aiohttp")
if sys.version_info < (3, 9):
    missing.append("Python 3.9+")
if not missing:
    os.execv(sys.executable, [sys.executable, str(here / "bootstrap.py")])

class Diagnostics(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("X-Trim-Userid") != "1000":
            self.send_error(403)
            return
        if self.path.split("?")[0] != "/app/fnos-qq/":
            self.send_error(404)
            return
        items = "".join("<li>" + html.escape(name) + "</li>" for name in missing)
        content = ("<!doctype html><meta charset=utf-8><title>QQ</title>"
                   "<main style='font:16px/1.6 system-ui;max-width:38em;margin:7vh auto;padding:20px'>"
                   "<h1>QQ 启动所需组件</h1><p>飞牛已启动独立应用进程。当前缺少以下组件，"
                   "QQ 客户端尚未启动。</p><ul>" + items + "</ul></main>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass

socket_path = Path(os.environ["TRIM_APPDEST"]) / "app.sock"
socket_path.unlink(missing_ok=True)
with UnixStreamServer(str(socket_path), Diagnostics) as server:
    server.serve_forever()
