"""Python sidecar 启动入口。

用法：
    python -m src.server                    # 自动分配端口，浏览器可访问
    python -m src.server --port 8765        # 指定端口
    python -m src.server --parent-pid 1234  # Tauri 外壳传入，父进程退出后自动结束

启动成功后会输出（stdout，便于 Rust 侧读取）：
    NCMP_PORT=<端口>
    NCMP_TOKEN=<访问令牌>
同时在 data/sidecar.json 写入一份信息，供其他进程发现。
"""
import argparse
import json
import os
import sys
import threading
import time

from ..store.history import PROJECT_ROOT
from .app import VERSION, create_server, get_web_dir

INFO_PATH = os.path.join(PROJECT_ROOT, "data", "sidecar.json")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _watch_parent(server, parent_pid: int, interval: float = 2.0) -> None:
    """父进程（Tauri 外壳）退出后关闭服务，避免残留进程。"""
    while True:
        time.sleep(interval)
        if not _pid_alive(parent_pid):
            print(f"[sidecar] parent process {parent_pid} exited, shutting down", flush=True)
            server.shutdown()
            return


def _write_info(port: int, token: str, parent_pid: int) -> None:
    try:
        os.makedirs(os.path.dirname(INFO_PATH), exist_ok=True)
        with open(INFO_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "version": VERSION,
                "port": port,
                "token": token,
                "pid": os.getpid(),
                "parent_pid": parent_pid,
                "started_at": time.time(),
                "url": f"http://127.0.0.1:{port}/",
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[sidecar] failed to write info file: {e}", flush=True)


def _remove_info() -> None:
    try:
        if os.path.exists(INFO_PATH):
            os.remove(INFO_PATH)
    except Exception:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ncmp-server", description="ncmp Web 服务 (sidecar)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=0, help="监听端口，0 表示自动分配")
    parser.add_argument("--token", default=None, help="访问令牌，默认随机生成")
    parser.add_argument("--parent-pid", type=int, default=0, help="父进程 PID，父进程退出后自动结束")
    parser.add_argument("--open-browser", action="store_true", help="启动后打开浏览器")
    parser.add_argument("--print-token", action="store_true", help="在控制台显示访问令牌")
    args = parser.parse_args(argv)

    web_dir = get_web_dir()
    if not os.path.isdir(web_dir):
        print(f"[sidecar] warning: web assets dir not found: {web_dir}", flush=True)

    server = create_server(args.host, args.port, args.token)
    port = server.server_address[1]
    token = server.token

    _write_info(port, token, args.parent_pid)

    # 供 Rust 外壳及其它进程读取的关键信息
    print(f"NCMP_PORT={port}", flush=True)
    print(f"NCMP_TOKEN={token}", flush=True)
    print(f"NCMP_URL=http://{args.host}:{port}/", flush=True)
    if args.print_token:
        print(f"[sidecar] ncmp {VERSION} listening on http://{args.host}:{port}/", flush=True)
        print(f"[sidecar] token: {token}", flush=True)

    if args.open_browser:
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}/?token={token}")
        except Exception:
            pass

    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(server, args.parent_pid),
                         daemon=True).start()

    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        _remove_info()
        print("[sidecar] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
