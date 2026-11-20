$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $PSScriptRoot '.cache\pip'
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.vendor') + [IO.Path]::PathSeparator + $PSScriptRoot
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
Push-Location $PSScriptRoot
try {
    if ($args.Count -eq 0) { python -B -m driftlab demo }
    else { python -B -m driftlab @args }
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
