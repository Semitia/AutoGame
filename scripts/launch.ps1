param([ValidateSet('test','farm','hidden','resume','stop','show')][string]$Mode='test')
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
