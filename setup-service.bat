@echo off
chcp 65001 >nul
title Exmsys 考试系统服务安装程序

:: ============================================
::  Exmsys 心理咨询师考试系统 - 服务安装程序
::  全自动安装为 Windows 系统服务
::  支持跨机器迁移：复制整个文件夹到新机器后运行此脚本即可
::  依赖：NSSM (https://nssm.cc)
:: ============================================

set "BASE_DIR=%~dp0"
set "BASE_DIR=%BASE_DIR:~0,-1%"
set "SERVICE_NAME=ExmsysStudy-MultiUser"
set "SERVICE_DESC=心理咨询师考试背题系统 - Streamlit Web 服务"
set "PYTHON_EXE=C:\Users\wanli\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "APP_PORT=8511"

:: ─── 检查管理员权限 ───
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [INFO] 需要管理员权限来安装系统服务...
    echo.
    mshta "javascript:var shell=new ActiveXObject('Shell.Application');shell.ShellExecute('%~s0','','','runas',1);close();"
    exit /b
)

echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   Exmsys 考试系统 - 服务安装程序         ║
echo   ║                                          ║
echo   ║   项目路径: %BASE_DIR%   ║
echo   ║   访问端口: %APP_PORT%                         ║
echo   ╚══════════════════════════════════════════╝
echo.

:: ─── 检查项目完整性 ───
echo   [1/5] 检查项目完整性...
if not exist "%BASE_DIR%\app.py" (
    echo   [ERROR] 未找到 app.py！请确保项目完整
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo   [ERROR] 未找到 Python 解释器！
    echo.
    echo   当前配置路径: %PYTHON_EXE%
    echo.
    echo   如需修改 Python 路径，请编辑本文件中的 PYTHON_EXE 变量
    pause
    exit /b 1
)

:: ─── 检查 Streamlit ───
echo   [2/5] 检查 Streamlit 环境...
"%PYTHON_EXE%" -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [INFO] 未安装 streamlit，正在安装...
    "%PYTHON_EXE%" -m pip install streamlit -q
    if %errorlevel% neq 0 (
        echo   [ERROR] streamlit 安装失败！请手动执行:
        echo   "%PYTHON_EXE%" -m pip install streamlit
        pause
        exit /b 1
    )
    echo   [OK] streamlit 安装完成
) else (
    echo   [OK] Streamlit 已就绪
)

:: ─── 检查/下载 NSSM ───
echo   [3/5] 检查 NSSM...
if not exist "C:\nssm\nssm.exe" (
    echo   [INFO] 未找到 NSSM，正在下载...
    if not exist "%TEMP%\nssm" mkdir "%TEMP%\nssm"
    curl -L -s -o "%TEMP%\nssm.zip" "https://nssm.cc/release/nssm-2.24.zip"
    if %errorlevel% neq 0 (
        echo   [ERROR] 下载失败，请手动下载:
        echo   1. 访问 https://nssm.cc/download
        echo   2. 下载 nssm-2.24.zip
        echo   3. 解压后将 win64\nssm.exe 复制到 C:\nssm\nssm.exe
        pause
        exit /b 1
    )
    powershell -command "Expand-Archive -Path '%TEMP%\nssm.zip' -DestinationPath '%TEMP%\nssm' -Force" >nul 2>&1
    if not exist "C:\nssm" mkdir C:\nssm
    copy /Y "%TEMP%\nssm\nssm-2.24\win64\nssm.exe" "C:\nssm\nssm.exe" >nul
    echo   [OK] NSSM 已下载安装到 C:\nssm\nssm.exe
) else (
    echo   [OK] NSSM 已就绪
)

:: ─── 如果服务已存在，先删除 ───
sc query "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [INFO] 服务已存在，正在重建...
    C:\nssm\nssm.exe stop "%SERVICE_NAME%" >nul 2>&1
    timeout /t 2 >nul
    C:\nssm\nssm.exe remove "%SERVICE_NAME%" confirm >nul 2>&1
    timeout /t 2 >nul
)

:: ─── 安装服务 ───
echo   [4/5] 正在安装服务...
C:\nssm\nssm.exe install "%SERVICE_NAME%" "%PYTHON_EXE%" "-m streamlit run app.py --server.port %APP_PORT% --server.headless true"

:: 设置工作目录
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppDirectory "%BASE_DIR%"

:: 设置启动类型为自动
C:\nssm\nssm.exe set "%SERVICE_NAME%" Start SERVICE_AUTO_START

:: 设置显示名称和描述
C:\nssm\nssm.exe set "%SERVICE_NAME%" DisplayName "%SERVICE_NAME%"
C:\nssm\nssm.exe set "%SERVICE_NAME%" Description "%SERVICE_DESC%"

:: 设置日志输出
if not exist "%BASE_DIR%\logs" mkdir "%BASE_DIR%\logs"
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppStdout "%BASE_DIR%\logs\stdout.log"
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppStderr "%BASE_DIR%\logs\stderr.log"
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppRotateFiles 1
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppRotateOnline 1
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppRotateBytes 10485760

:: 进程优先级
C:\nssm\nssm.exe set "%SERVICE_NAME%" AppPriority NORMAL_PRIORITY_CLASS

echo   [OK] 服务配置完成

:: ─── 启动服务 ───
echo   [5/5] 正在启动服务...
C:\nssm\nssm.exe start "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] 服务启动成功！
) else (
    sc start "%SERVICE_NAME%" >nul 2>&1
    if %errorlevel% equ 0 (
        echo   [OK] 服务启动成功！
    ) else (
        echo   [WARN] 服务启动可能延迟，稍后可使用 exmsys-service-manager.bat 手动启动
    )
)

echo.
echo   ╔══════════════════════════════════════════╗
echo   ║  安装完成！                              ║
echo   ║                                          ║
echo   ║   服务名称: %SERVICE_NAME%        ║
echo   ║   访问地址: http://localhost:%APP_PORT%        ║
echo   ║   管理脚本: exmsys-service-manager.bat   ║
echo   ╚══════════════════════════════════════════╝
echo.
echo   提示：
echo   - 服务已设置为"自动启动"，重启电脑后自动运行
echo   - 浏览器打开 http://localhost:%APP_PORT% 即可使用
echo   - 如复制到新机器，修改本文件中的 PYTHON_EXE 路径后运行即可
echo.

:: ─── 询问是否打开浏览器 ───
set /p open="是否现在打开浏览器访问？(Y/n): "
if /i "%open%" neq "n" (
    start http://localhost:%APP_PORT%
)

echo.
pause
