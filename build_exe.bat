@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo   SD RAWR v0.13 - EXE ビルダー
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% --version
if errorlevel 1 (
    echo Python 3 が見つかりません。
    echo Python 3.11 または 3.12 をインストールしてから、もう一度実行してください。
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo 仮想環境を作成しています...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

echo 依存パッケージをインストールしています...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo 依存パッケージを確認しています...
".venv\Scripts\python.exe" -c "import pkg_resources, pyfatfs, fs; print('依存パッケージ: OK')"
if errorlevel 1 goto :fail

REM 古い PyInstaller の spec/build/dist を削除し、以前の設定が再利用されないようにします。
if exist "SDRAWR.spec" del /q "SDRAWR.spec"
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

set "ICON_ARG="
if exist "assets\sdrawr.ico" (
    echo アプリアイコンを使用します: assets\sdrawr.ico
    set "ICON_ARG=--icon assets\sdrawr.ico"
) else (
    echo 警告: assets\sdrawr.ico が見つかりません。カスタムアイコンなしでビルドします。
)

echo.
echo SDRAWR.exe をビルドしています...
".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --uac-admin ^
  --name SDRAWR ^
  %ICON_ARG% ^
  --add-data "assets;assets" ^
  --hidden-import pkg_resources ^
  --hidden-import setuptools ^
  --collect-all setuptools ^
  --collect-all pyfatfs ^
  --collect-all fs ^
  main.py

if errorlevel 1 goto :fail

echo.
echo ビルド成功:
echo   %CD%\dist\SDRAWR.exe
echo.
pause
exit /b 0

:fail
echo.
echo ビルドに失敗しました。
pause
exit /b 1
