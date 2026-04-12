<#
.SYNOPSIS
    Standalone Docker Debug Helper — Docker-based LaTeX compilation wrapper.
.DESCRIPTION
    ⚠ ROLE DECLARATION:
    This script is a STANDALONE DOCKER DEBUG HELPER, NOT a no-Docker fallback.
    It uses Docker internally (docker info / docker run) and requires Docker Desktop.

    The CANONICAL COMPILE ENGINE is run_v2.py Step 6 (built-in Docker mechanism).
    Use this script only when you need to compile a .tex project independently,
    outside of the full run_v2.py pipeline.

    Compiles a LaTeX thesis using Docker (TeX Live Full), with automatic
    Windows font mounting for Chinese font support.
    Supports profile-based compile chain selection.
.PARAMETER ProjectDir
    Path to the thesis project directory containing main.tex
.PARAMETER MainTex
    Name of the main .tex file (default: main.tex)
.PARAMETER Profile
    Profile name (e.g., uestc, uestc-marxism). If specified, reads compile
    chain from profile.json. Overrides CompileChain parameter.
.PARAMETER CompileChain
    Comma-separated compile chain (e.g., "xelatex,xelatex,xelatex").
    Default: "xelatex,bibtex,xelatex,xelatex"
.PARAMETER DockerImage
    Docker image to use (default: ghcr.io/xu-cheng/texlive-full:latest)
.PARAMETER MaxRetries
    Maximum compilation retry attempts (circuit breaker, default: 3)
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectDir,

    [string]$MainTex = "main.tex",

    [string]$Profile = "",

    [string]$CompileChain = "",

    [string]$DockerImage = "ghcr.io/xu-cheng/texlive-full:latest",

    [int]$MaxRetries = 3
)

$ErrorActionPreference = "Stop"

# === Validate ===
if (-not (Test-Path $ProjectDir)) {
    Write-Error "Project directory not found: $ProjectDir"
    exit 1
}

if (-not (Test-Path (Join-Path $ProjectDir $MainTex))) {
    Write-Error "Main tex file not found: $ProjectDir\$MainTex"
    exit 1
}

# === Check Docker ===
try {
    docker info 2>&1 | Out-Null
} catch {
    Write-Error "Docker is not available. Please install Docker Desktop."
    exit 1
}

# === Determine compile chain ===
$chain = @()

if ($Profile -ne "") {
    # Load from profile using profile_loader.py
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $loaderScript = Join-Path $ScriptDir "profile_loader.py"

    if (Test-Path $loaderScript) {
        Write-Host "Loading compile chain from profile: $Profile" -ForegroundColor Cyan
        $profileJson = python $loaderScript $Profile 2>&1
        if ($LASTEXITCODE -eq 0) {
            $profileData = $profileJson | ConvertFrom-Json
            $rawChain = $profileData.compile_chain
            if ($rawChain -is [array]) {
                $chain = $rawChain
            } elseif ($rawChain -is [string]) {
                $chain = $rawChain -split '[→,]' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
            }
            Write-Host "  Compile chain: $($chain -join ' → ')" -ForegroundColor Cyan

            # Override docker image if specified in profile
            if ($profileData.docker_image) {
                $DockerImage = $profileData.docker_image
            }
        } else {
            Write-Warning "Failed to load profile, using default chain"
        }
    }
}

if ($chain.Count -eq 0 -and $CompileChain -ne "") {
    $chain = $CompileChain -split ',' | ForEach-Object { $_.Trim() }
}

if ($chain.Count -eq 0) {
    # Default: standard UESTC chain
    $chain = @("xelatex", "bibtex", "xelatex", "xelatex")
}

Write-Host "Compile chain: $($chain -join ' → ')" -ForegroundColor Cyan

# === Resolve paths ===
$ProjectDir = (Resolve-Path $ProjectDir).Path

# Font mount: use Windows Fonts directory
$FontDir = "C:\Windows\Fonts"
if (-not (Test-Path $FontDir)) {
    Write-Warning "Windows Fonts directory not found at $FontDir"
}

# Convert Windows path to Docker volume mount format
$DockerProjectMount = "${ProjectDir}:/thesis"
$DockerFontMount = "${FontDir}:/thesis/fonts:ro"

# === Build compilation command ===
$mainBase = $MainTex -replace '\.tex$', ''
$compileCmds = @()
foreach ($step in $chain) {
    switch ($step) {
        "xelatex"  { $compileCmds += "xelatex -interaction=nonstopmode $MainTex" }
        "bibtex"   { $compileCmds += "bibtex $mainBase 2>/dev/null; true" }
        "pdflatex" { $compileCmds += "pdflatex -interaction=nonstopmode $MainTex" }
        "lualatex" { $compileCmds += "lualatex -interaction=nonstopmode $MainTex" }
        default    { Write-Warning "Unknown compile step: $step, skipping" }
    }
}

$CompileScript = "export OSFONTDIR=/thesis/fonts && cd /thesis && " + ($compileCmds -join " && ")

# === Run compilation ===
$attempt = 0
$success = $false

while ($attempt -lt $MaxRetries -and -not $success) {
    $attempt++
    Write-Host "`n=== Compilation attempt $attempt/$MaxRetries ===" -ForegroundColor Cyan

    $result = docker run --rm `
        -v $DockerProjectMount `
        -v $DockerFontMount `
        -w /thesis `
        $DockerImage `
        bash -c $CompileScript 2>&1

    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        $success = $true
        Write-Host "✅ Compilation successful!" -ForegroundColor Green
    } else {
        Write-Host "❌ Compilation failed (exit code: $exitCode)" -ForegroundColor Red

        # Parse errors from output
        $errors = $result | Select-String -Pattern "^!" | Select-Object -First 5
        if ($errors) {
            Write-Host "Errors found:" -ForegroundColor Yellow
            foreach ($err in $errors) {
                Write-Host "  $($err.Line)" -ForegroundColor Yellow
            }
        }

        if ($attempt -lt $MaxRetries) {
            Write-Host "Retrying..." -ForegroundColor Yellow
        }
    }
}

if (-not $success) {
    Write-Host "`n🛑 CIRCUIT BREAKER: Failed after $MaxRetries attempts." -ForegroundColor Red
    Write-Host "Please check the log file: $ProjectDir\$($MainTex -replace '\.tex$','.log')" -ForegroundColor Red
    exit 1
}

# === Report ===
$pdfFile = Join-Path $ProjectDir ($MainTex -replace '\.tex$','.pdf')
if (Test-Path $pdfFile) {
    $pdfSize = [math]::Round((Get-Item $pdfFile).Length / 1MB, 2)
    Write-Host "`n📄 Output: $pdfFile ($pdfSize MB)" -ForegroundColor Green
} else {
    Write-Host "`n⚠️ PDF file not found after compilation" -ForegroundColor Yellow
}
