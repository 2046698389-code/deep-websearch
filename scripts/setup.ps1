param([switch]$Dev, [switch]$Shared)

$ErrorActionPreference = 'Stop'
$taskScriptPath = Join-Path $PSScriptRoot 'bootstrap.py'
$taskArguments = @($taskScriptPath)
if ($Dev) { $taskArguments += '--dev' }
if ($Shared) { $taskArguments += '--shared' }
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python @taskArguments
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @taskArguments
} else {
    throw 'Install Python 3.11 or newer and make it available as python or py.'
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
