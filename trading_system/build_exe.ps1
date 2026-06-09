$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $Root
$Venv = Join-Path $Root ".venv"
$Python = "py -V:Astral/CPython3.11.15"

Push-Location $ProjectRoot
try {
  if (-not (Test-Path $Venv)) {
    Invoke-Expression "$Python -m venv `"$Venv`""
  }

  $VenvPython = Join-Path $Venv "Scripts\python.exe"
  & $VenvPython -m pip install --upgrade pip pyinstaller

  $Dist = Join-Path $Root "dist"
  $Build = Join-Path $Root "build"
  $Preserve = Join-Path $Root ".build-preserve"
  $LocalBackup = Join-Path $Root ".local-data-backup"
  $LocalDataFiles = @(".env.local", "asset_pool.json", "manual_holdings.json", "dashboard_view_cache.json", "binance api.txt")
  if (-not (Test-Path $Preserve)) { New-Item -ItemType Directory -Path $Preserve | Out-Null }
  if (-not (Test-Path $LocalBackup)) { New-Item -ItemType Directory -Path $LocalBackup | Out-Null }
  foreach ($Name in $LocalDataFiles) {
    $DistSide = Join-Path $Dist $Name
    $Preserved = Join-Path $Preserve $Name
    $BackedUp = Join-Path $LocalBackup $Name
    $RootSide = Join-Path $Root $Name
    if (Test-Path $DistSide) {
      Copy-Item -LiteralPath $DistSide -Destination $Preserved -Force
      Copy-Item -LiteralPath $DistSide -Destination $BackedUp -Force
    } elseif (Test-Path $Preserved) {
      Copy-Item -LiteralPath $Preserved -Destination $BackedUp -Force
    } elseif (Test-Path $BackedUp) {
      Copy-Item -LiteralPath $BackedUp -Destination $Preserved -Force
    } elseif (Test-Path $RootSide) {
      Copy-Item -LiteralPath $RootSide -Destination $Preserved -Force
    }
  }
  if (Test-Path $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force }
  if (Test-Path $Build) { Remove-Item -LiteralPath $Build -Recurse -Force }

  $PreviousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $VenvPython -m PyInstaller `
    --onefile `
    --name "ETF-Trading-System" `
    --distpath $Dist `
    --workpath $Build `
    --specpath $Root `
    --add-data "$Root\dashboard;dashboard" `
    --add-data "$Root\config.json;." `
    --add-data "$Root\README.md;." `
    "$Root\server.py"
  $PyInstallerExitCode = $LASTEXITCODE
  $ErrorActionPreference = $PreviousErrorActionPreference
  if ($PyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $PyInstallerExitCode"
  }

  Copy-Item -LiteralPath "$Root\dashboard" -Destination "$Dist\dashboard" -Recurse -Force
  Copy-Item -LiteralPath "$Root\config.json" -Destination "$Dist\config.json" -Force
  $SavedAssetPool = Join-Path $Preserve "asset_pool.json"
  if (Test-Path $SavedAssetPool) {
    Copy-Item -LiteralPath $SavedAssetPool -Destination "$Dist\asset_pool.json" -Force
    Copy-Item -LiteralPath $SavedAssetPool -Destination "$LocalBackup\asset_pool.json" -Force
  } else {
    Copy-Item -LiteralPath "$Root\asset_pool.json" -Destination "$Dist\asset_pool.json" -Force
  }
  Copy-Item -LiteralPath "$Root\setup_tailscale.md" -Destination "$Dist\setup_tailscale.md" -Force
  foreach ($Name in @(".env.local", "manual_holdings.json", "binance api.txt")) {
    $Saved = Join-Path $Preserve $Name
    $RootSide = Join-Path $Root $Name
    if (Test-Path $Saved) {
      Copy-Item -LiteralPath $Saved -Destination (Join-Path $Dist $Name) -Force
      Copy-Item -LiteralPath $Saved -Destination (Join-Path $LocalBackup $Name) -Force
    } elseif (Test-Path $RootSide) {
      Copy-Item -LiteralPath $RootSide -Destination (Join-Path $Dist $Name) -Force
    }
  }
  Remove-Item -LiteralPath $Preserve -Recurse -Force
  Write-Host "Done: $Dist\ETF-Trading-System.exe"
}
finally {
  Pop-Location
}
