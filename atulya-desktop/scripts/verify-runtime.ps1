# Verify integrity of assembled runtime artifacts.
# Usage: .\scripts\verify-runtime.ps1 [runtime_dir]

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$RuntimeDir = if ($args.Count -gt 0) { $args[0] } else { Join-Path $ProjectRoot ".dist\runtime" }

Write-Host "==> Verifying runtime integrity: $RuntimeDir"

$Errors = 0

foreach ($dir in @("api", "control-plane", "brain")) {
    $fullPath = Join-Path $RuntimeDir $dir
    if (!(Test-Path $fullPath)) {
        Write-Host "    FAIL: missing directory $dir\"
        $Errors++
    } else {
        Write-Host "    OK:   $dir\"
    }
}

if (!(Test-Path (Join-Path $RuntimeDir "api\.venv"))) {
    Write-Host "    FAIL: API .venv missing"
    $Errors++
} else {
    Write-Host "    OK:   api\.venv"
}

if (!(Test-Path (Join-Path $RuntimeDir "control-plane\server.js"))) {
    Write-Host "    FAIL: control-plane\server.js missing"
    $Errors++
} else {
    Write-Host "    OK:   control-plane\server.js"
}

$BrainLib = Join-Path $RuntimeDir "brain\atulya_brain.dll"
if (!(Test-Path $BrainLib)) {
    Write-Host "    FAIL: brain\atulya_brain.dll missing"
    $Errors++
} else {
    Write-Host "    OK:   brain\atulya_brain.dll"
}

$ChecksumFile = Join-Path $RuntimeDir "checksums.sha256"
if (Test-Path $ChecksumFile) {
    Write-Host "==> Verifying checksums..."
    $ChecksumErrors = 0
    Get-Content $ChecksumFile | ForEach-Object {
        $parts = $_ -split "  ", 2
        if ($parts.Count -eq 2) {
            $expectedHash = $parts[0]
            $relPath = $parts[1]
            $fullPath = Join-Path $RuntimeDir $relPath.Replace("/", "\")
            if (Test-Path $fullPath) {
                $actualHash = (Get-FileHash $fullPath -Algorithm SHA256).Hash.ToLower()
                if ($expectedHash -ne $actualHash) {
                    Write-Host "    FAIL: checksum mismatch for $relPath"
                    $ChecksumErrors++
                }
            } else {
                Write-Host "    FAIL: file missing: $relPath"
                $ChecksumErrors++
            }
        }
    }
    if ($ChecksumErrors -eq 0) {
        Write-Host "    OK:   all checksums verified"
    } else {
        $Errors += $ChecksumErrors
    }
}

Write-Host ""
if ($Errors -gt 0) {
    Write-Host "==> FAILED: $Errors error(s) found"
    exit 1
} else {
    Write-Host "==> PASSED: runtime integrity verified"
}
