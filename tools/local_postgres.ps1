param([ValidateSet('start', 'stop', 'status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$local = Join-Path $root '.local-postgres'
$config = Get-Content -LiteralPath (Join-Path $local 'connection.json') -Raw | ConvertFrom-Json
$pgCtl = Join-Path $config.bin 'pg_ctl.exe'
$data = Join-Path $local 'data'
if ($Action -eq 'start') {
    & $pgCtl -D $data status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output 'PMS PostgreSQL is already running.'; exit 0 }
    & $pgCtl -D $data -l (Join-Path $local 'server.log') -w start
} elseif ($Action -eq 'stop') {
    & $pgCtl -D $data -m fast -w stop
} else {
    & $pgCtl -D $data status
}
exit $LASTEXITCODE
