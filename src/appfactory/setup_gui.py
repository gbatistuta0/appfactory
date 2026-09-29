"""Local credentials page for AppFactory — stdlib only.

Secrets must never pass through the model, so the `setup_credentials` MCP tool (and `appfactory setup --browser`)
starts this tiny server on 127.0.0.1 (random port) and opens one page where the human types keys. Every request
needs a random token (query `t` for the page, `X-Setup-Token` header for the API), Host/Origin must be loopback,
secret values are never sent back to the page (only set/missing), and the server stops after Save or 30 idle minutes.
Config is written through config.save_config.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import cli
from . import config as cfg

PAGE = Path(__file__).parent / "data" / "setup.html"
IDLE_SECONDS = 30 * 60
MAX_BODY = 1_000_000


def service_keys(name: str) -> list[str]:
    spec = cfg.SERVICES[name]
    return spec["keys"] + spec.get("optional_keys", [])


def credential_services(names: list[str] | None) -> list[str]:
    """Services whose credential form is shown: the given ones (must be enabled) or every enabled one with keys."""
    c = cfg.load_config()
    if "services" not in c:
        raise ValueError("no services chosen yet: call setup_services first")
    enabled = cfg.enabled_services(c)
    if names is None:
        names = [n for n in cfg.SERVICES if n in enabled]
    for n in names:
        if n not in cfg.SERVICES:
            raise ValueError(f"unknown service {n!r}")
        if n not in enabled:
            raise ValueError(f"service {n!r} is disabled: call setup_services(enable=[{n!r}]) first")
    out = [n for n in cfg.SERVICES if n in names and service_keys(n)]
    if not out:
        raise ValueError("none of these services needs credentials")
    return out


# ---------------------------------------------------------------- page logic
def build_state(services: list[str]) -> dict[str, Any]:
    c = cfg.load_config()
    cards = []
    for name in services:
        spec = cfg.SERVICES[name]
        fields = []
        for key in service_keys(name):
            secret = key in cfg.SECRET_KEYS
            f: dict[str, Any] = {"key": key, "label": cfg.KNOWN_KEYS.get(key, key), "secret": secret,
                                 "optional": key in spec.get("optional_keys", []),
                                 "file": key.endswith("filepath"), "set": bool(c.get(key))}
            if not secret:  # plain values are shown so a re-run is editable; secrets never leave the server
                f["value"] = str(c.get(key, "") or "")
            fields.append(f)
        cards.append({"name": name, "description": spec["description"], "help": cfg.SERVICE_HELP.get(name, ""),
                      "fields": fields})
    return {"config_path": str(cfg.CONFIG_PATH), "services": cards,
            "approvals": c.get("approvals", "required") != "off",
            "approvals_warning": " ".join(cli.APPROVALS_LINES)}


def apply_save(payload: dict[str, Any], services: list[str]) -> dict[str, Any]:
    """Write the shown credential keys (+ approvals). Empty secret = keep the saved value; empty plain value clears."""
    allowed = {k for n in services for k in service_keys(n)}
    values = payload.get("values", {})
    if not isinstance(values, dict):
        raise ValueError("values must be an object")
    c = cfg.load_config()
    for key, val in values.items():
        if key not in allowed:
            raise ValueError(f"unexpected key {key}")
        if not isinstance(val, str) or len(val) > 4096:
            raise ValueError(f"invalid value for {key}")
        val = val.strip()
        if not val:
            if key not in cfg.SECRET_KEYS:
                c.pop(key, None)
            continue
        c[key] = os.path.expanduser(val) if key.endswith("filepath") else val
    if "approvals" in payload:
        c["approvals"] = "required" if payload["approvals"] else "off"
    cfg.save_config(c)
    return {"ok": True, "config_path": str(cfg.CONFIG_PATH)}


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "AppFactorySetup"
    server: "SetupServer"

    def log_message(self, *args: Any) -> None:  # silence request logging (stdout is the MCP channel)
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(cfg.scrub(obj), ensure_ascii=False).encode())

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _guard(self, query_token: bool = False) -> bool:
        """Host, Origin, then token. Sends the error itself and returns False when the request is refused."""
        self.server.touch()
        if self.headers.get("Host", "") not in self._allowed_hosts():
            self._json(403, {"error": "bad host"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in self._allowed_hosts()}:
            self._json(403, {"error": "bad origin"})
            return False
        token = self.headers.get("X-Setup-Token", "")
        if query_token and not token:
            token = parse_qs(urlsplit(self.path).query).get("t", [""])[0]
        if not token or not secrets.compare_digest(token, self.server.token):
            self._json(401, {"error": "missing or wrong token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            if self._guard(query_token=True):
                self._send(200, PAGE.read_bytes(), "text/html")
        elif path == "/api/state":
            if self._guard():
                self._json(200, build_state(self.server.services))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                return self._json(413, {"error": "too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            self._json(200, self._post(urlsplit(self.path).path, body))
        except KeyError:
            self._json(404, {"error": "not found"})
        except (ValueError, TypeError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        if path == "/api/save":
            return apply_save(body, self.server.services)
        if path == "/api/check-file":
            p = str(body.get("path", ""))
            return {"exists": bool(p) and Path(os.path.expanduser(p)).is_file()}
        if path == "/api/test-asc":
            return cli.asc_check(cfg.load_config(), self.server.offline)
        if path == "/api/finish":
            self.server.finished = True
            threading.Timer(0.3, self.server.shutdown).start()
            return {"ok": True}
        raise KeyError(path)


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, services: list[str], offline: bool = False, idle_seconds: float = IDLE_SECONDS) -> None:
        super().__init__(("127.0.0.1", 0), Handler)  # port 0 = random free port, loopback only
        self.token = secrets.token_urlsafe(32)
        self.services = services
        self.offline = offline
        self.idle_seconds = idle_seconds
        self.finished = False
        self._last = time.monotonic()
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?t={self.token}"

    def touch(self) -> None:
        self._last = time.monotonic()

    def _watchdog(self) -> None:
        while not self._stop.wait(min(5.0, max(self.idle_seconds / 4, 0.05))):
            if time.monotonic() - self._last > self.idle_seconds:
                threading.Thread(target=self.shutdown, daemon=True).start()
                return

    def serve(self) -> None:
        threading.Thread(target=self._watchdog, daemon=True).start()
        try:
            self.serve_forever()
        finally:
            self._stop.set()
            self.server_close()


def _open(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 — headless / no display
        return False


_active: SetupServer | None = None


def start(services: list[str] | None = None, offline: bool = False, open_browser: bool = True) -> dict[str, Any]:
    """Start the credentials page in the background (MCP tool path). Returns at once with the URL."""
    global _active
    shown = credential_services(services)
    if not PAGE.exists():
        raise ValueError("setup page missing from the package")
    if _active is not None:  # only one page at a time
        threading.Thread(target=_active.shutdown, daemon=True).start()
    srv = _active = SetupServer(shown, offline=offline)
    threading.Thread(target=srv.serve, daemon=True).start()
    opened = _open(srv.url) if open_browser else False
    return {"ok": True, "url": srv.url, "browser_opened": opened, "services": shown,
            "message": "Ask the user to fill the form in the browser (open the url if it did not open by itself), "
                       "then call setup_status()."}


def run(offline: bool = False, open_browser: bool = True) -> int:
    """`appfactory setup --browser`: serve the page in the foreground until Save."""
    try:
        srv = SetupServer(credential_services(None), offline=offline)
    except ValueError as e:
        print(f"{e}\nRun `appfactory setup` (terminal) to choose services first.")
        return 2
    print(f"AppFactory credentials page (127.0.0.1 only). Open this URL if it does not open by itself:\n\n  {srv.url}\n")
    if not (open_browser and _open(srv.url)):
        print("(could not open a browser here; copy the URL above, or forward the port over SSH)")
    try:
        srv.serve()
    except KeyboardInterrupt:
        print("\naborted")
        return 130
    print("Saved." if srv.finished else "Closed without saving.")
    return 0
