@echo off
chcp 65001 > nul
echo ============================================
echo   工厂零件管理系统 启动脚本
echo ============================================
echo.

REM 查找Python路径
set PYTHON_EXE=
if exist "C:\Users\Lenovo\AppData\Local\Python\bin\python.exe" (
    set PYTHON_EXE=C:\Users\Lenovo\AppData\Local\Python\bin\python.exe
) else (
    python --version > nul 2>&1
    if not errorlevel 1 set PYTHON_EXE=python
)

if "%PYTHON_EXE%"=="" (
    echo [错误] 未检测到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/2] 正在安装依赖包...
"%PYTHON_EXE%" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)

echo [2/2] 正在启动服务器...
for /f "tokens=2 delims=: " %%a in ('ipconfig ^| findstr /R /C:"IPv4.*"') do (
    set LOCAL_IP=%%a
    goto :ip_done
)
:ip_done
echo.
echo ============================================
echo   访问地址: http://127.0.0.1:5000
if not "%LOCAL_IP%"=="" echo   局域网访问: http://%LOCAL_IP%:5000
echo   公网访问: 请将本机5000端口映射到穿透域名
echo   默认账号: admin / admin123
echo   按 Ctrl+C 停止服务器
echo ============================================
echo.
"%PYTHON_EXE%" app.py
pause
