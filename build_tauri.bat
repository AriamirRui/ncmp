@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   ncmp 桌面应用构建脚本 (Tauri + Rust)
echo ============================================

where cargo >nul 2>nul
if errorlevel 1 (
    echo ❌ 未检测到 Rust 工具链。请先安装：https://rustup.rs/
    echo    安装后重新打开命令行，运行 rustup default stable
    pause
    exit /b 1
)

if not exist "src-tauri\binaries\ncmp-server-x86_64-pc-windows-msvc.exe" (
    echo ⚠️  未找到 Python sidecar，先构建后端...
    call build_sidecar.bat
    if errorlevel 1 exit /b 1
)

echo [1/2] 安装前端构建工具 (Tauri CLI)...
if not exist "node_modules" (
    call npm install
    if errorlevel 1 (
        echo ❌ npm install 失败。
        pause
        exit /b 1
    )
)

echo.
echo [2/2] 构建桌面应用...
call npx tauri build
if errorlevel 1 (
    echo ❌ 构建失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo ✅ 构建完成，安装包位于 src-tauri\target\release\bundle\nsis\
echo    可执行文件位于 src-tauri\target\release\ncmp.exe
pause
