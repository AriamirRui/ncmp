// 网易云音乐合伙人 · Tauri 外壳
//
// 职责：
//   1. 创建桌面窗口并在其中加载 Web 前端（../web）
//   2. 以 sidecar 方式启动 Python 后端（ncmp-server），分配随机端口与访问令牌
//   3. 把端口/令牌通过 `server_info` 命令交给前端
//   4. 应用退出时结束 sidecar 进程，避免残留

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde::Serialize;
use tauri::{Emitter, RunEvent, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const SIDECAR_STEM: &str = "ncmp-server";

#[cfg(all(windows, target_arch = "x86_64"))]
const TARGET_TRIPLE: &str = "x86_64-pc-windows-msvc";
#[cfg(all(windows, target_arch = "aarch64"))]
const TARGET_TRIPLE: &str = "aarch64-pc-windows-msvc";
#[cfg(all(not(windows), target_arch = "x86_64"))]
const TARGET_TRIPLE: &str = "x86_64-unknown-linux-gnu";

#[derive(Clone, Serialize, Default)]
struct ServerInfo {
    port: u16,
    token: String,
}

#[derive(Default)]
struct AppState {
    child: Mutex<Option<Child>>,
    info: Mutex<Option<ServerInfo>>,
}

/// 前端调用：获取 sidecar 的端口与令牌（未就绪时返回 null，前端会重试）
#[tauri::command]
fn server_info(state: State<'_, Arc<AppState>>) -> Option<ServerInfo> {
    state.info.lock().ok().and_then(|g| g.clone())
}

/// 按优先级查找 sidecar 可执行文件
fn resolve_sidecar() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(custom) = std::env::var("NCMP_SIDECAR") {
        if !custom.trim().is_empty() {
            candidates.push(PathBuf::from(custom));
        }
    }

    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(PathBuf::from));

    if let Some(dir) = &exe_dir {
        // 安装后：与主程序同目录
        candidates.push(dir.join(format!("{SIDECAR_STEM}.exe")));
        candidates.push(dir.join(format!("{SIDECAR_STEM}-{TARGET_TRIPLE}.exe")));
        // 开发模式：target/debug 同级查找
        candidates.push(dir.join("binaries").join(format!("{SIDECAR_STEM}-{TARGET_TRIPLE}.exe")));
        if let Some(parent) = dir.parent().and_then(|p| p.parent()) {
            candidates.push(parent.join("binaries").join(format!("{SIDECAR_STEM}-{TARGET_TRIPLE}.exe")));
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("binaries").join(format!("{SIDECAR_STEM}-{TARGET_TRIPLE}.exe")));
        candidates.push(cwd.join(format!("{SIDECAR_STEM}.exe")));
        // 工程根目录下的构建产物目录
        candidates.push(
            cwd.parent()
                .unwrap_or(&cwd)
                .join("dist-sidecar")
                .join(format!("{SIDECAR_STEM}.exe")),
        );
    }

    candidates.into_iter().find(|p| p.is_file())
}

fn spawn_sidecar(state: Arc<AppState>, app: tauri::AppHandle) {
    let path = match resolve_sidecar() {
        Some(p) => p,
        None => {
            let msg = format!("未找到 Python 后端程序（{SIDECAR_STEM}.exe），请先运行 build_sidecar.bat");
            eprintln!("[ncmp] {msg}");
            let _ = app.emit("sidecar-error", msg);
            return;
        }
    };
    eprintln!("[ncmp] sidecar: {}", path.display());

    let mut command = Command::new(&path);
    command
        .arg("--port")
        .arg("0")
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = match command.spawn() {
        Ok(c) => c,
        Err(e) => {
            let msg = format!("启动 Python 后端失败：{e}");
            eprintln!("[ncmp] {msg}");
            let _ = app.emit("sidecar-error", msg);
            return;
        }
    };

    // 读取 stdout：解析 NCMP_PORT / NCMP_TOKEN
    if let Some(stdout) = child.stdout.take() {
        let state_reader = state.clone();
        let app_reader = app.clone();
        thread::spawn(move || {
            let mut port: Option<u16> = None;
            let mut token = String::new();
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let line = line.trim().to_string();
                if let Some(value) = line.strip_prefix("NCMP_PORT=") {
                    port = value.trim().parse::<u16>().ok();
                } else if let Some(value) = line.strip_prefix("NCMP_TOKEN=") {
                    token = value.trim().to_string();
                }
                if let (Some(p), true) = (port, !token.is_empty()) {
                    let info = ServerInfo { port: p, token: token.clone() };
                    if let Ok(mut guard) = state_reader.info.lock() {
                        *guard = Some(info.clone());
                    }
                    eprintln!("[ncmp] backend ready on 127.0.0.1:{}", p);
                    let _ = app_reader.emit("sidecar-ready", info);
                    break;
                }
            }
        });
    }

    // stderr 转发到外壳日志，便于排查
    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("[backend] {line}");
            }
        });
    }

    if let Ok(mut guard) = state.child.lock() {
        *guard = Some(child);
    }

    // 监视进程退出：通知前端 + 清理句柄
    let state_watch = state.clone();
    let app_watch = app.clone();
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(800));
        let exited = {
            match state_watch.child.lock() {
                Ok(mut guard) => match guard.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(status)) => Some(status.code()),
                        Ok(None) => None,
                        Err(_) => Some(None),
                    },
                    None => return,
                },
                Err(_) => return,
            }
        };
        if let Some(code) = exited {
            eprintln!("[ncmp] backend exited: {code:?}");
            if let Ok(mut guard) = state_watch.child.lock() {
                *guard = None;
            }
            let _ = app_watch.emit("sidecar-exit", code);
            return;
        }
    });
}

/// 结束 sidecar 进程树。
///
/// PyInstaller onefile 会派生出「引导进程 + 真正的 Python 进程」两个进程，
/// 单独 child.kill() 只会结束引导进程，因此在 Windows 上用 taskkill /T 结束整棵树。
fn kill_sidecar_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        let pid = child.id().to_string();
        let _ = Command::new("taskkill")
            .args(["/PID", pid.as_str(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn main() {
    let state = Arc::new(AppState::default());
    let state_for_setup = state.clone();
    let state_for_exit = state.clone();

    let app = tauri::Builder::default()
        .manage(state_for_setup)
        .invoke_handler(tauri::generate_handler![server_info])
        .setup(move |app| {
            let handle = app.handle().clone();
            let st = state.clone();
            thread::spawn(move || spawn_sidecar(st, handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build ncmp application");

    app.run(move |_app_handle, event| {
        if let RunEvent::Exit = event {
            if let Ok(mut guard) = state_for_exit.child.lock() {
                if let Some(mut child) = guard.take() {
                    kill_sidecar_tree(&mut child);
                    eprintln!("[ncmp] backend terminated");
                }
            }
        }
    });
}
