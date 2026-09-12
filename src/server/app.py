"""HTTP API 服务：为 Web 前端（Tauri 外壳内 / 浏览器）提供本地接口。

设计要点：
  - 仅监听 127.0.0.1，随机端口（0 = 自动分配）
  - 所有 /api/* 请求需要启动时生成的 token（通过头部 X-NCMP-Token 或 ?token= 传递）
  - 实时日志通过 SSE（/api/events）推送
  - 同一套服务既可作为 Tauri sidecar，也可直接 `python -m src.server` 在浏览器中使用
"""
import json
import mimetypes
import os
import queue
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from ..store.history import HISTORY_DIR, PROJECT_ROOT, RunHistory
from ..utils.paths import get_project_root
from .hub import EventHub
from .runner import TaskRunner

CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "setting.json")
EXAMPLE_PATH = os.path.join(CONFIG_DIR, "setting.example.json")

VERSION = "2.0.0"

DEFAULT_FIELDS = {
    "wait_time_min": 15,
    "wait_time_max": 20,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 465,
    "score": 3,
}

TEXT_FIELDS = (
    "Cookie_MUSIC_U", "Cookie___csrf", "notify_email", "email_password",
    "smtp_server", "netease_phone", "netease_password",
    "netease_md5_password", "gh_token", "gh_repo",
)


