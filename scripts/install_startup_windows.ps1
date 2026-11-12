$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startup = [Environment]::GetFolderPath('Startup')
$template = Get-Content (Join-Path $PSScriptRoot "run_silent.vbs") -Raw
$vbs = $template.Replace("__REPO__", $root)
$out = Join-Path $startup "TieuVu.vbs"
[System.IO.File]::WriteAllText($out, $vbs, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[OK] Startup registered: $out"
