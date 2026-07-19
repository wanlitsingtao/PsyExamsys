@echo off
chcp 65001 >nul
title Exmsys 考试系统服务管理面板

:: ============================================
::  Exmsys 心理咨询师考试系统 - 服务管理面板
::  启动/停止/重启/安装/卸载 一键管理
::  可随项目文件夹迁移到其他机器
:: ============================================

set "SERVICE_NAME=ExmsysStudy"
set "BASE_DIR=%~dp0"
set "BASE_DIR=%BASE_DIR:~0,-1%"
set "APP_PORT=8510"

:menu
cls
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   Exmsys 考试系统 - 服务管理面板         ║
echo   ╚══════════════════════════════════════════╝
echo.

:: 检查服务状态
sc query "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2 delims=: " %%a in ('sc query "%SERVICE_NAME%" ^| find "STATE"') do (
        if "%%a"=="RUNNING" (
            echo     服务状态: [● 正在运行]
            echo     访问地址: http://localhost:%APP_PORT%
        ) else (
            echo     服务状态: [○ 已停止]
        )
    )
    for /f "tokens=4 delims= " %%b in ('sc query "%SERVICE_NAME%" ^| find "PID"') do set "SERVICE_PID=%%b"
    if defined SERVICE_PID (
        if not "!SERVICE_PID!"=="0" (
            echo     进程 PID: %SERVICE_PID%
        )
    )
) else (
    echo     服务状态: [× 未安装]
)
echo.
echo   ┌──────────────────────────────────────┐
echo   │  1. 启动服务                          │
echo   │  2. 停止服务                          │
echo   │  3. 重启服务                          │
echo   │  4. 安装/重新安装服务                  │
echo   │  5. 卸载服务                          │
echo   │  6. 打开浏览器访问                     │
echo   │  7. 查看服务日志                       │
echo   │                                      │
echo   │  0. 退出                              │
echo   └──────────────────────────────────────┘
echo.
set /p choice="   请选择操作 (0-7): "

if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto install
if "%choice%"=="5" goto remove
if "%choice%"=="6" goto browser
if "%choice%"=="7" goto logs
if "%choice%"=="0" exit /b
goto menu

:start
echo.
echo   [INFO] 正在启动服务...
sc start "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] 服务启动成功！
    timeout /t 2 >nul
    set /p open="   是否打开浏览器？(Y/n): "
    if /i "%open%" neq "n" start http://localhost:%APP_PORT%
) else (
    echo   [ERROR] 启动失败！
    echo.
    echo   请先运行 setup-service.bat 安装服务
)
pause
goto menu

:stop
echo.
echo   [INFO] 正在停止服务...
sc stop "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] 服务已停止
) else (
    echo   [ERROR] 停止失败（可能服务未运行）
)
pause
goto menu

:restart
echo.
echo   [INFO] 正在重启服务...
sc stop "%SERVICE_NAME%" >nul 2>&1
timeout /t 3 >nul
sc start "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] 服务重启成功！
    timeout /t 2 >nul
    set /p open="   是否打开浏览器？(Y/n): "
    if /i "%open%" neq "n" start http://localhost:%APP_PORT%
) else (
    echo   [ERROR] 重启失败
)
pause
goto menu

:install
echo.
echo   [INFO] 正在调用安装程序...
echo.
start /wait "" "%BASE_DIR%\setup-service.bat"
echo.
pause
goto menu

:remove
echo.
echo   [WARN] 确定要卸载服务吗？
echo.
set /p confirm="   确认卸载？(Y/N): "
if /i "%confirm%"=="Y" (
    sc stop "%SERVICE_NAME%" >nul 2>&1
    timeout /t 2 >nul
    C:\nssm\nssm.exe remove "%SERVICE_NAME%" confirm >nul 2>&1
    if %errorlevel% equ 0 (
        echo   [OK] 服务已卸载
    ) else (
        sc delete "%SERVICE_NAME%" >nul 2>&1
        echo   [OK] 服务已通过 sc 卸载
    )
) else (
    echo   [INFO] 已取消
)
pause
goto menu

:browser
echo.
echo   [INFO] 正在打开浏览器...
start http://localhost:%APP_PORT%
echo   [OK] 已打开 http://localhost:%APP_PORT%
pause
goto menu

:logs
cls
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   服务日志查看                           ║
echo   ╚══════════════════════════════════════════╝
echo.
echo   日志文件位置：
echo   %BASE_DIR%\logs\
echo.
echo   1. 查看 stdout 日志（标准输出）
echo   2. 查看 stderr 日志（错误输出）
echo   3. 以记事本打开日志目录
echo   4. 清空日志
echo   5. 返回上一级
echo.
set /p logchoice="   请选择 (1-5): "

if "%logchoice%"=="1" (
    if exist "%BASE_DIR%\logs\stdout.log" (
        notepad "%BASE_DIR%\logs\stdout.log"
    ) else (
        echo   [INFO] 暂无 stdout 日志
        pause
    )
    goto logs
)
if "%logchoice%"=="2" (
    if exist "%BASE_DIR%\logs\stderr.log" (
        notepad "%BASE_DIR%\logs\stderr.log"
    ) else (
        echo   [INFO] 暂无 stderr 日志
        pause
    )
    goto logs
)
if "%logchoice%"=="3" (
    if not exist "%BASE_DIR%\logs" mkdir "%BASE_DIR%\logs"
    start explorer "%BASE_DIR%\logs"
    goto logs
)
if "%logchoice%"=="4" (
    del /Q "%BASE_DIR%\logs\*.log" 2>nul
    echo   [OK] 日志已清空
    pause
    goto logs
)
goto menu
