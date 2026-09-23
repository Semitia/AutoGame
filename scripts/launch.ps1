param([ValidateSet('test','farm','hidden','resume','stop','show','gui')][string]$Mode='test')
$ErrorActionPreference='Stop'
$repoRoot=Split-Path $PSScriptRoot -Parent
$localPath=Join-Path $repoRoot 'config/local.json'
$localConfig=if(Test-Path -LiteralPath $localPath){Get-Content -LiteralPath $localPath -Raw | ConvertFrom-Json}else{$null}
$pythonPath=$env:AUTOGAME_PYTHON
if(-not $pythonPath){$pythonPath=$localConfig.python}
if(-not $pythonPath){$pythonPath=Join-Path $repoRoot '.venv/Scripts/python.exe'}
if(-not (Test-Path -LiteralPath $pythonPath)){$pythonPath=(Get-Command python -ErrorAction Stop).Source}
Push-Location $repoRoot
try {
 if($Mode -eq 'gui') {
  & $pythonPath -X utf8 -c "import sys; sys.path.insert(0,'.local/python-deps'); from PySide6.QtWidgets import QApplication"
  if($LASTEXITCODE -ne 0) {
   Write-Host 'GUI dependency missing. Install with your Python: -m pip install -r requirements-gui.txt'
   exit 1
  }
  $guiLogDir=Join-Path $repoRoot 'runtime'
  New-Item -ItemType Directory -Path $guiLogDir -Force | Out-Null
  $guiScript=Join-Path $repoRoot 'gui.py'
  # SW_HIDE also hides Qt's first top-level window. pythonw has no console,
  # so the actual player-facing GUI must be started normally.
  $guiPython=Join-Path (Split-Path $pythonPath -Parent) 'pythonw.exe'
  if(-not (Test-Path -LiteralPath $guiPython)){$guiPython=$pythonPath}
  $guiErrorLog=Join-Path $guiLogDir 'gui-launch-error.log'
  $guiProcess=Start-Process -WindowStyle Normal -FilePath $guiPython -WorkingDirectory $repoRoot -ArgumentList @('-X','utf8',('"'+$guiScript+'"')) -RedirectStandardError $guiErrorLog -PassThru
  $guiDeadline=[DateTime]::UtcNow.AddSeconds(15)
  do {
   Start-Sleep -Milliseconds 200
   $guiProcess.Refresh()
   if($guiProcess.HasExited) {
    if(Test-Path -LiteralPath $guiErrorLog){Get-Content -LiteralPath $guiErrorLog | Write-Host}
    Write-Host "GUI exited before showing a window. See: $guiErrorLog"
    exit 1
   }
   if($guiProcess.MainWindowHandle -ne [IntPtr]::Zero){exit 0}
  } while([DateTime]::UtcNow -lt $guiDeadline)
  Write-Host "GUI window did not appear within 15 seconds. PID: $($guiProcess.Id). See: $guiErrorLog"
  exit 1
 }
 if($Mode -eq 'stop') {
  $stateDir=Join-Path $repoRoot 'runtime/bilibili_hero_merge'
  New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $stateDir 'STOP') -Value ''
 }
 if($Mode -in @('stop','show')) {
  & $pythonPath -c "import sys; sys.path.insert(0,'src'); from autogame.platforms.mumu import MuMuPlatform; MuMuPlatform().show()"
 } elseif($Mode -eq 'hidden') {
  $logDir=Join-Path $repoRoot 'runtime'; New-Item -ItemType Directory -Path $logDir -Force | Out-Null
  Start-Process -WindowStyle Hidden -FilePath $pythonPath -WorkingDirectory $repoRoot -ArgumentList '-X utf8 run.py bilibili_hero_merge --hide --until-stamina' -RedirectStandardOutput (Join-Path $logDir 'stdout.log') -RedirectStandardError (Join-Path $logDir 'stderr.log')
 } else {
  $runnerArgs=@('-X','utf8','run.py','bilibili_hero_merge','--hide')
  if($Mode -eq 'test'){$runnerArgs+=@('--runs','1','--minutes','15')}
  else{$runnerArgs+='--until-stamina'}
  if($Mode -eq 'resume'){$runnerArgs+='--resume'}
  & $pythonPath @runnerArgs
 }
} finally {Pop-Location}
