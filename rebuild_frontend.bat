@echo off
echo Rebuilding React frontend...
cd /d "D:\zhuomian\agent\patient-care-assistant\frontend"
call npx vite build
echo Done! Refresh browser to see changes.
