@echo off
:: EIL-Calc API server — Windows startup script
:: Requires: uv  (https://docs.astral.sh/uv/getting-started/installation/)
::
:: DEM paths are auto-detected by scanning all drive letters for:
::   <drive>:\eil-calc\IfSAR\IfSAR_PH.tif
::   <drive>:\eil-calc\SRTM\SRTM30m.tif
::
:: To override, set environment variables before running this script:
::   set IFSAR_PATH=E:\eil-calc\IfSAR\IfSAR_PH.tif
::   set SRTM_PATH=E:\eil-calc\SRTM\SRTM30m.tif

cd /d "%~dp0"
uv run uvicorn api:app --host 127.0.0.1 --port 8000 --reload
