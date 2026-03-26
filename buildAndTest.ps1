# ECS Discord Bot & WebUI - Build and Test Script (Windows)

Write-Host "🚀 Starting Build and Test process..." -ForegroundColor Cyan

# 1. Bot Core Tests
Write-Host "`n========================================" -ForegroundColor Gray
Write-Host "--- Running Bot Core Unit Tests ---" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Gray
$env:PYTHONPATH = ".;$env:PYTHONPATH"
python -m pytest tests/
if ($LASTEXITCODE -ne 0) { 
    Write-Host "❌ Bot Core Tests Failed" -ForegroundColor Red
    exit $LASTEXITCODE 
}

# 2. WebUI Python Tests
Write-Host "`n========================================" -ForegroundColor Gray
Write-Host "--- Running WebUI Python Tests ---" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Gray
Set-Location Discord-Bot-WebUI
if (Test-Path "run_tests.py") {
    python run_tests.py --unit --integration
    if ($LASTEXITCODE -ne 0) { 
        Write-Host "❌ WebUI Python Tests Failed" -ForegroundColor Red
        exit $LASTEXITCODE 
    }
} else {
    Write-Host "⚠️ run_tests.py not found in Discord-Bot-WebUI/" -ForegroundColor Cyan
}

# 3. WebUI Frontend Tests
Write-Host "`n========================================" -ForegroundColor Gray
Write-Host "--- Running WebUI Frontend Tests ---" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Gray
if (Test-Path "package.json") {
    if (-not (Test-Path "node_modules")) {
        Write-Host "📦 node_modules not found, running npm install..." -ForegroundColor Cyan
        npm install
    }
    npm test
    if ($LASTEXITCODE -ne 0) { 
        Write-Host "❌ WebUI Frontend Tests Failed" -ForegroundColor Red
        exit $LASTEXITCODE 
    }
} else {
    Write-Host "⚠️ package.json not found in Discord-Bot-WebUI/" -ForegroundColor Cyan
}

Set-Location ..
Write-Host "`n✅ All tests passed successfully!" -ForegroundColor Green
