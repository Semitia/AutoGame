@echo off
cd /d "%~dp0"
python -c "from pathlib import Path; p=Path('runtime/tata/fishing/STOP'); p.parent.mkdir(parents=True,exist_ok=True); p.touch()"
