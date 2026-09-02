@echo off
chcp 65001 >nul
set "APP_PORT=8511"
cd /d "%~dp0"
echo ============================================
echo   心理咨询师考试背题系统
echo ============================================
echo.
echo 正在启动...
echo 启动后请访问: http://localhost:%APP_PORT%
echo.
"C:\Users\wanli\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py --server.port %APP_PORT%
pause
