# Assemble Atulya Desktop runtime artifacts into .dist\runtime\
# Usage: .\scripts\assemble-runtime.ps1
#
# Must be run on Windows. Produces the portable runtime bundle
# that the Tauri shell manages.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$MonorepoRoot = Split-Path -Parent $ProjectRoot
$DistDir = Join-Path $ProjectRoot ".dist\runtime"

$Target = "windows-x64"

Write-Host "==> Assembling runtime for target: $Target"
Write-Host "    monorepo: $MonorepoRoot"
Write-Host "    output:   $DistDir"

if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
New-Item -ItemType Directory -Force -Path "$DistDir\api" | Out-Null
New-Item -ItemType Directory -Force -Path "$DistDir\control-plane" | Out-Null
New-Item -ItemType Directory -Force -Path "$DistDir\brain" | Out-Null

# -- Step 1: Build API runtime --
Write-Host "==> [1/4] Building API runtime..."
$ApiSrc = Join-Path $MonorepoRoot "atulya-api"

if (Test-Path $ApiSrc) {
    Copy-Item -Recurse -Force (Join-Path $ApiSrc "atulya_api") (Join-Path $DistDir "api\atulya_api")
    Copy-Item -Force (Join-Path $ApiSrc "pyproject.toml") (Join-Path $DistDir "api\")

    Push-Location (Join-Path $DistDir "api")
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv .venv
        uv sync
        uv pip install -e .
    } else {
        python -m venv .venv
        & .\.venv\Scripts\pip install -e .
    }
    Pop-Location
    Write-Host "    API runtime assembled"
} else {
    Write-Host "    WARNING: $ApiSrc not found, skipping API"
}

# -- Step 2: Build Control Plane --
Write-Host "==> [2/4] Building Control Plane..."
$CpSrc = Join-Path $MonorepoRoot "atulya-control-plane"

if (Test-Path $CpSrc) {
    Push-Location $CpSrc
    npm ci --ignore-scripts 2>$null
    if ($LASTEXITCODE -ne 0) { npm install }
    npx next build
    Pop-Location

    $StandaloneServer = Get-ChildItem -Path (Join-Path $CpSrc ".next\standalone") -Recurse -Filter "server.js" |
        Where-Object { $_.FullName -notmatch "node_modules" } |
        Select-Object -First 1
    if ($StandaloneServer) {
        $StandaloneRoot = $StandaloneServer.DirectoryName
        Copy-Item -Recurse -Force "$StandaloneRoot\*" "$DistDir\control-plane\"
        if (Test-Path (Join-Path $CpSrc ".next\static")) {
            New-Item -ItemType Directory -Force -Path "$DistDir\control-plane\.next\static" | Out-Null
            Copy-Item -Recurse -Force (Join-Path $CpSrc ".next\static\*") "$DistDir\control-plane\.next\static\"
        }
        Write-Host "    Control Plane assembled"
    }
} else {
    Write-Host "    WARNING: $CpSrc not found, skipping Control Plane"
}

# -- Step 3: Build brain native library --
Write-Host "==> [3/4] Building brain native library..."
$BrainSrc = Join-Path $MonorepoRoot "atulya-brain"

if (Test-Path $BrainSrc) {
    Push-Location $BrainSrc
    cargo build --release
    Pop-Location

    $DllPath = Join-Path $BrainSrc "target\release\atulya_brain.dll"
    if (Test-Path $DllPath) {
        Copy-Item -Force $DllPath "$DistDir\brain\"
    }
    Write-Host "    Brain native library assembled"
} else {
    Write-Host "    WARNING: $BrainSrc not found, skipping brain"
}

# -- Step 4: Generate checksums --
Write-Host "==> [4/4] Generating checksums..."
$ChecksumFile = Join-Path $DistDir "checksums.sha256"
"" | Set-Content $ChecksumFile

Get-ChildItem -Recurse -File $DistDir | Where-Object { $_.Name -ne "checksums.sha256" } | ForEach-Object {
    $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    $RelPath = $_.FullName.Substring($DistDir.Length + 1).Replace("\", "/")
    "$Hash  $RelPath" | Add-Content $ChecksumFile
}

Write-Host ""
Write-Host "==> Runtime assembly complete"
Write-Host "    Target: $Target"
Write-Host "    Output: $DistDir"
