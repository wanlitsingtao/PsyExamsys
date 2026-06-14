@echo off
chcp 65001 >nul
cd /d "E:\LingMa\exmsys"
echo ============================================
echo   心理咨询师考试背题系统
echo ============================================
echo.
echo 正在启动...
echo 启动后请访问: http://localhost:8510
echo.
"C:\Users\wanli\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py --server.port 8510
pause
