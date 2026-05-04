@echo off
cd /d "%~dp0\.."
if not exist config\config.yaml (
  copy config\config.example.yaml config\config.yaml >nul
  echo 已根据 config\config.example.yaml 创建本地配置: config\config.yaml
)
py -m pip install -r requirements.txt
py send_emails.py
pause
