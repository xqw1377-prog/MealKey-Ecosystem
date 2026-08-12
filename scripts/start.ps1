$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
}

& .\.venv\Scripts\python.exe -c @"
from app.services.llm_engine import is_llm_configured, llm_status
status = llm_status()
print('LLM standalone:', status.get('standalone'), 'configured:', status.get('configured'))
if not is_llm_configured():
    print('WARN: 未检测到大模型 Key。请确认 .env 已从主仓复制，或到设置页填写。')
"@

Write-Host "MealKey 餐启（独立部署）: http://127.0.0.1:8000"
Write-Host "健康检查: http://127.0.0.1:8000/public/health"
Write-Host "打开「设置」可查看内置大模型引擎状态。"
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
