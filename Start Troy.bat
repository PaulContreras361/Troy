@echo off
title Troy
cd /d "%~dp0"
echo Starting Troy... your browser will open in a few seconds.
echo Leave this window open while you use Troy. Close it to stop Troy.
python -m streamlit run app.py
pause
