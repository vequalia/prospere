# Prospere One-Click Installer for Windows
Write-Host "🚀 Starting Prospere installation..." -ForegroundColor Cyan

# 1. Check for Python
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: Python is not installed. Please install Python 3.11 or higher from the Microsoft Store or python.org." -ForegroundColor Red
    exit 1
}

$pyVersion = python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "✅ Found Python $pyVersion" -ForegroundColor Green

# 2. Define install directory
$installDir = "$HOME\.prospere"
$venvDir = "$installDir\venv"

Write-Host "📂 Setting up environment in $installDir..." -ForegroundColor Cyan
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
}

# 3. Create virtual environment
if (-not (Test-Path $venvDir)) {
    Write-Host "📦 Creating virtual environment..."
    python -m venv $venvDir
}

# 4. Install Prospere from GitHub
Write-Host "📥 Downloading and installing Prospere from GitHub..." -ForegroundColor Cyan
& "$venvDir\Scripts\python.exe" -m pip install --upgrade pip
& "$venvDir\Scripts\pip.exe" install "git+https://github.com/vequalia/prospere.git"

# 5. Create a wrapper script
$binDir = "$HOME\.local\bin"
if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
}

$batPath = "$binDir\prospere.bat"
$batContent = "@echo off`nset PATH=$venvDir\Scripts;%PATH%`n`"$venvDir\Scripts\prospere.exe`" %*"
Set-Content -Path $batPath -Value $batContent

# 6. Configure Shell (Path)
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($userPath -notmatch [regex]::Escape($binDir)) {
    Write-Host "🔧 Adding $binDir to your User PATH..." -ForegroundColor Cyan
    $newPath = "$userPath;$binDir"
    [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
    Write-Host "⚠️  PATH updated. You MUST restart your terminal (or open a new tab) for the 'prospere' command to work." -ForegroundColor Yellow
}

Write-Host "🎉 Prospere installed successfully!" -ForegroundColor Green
Write-Host "👉 Open a NEW terminal window and type 'prospere' to start." -ForegroundColor Green
Write-Host "---"
