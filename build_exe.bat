@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   ncmp 一键打包脚本 (PyInstaller)
echo ============================================

echo [1/3] 安装构建依赖 (pyinstaller)...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ❌ 依赖安装失败，请检查网络或 Python 环境。
    pause
    exit /b 1
)

echo.
echo [2/3] 生成应用图标...
python assets\make_icon.py
if errorlevel 1 (
    echo ❌ 图标生成失败（将使用默认图标继续）。
)

echo.
echo [3/3] 构建 ncmp.exe...
python -m PyInstaller ncmp.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo ❌ 构建失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
if exist "config\setting.json" (
    echo 将配置文件夹复制到 dist\config ...
    xcopy /E /Y /I config dist\config >nul
)

if exist "dist\ncmp.exe" (
    echo ✅ 构建完成: %~dp0dist\ncmp.exe
    echo 配置已位于: %~dp0dist\config（如有需要可自行修改 setting.json）
) else (
    echo ❌ 未找到 dist\ncmp.exe，请检查日志。
)
pause
