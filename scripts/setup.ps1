param(
    [string]$PythonCmd = "python",
    [string]$RscriptCmd = "Rscript"
)

$ErrorActionPreference = "Stop"

& $PythonCmd -m venv .venv
& .\.venv\Scripts\Activate.ps1
& $PythonCmd -m pip install --upgrade pip
& $PythonCmd -m pip install -r requirements.txt
& $RscriptCmd .\install_r_packages.R

Write-Host "Setup completed."