def get_web_dir() -> str:
    """返回前端静态资源目录（兼容 PyInstaller 打包后的 sidecar）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "web")
    return os.path.join(get_project_root(), "web")


# ----------------------------------------------------------------------
# 配置读写
# ----------------------------------------------------------------------
PLACEHOLDER_PREFIXES = ("YOUR_", "您的")


def is_cookie_configured(config: Dict) -> bool:
    """判断配置中是否填写了可用的 Cookie（排除示例占位符）。"""
    value = str(config.get("Cookie_MUSIC_U") or "").strip()
    if not value:
        return False
    for prefix in PLACEHOLDER_PREFIXES:
        if value.startswith(prefix):
            return False
    return True


def read_config() -> Dict:
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def normalize_config(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """校验并规范化配置，返回 (配置, 错误信息)。"""
    if not isinstance(data, dict):
        return None, "配置格式错误"

    music_u = str(data.get("Cookie_MUSIC_U") or "").strip()
    csrf = str(data.get("Cookie___csrf") or "").strip()
    if not music_u or not csrf:
        return None, "MUSIC_U Cookie 与 __csrf Token 为必填项"

    try:
        wait_min = float(data.get("wait_time_min", DEFAULT_FIELDS["wait_time_min"]))
        wait_max = float(data.get("wait_time_max", DEFAULT_FIELDS["wait_time_max"]))
        score = int(data.get("score", DEFAULT_FIELDS["score"]))
        smtp_port = int(data.get("smtp_port", DEFAULT_FIELDS["smtp_port"]))
    except (TypeError, ValueError):
        return None, "等待时间 / 评分策略 / SMTP 端口必须为数字"

    if wait_min <= 0 or wait_max <= 0:
        return None, "等待时间必须大于 0"
    if wait_min > wait_max:
        return None, "最短等待时间不能大于最长等待时间"
    if score not in (1, 2, 3, 4):
        return None, "评分策略必须为 1-4"
    if not (1 <= smtp_port <= 65535):
        return None, "SMTP 端口必须在 1-65535 之间"

    result = dict(data)
    result["Cookie_MUSIC_U"] = music_u
    result["Cookie___csrf"] = csrf
    result["wait_time_min"] = wait_min
    result["wait_time_max"] = wait_max
    result["score"] = score
    result["smtp_port"] = smtp_port
    for key in TEXT_FIELDS:
        if key in data:
            result[key] = data.get(key)
    return result, None


def write_config(data: Dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# HTTP 服务
# ----------------------------------------------------------------------
class NcmpHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, token: str):
        super().__init__(address, handler)
        self.token = token
        self.hub = EventHub()
        self.runner = TaskRunner(self.hub)
        self.started_at = time.time()


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"ncmp/{VERSION}"

    # ---------------- 基础工具 ----------------
    @property
    def app(self) -> NcmpHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args) -> None:  # 静默访问日志
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-NCMP-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) or {}
        except Exception:
            return {}

    def _authorized(self, query: Dict[str, list]) -> bool:
        token = self.headers.get("X-NCMP-Token") or (query.get("token") or [""])[0]
        return bool(token) and secrets.compare_digest(token, self.app.token)

    # ---------------- 路由 ----------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            if not self._authorized(query):
                self._send_json({"error": "unauthorized"}, 401)
                return
            self._handle_api_get(path, query)
            return

        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if not self._authorized(query):
            self._send_json({"error": "unauthorized"}, 401)
            return
        self._handle_api_post(path)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if not self._authorized(query):
            self._send_json({"error": "unauthorized"}, 401)
            return
        if path.startswith("/api/history/"):
            run_id = urllib.parse.unquote(path[len("/api/history/"):])
            ok = RunHistory.delete(run_id)
            self._send_json({"deleted": ok})
            return
        self._send_json({"error": "not found"}, 404)

    # ---------------- GET /api/* ----------------
    def _handle_api_get(self, path: str, query: Dict[str, list]) -> None:
        if path == "/api/meta":
            self._send_json({
                "version": VERSION,
                "project_root": PROJECT_ROOT,
                "config_path": CONFIG_PATH,
                "config_exists": os.path.exists(CONFIG_PATH),
                "history_dir": HISTORY_DIR,
                "frozen": bool(getattr(sys, "frozen", False)),
                "started_at": self.app.started_at,
            })
            return

        if path == "/api/state":
            cfg = read_config()
            self._send_json({
                "state": self.app.runner.snapshot(),
                "has_cookie": is_cookie_configured(cfg),
                "score": cfg.get("score", DEFAULT_FIELDS["score"]),
            })
            return

        if path == "/api/config":
            self._send_json({"config": read_config(),
                             "config_exists": os.path.exists(CONFIG_PATH)})
            return

        if path == "/api/events":
            self._serve_sse()
            return

        if path == "/api/history":
            self._send_json({"records": RunHistory.load_all()})
            return

        if path.startswith("/api/history/"):
            rest = urllib.parse.unquote(path[len("/api/history/"):])
            if rest.endswith("/raw"):
                run_id = rest[:-len("/raw")]
                log = RunHistory.load_log(run_id)
                body = log.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
            record = RunHistory.load(rest)
            if record is None:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json({"record": record, "log": RunHistory.load_log(rest)})
            return

        self._send_json({"error": "not found"}, 404)

    # ---------------- POST /api/* ----------------
    def _handle_api_post(self, path: str) -> None:
        body = self._read_json()

        if path == "/api/config":
            current = read_config()
            merged = dict(current)
            merged.update(body or {})
            data, error = normalize_config(merged)
            if error:
                self._send_json({"ok": False, "error": error}, 400)
                return
            try:
                write_config(data)
            except Exception as e:
                self._send_json({"ok": False, "error": f"写入失败: {e}"}, 500)
                return
            self._send_json({"ok": True, "config": data})
            return

        if path == "/api/validate":
            music_u = str(body.get("Cookie_MUSIC_U") or "").strip()
            csrf = str(body.get("Cookie___csrf") or "").strip()
            if not music_u or not csrf:
                cfg = read_config()
                music_u = music_u or str(cfg.get("Cookie_MUSIC_U") or "")
                csrf = csrf or str(cfg.get("Cookie___csrf") or "")
            if self.app.runner.busy:
                self._send_json({"ok": False, "error": "已有任务在运行"}, 409)
                return
            result = self.app.runner.validate(music_u, csrf)
            self._send_json({"ok": True, **result})
            return

        if path == "/api/run":
            started = self.app.runner.start_pipeline()
            self._send_json({"ok": started, "error": None if started else "已有任务在运行"},
                            200 if started else 409)
            return

        if path == "/api/refresh-cookie":
            started = self.app.runner.start_refresh()
            self._send_json({"ok": started, "error": None if started else "已有任务在运行"},
                            200 if started else 409)
            return

        if path == "/api/cancel":
            ok = self.app.runner.cancel()
            self._send_json({"ok": ok, "error": None if ok else "当前没有运行中的任务"},
                            200 if ok else 409)
            return

        if path == "/api/open-path":
            target = str(body.get("target") or "config_dir")
            mapping = {
                "config_dir": CONFIG_DIR,
                "config_file": CONFIG_PATH,
                "logs": HISTORY_DIR,
            }
            target_path = mapping.get(target, CONFIG_DIR)
            if not os.path.exists(target_path):
                self._send_json({"ok": False, "error": "路径不存在"}, 404)
                return
            try:
                if sys.platform == "win32":
                    os.startfile(target_path)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", target_path])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", target_path])
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/shutdown":
            self._send_json({"ok": True})
            threading.Thread(target=self.app.shutdown, daemon=True).start()
            return

        self._send_json({"error": "not found"}, 404)

    # ---------------- SSE ----------------
    def _serve_sse(self) -> None:
        q = self.app.hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self._cors()
        self.end_headers()

        def send_chunk(payload: str) -> None:
            data = payload.encode("utf-8")
            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
            self.wfile.flush()

        def send_event(event: str, data: Dict) -> None:
            send_chunk(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")

        try:
            send_event("state", self.app.runner.snapshot())
            last_ping = time.time()
            while True:
                try:
                    event = q.get(timeout=1.0)
                    send_event("message", event)
                except queue.Empty:
                    now = time.time()
                    if now - last_ping >= 15:
                        send_chunk(": ping\n\n")
                        last_ping = now
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            self.app.hub.unsubscribe(q)
            self.close_connection = True

    # ---------------- 静态资源 ----------------
    def _serve_static(self, path: str) -> None:
        web_dir = get_web_dir()
        rel = "index.html" if path in ("/", "") else urllib.parse.unquote(path.lstrip("/"))
        rel = rel.replace("\\", "/")
        if ".." in rel.split("/"):
            self._send_json({"error": "forbidden"}, 403)
            return
        full = os.path.join(web_dir, *rel.split("/"))
        if not os.path.isfile(full):
            # 单页应用回退
            full = os.path.join(web_dir, "index.html")
            if not os.path.isfile(full):
                self._send_json({"error": "web assets not found", "web_dir": web_dir}, 404)
                return
            rel = "index.html"

        content_type = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript",
                                                               "application/json"):
            content_type += "; charset=utf-8"

        try:
            with open(full, "rb") as f:
                body = f.read()
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
            return

        # 向前端注入端口与 token（浏览器直连模式）
        if rel.endswith(".html"):
            text = body.decode("utf-8")
            inject = (
                "<script>"
                f"window.__NCMP_TOKEN__={json.dumps(self.app.token)};"
                f"window.__NCMP_PORT__={self.server.server_address[1]};"
                "window.__NCMP_EMBEDDED__=true;"
                "</script>"
            )
            text = text.replace("<!--NCMP_BOOTSTRAP-->", inject)
            body = text.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = "127.0.0.1", port: int = 0,
                  token: Optional[str] = None) -> NcmpHTTPServer:
    token = token or secrets.token_urlsafe(24)
    return NcmpHTTPServer((host, port), ApiHandler, token)
