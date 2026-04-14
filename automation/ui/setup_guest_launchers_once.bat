@echo off
setlocal

net use H: \\DEV1\D /user:DEV1\Администратор Man1Man2
C:\Python\python.exe H:\EDTApps\AI_agent\automation\ui\setup_guest_launchers.py --autostart --jobs-root H:\EDTApps\AI_agent\automation\logs\vm_ui_jobs

endlocal
