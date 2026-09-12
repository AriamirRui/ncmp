@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   ncmp Python sidecar 构建脚本
echo   (Web 后端 ncmp-server.exe)
echo ============================================

echo [1/3] 安装构建依赖...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ❌ 依赖安装失败。
    pause
    exit /b 1
)

echo.
echo [2/3] 生成图标...
python assets\make_icon.py

echo.
echo [3/3] 打包 ncmp-server.exe ...
python -m PyInstaller ncmp-server.spec --noconfirm --clean --distpath dist-sidecar
if errorlevel 1 (
    echo ❌ 打包失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo 复制到 Tauri sidecar 目录（带 target triple 后缀）...
if not exist "src-tauri\binaries" mkdir "src-tauri\binaries"
copy /Y "dist-sidecar\ncmp-server.exe" "src-tauri\binaries\ncmp-server-x86_64-pc-windows-msvc.exe" >nul
if errorlevel 1 (
    echo ❌ 复制失败。
    pause
    exit /b 1
)

echo.
echo ✅ sidecar 构建完成:
echo    dist-sidecar\ncmp-server.exe
echo    src-tauri\binaries\ncmp-server-x86_64-pc-windows-msvc.exe
echo.
echo 下一步：运行 build_tauri.bat 构建桌面应用
pause
