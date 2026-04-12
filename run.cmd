@echo off
chcp 65001 >nul
echo ===================================================
echo UESTC Thesis Formatter (马克思主义学院专版)
echo ===================================================

if "%~1"=="" (
    echo [错误] 请拖拽一个 .docx 文件到本脚本上运行，或在命令行中指定参数。
    echo 示例: run.cmd "D:\我的论文.docx"
    pause
    exit /b 1
)

if not exist "%~1" (
    echo [错误] 找不到输入文件: %~1
    pause
    exit /b 1
)

echo.
echo [1/3] 正在检查基本环境 (Python)...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未安装 Python 或未加入系统环境变量 PATH 中。请先安装 Python 3.10+。
    pause
    exit /b 1
)
echo.
echo [1.5/3] 检查底层排版模板...
if not exist "vendor\DissertationUESTC\main.tex" (
    echo [提示] 首次运行，正在自动拉取底层排版引擎代码 (可能需要几十秒)...
    if not exist "vendor\DissertationUESTC" mkdir "vendor\DissertationUESTC"
    git submodule update --init --recursive >nul 2>&1
    if not exist "vendor\DissertationUESTC\main.tex" (
        echo [提示] Git 拉取失败或未安装 Git，正在尝试直接下载预编译 ZIP...
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/MGG1996/DissertationUESTC/archive/refs/heads/master.zip' -OutFile 'vendor.zip'; Expand-Archive -Path 'vendor.zip' -DestinationPath 'vendor_temp' -Force; Move-Item -Path 'vendor_temp\DissertationUESTC-master\*' -Destination 'vendor\DissertationUESTC' -Force; Remove-Item 'vendor.zip'; Remove-Item 'vendor_temp' -Recurse -Force"
    )
)
echo.
echo [2/3] 正在安装所需依赖库...
pip install -r requirements.txt >nul 2>&1

echo.
echo [3/3] 正在启动全自动转换流水线...
python scripts/run_v2.py "%~1" --profile uestc-marxism

echo.
echo ===================================================
echo 执行结束。如果有任何错误请查看上方输出。
echo ===================================================
pause
