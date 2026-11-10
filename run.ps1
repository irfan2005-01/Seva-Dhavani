# Native programs can emit diagnostics to stderr during normal checks. Keep
# those diagnostics non-terminating and determine success with LASTEXITCODE.
$ErrorActionPreference = 'Continue'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$pythonArgs = @()
$serverPort = $null
for ($candidatePort = 8000; $candidatePort -le 8010; $candidatePort++) {
    $probeListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidatePort)
    try {
        $probeListener.Start()
        $probeListener.Stop()
        $serverPort = $candidatePort
        break
    } catch {
        if ($probeListener) { $probeListener.Stop() }
    }
}
if (-not $serverPort) {
    Write-Host 'ERROR No free local port between 8000 and 8010 was found.' -ForegroundColor Red
    exit 1
}
if ($serverPort -ne 8000) {
    Write-Host "WARN Port 8000 is occupied; using free port $serverPort for this run." -ForegroundColor Yellow
}

$pythonCandidates = @(
    (Join-Path $root '.venv\Scripts\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    'C:\Users\ahmed\AppData\Local\Programs\Python\Python312\python.exe',
    'python.exe'
)
$python = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-Path -LiteralPath $candidate -ErrorAction SilentlyContinue)) { continue }
    try {
        & $candidate -c 'import sys; print(sys.executable)' *> $null
        $candidateExitCode = $LASTEXITCODE
        if ($candidateExitCode -eq 0) { $python = $candidate; break }
    } catch {
        # Try the next installed interpreter candidate.
    }
}
if (-not $python) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            & $launcher.Source -3 -c 'import sys; print(sys.executable)' *> $null
            $launcherExitCode = $LASTEXITCODE
            if ($launcherExitCode -eq 0) { $python = $launcher.Source; $pythonArgs = @('-3') }
        } catch {
            # Report a single actionable message below if no interpreter works.
        }
    }
}
if (-not $python) {
    Write-Host 'ERROR Python 3 was not found. Install Python 3.10+ and run .\run.ps1 again.' -ForegroundColor Red
    exit 1
}

$envFile = Join-Path $backend '.env'
$example = Join-Path $backend '.env.example'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $example -Destination $envFile -ErrorAction Stop
    Write-Host 'Created backend/.env from backend/.env.example. Set officer/admin keys before using protected dashboard actions.'
}

Push-Location $backend
try {
    $requiredModules = @('fastapi', 'uvicorn', 'sqlalchemy', 'dotenv', 'httpx', 'multipart', 'pytest', 'pytest_asyncio')
    $missingModule = $null
    foreach ($moduleName in $requiredModules) {
        & $python @pythonArgs -c "import $moduleName" *> $null
        $moduleExitCode = $LASTEXITCODE
        if ($moduleExitCode -ne 0) { $missingModule = $moduleName; break }
    }
    if ($missingModule) {
        Write-Host "WARN Required Python module '$missingModule' is missing; installing requirements..." -ForegroundColor Yellow
        & $python @pythonArgs -m pip install -r requirements.txt
        $installExitCode = $LASTEXITCODE
        if ($installExitCode -ne 0) {
            throw "Dependency installation failed (exit $installExitCode). Check Python/pip and network access, then retry."
        }

        $missingModule = $null
        foreach ($moduleName in $requiredModules) {
            & $python @pythonArgs -c "import $moduleName" *> $null
            $moduleExitCode = $LASTEXITCODE
            if ($moduleExitCode -ne 0) { $missingModule = $moduleName; break }
        }
        if ($missingModule) {
            Write-Host "ERROR Required Python module '$missingModule' is still unavailable after installation." -ForegroundColor Red
            exit 1
        }
        Write-Host 'OK Python requirements installed and verified'
    } else {
        Write-Host 'OK Python requirements are installed'
    }

    & $python @pythonArgs -m app.preflight
    $preflightExitCode = $LASTEXITCODE
    if ($preflightExitCode -ne 0) { throw 'Preflight failed; see the warning above before starting the API.' }

    Write-Host "Starting Seva Dhwani at http://127.0.0.1:$serverPort (Ctrl+C to stop)."
    & $python @pythonArgs -m uvicorn app.main:app --host 127.0.0.1 --port $serverPort
    $serverExitCode = $LASTEXITCODE
    if ($serverExitCode -ne 0) { throw "Uvicorn exited with code $serverExitCode" }
} finally {
    Pop-Location
}
