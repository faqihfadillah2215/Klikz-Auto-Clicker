KLIKZ - SETUP WINDOWS 11
========================

Folder project on your computer:
C:\Users\FAQIH FADILLAH\Videos\project asal\Klikz

1. Copy these files to the corresponding paths:
   src\main.py
   requirements.txt
   assets\klikz.png
   assets\klikz.ico

2. Open VS Code terminal at project root Klikz.

3. Install dependencies WITHOUT activating the virtual environment:
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt --no-cache-dir

4. Run the app:
   .\.venv\Scripts\python.exe .\src\main.py

5. Test safely on an empty desktop or a noncritical application:
   - Start Clicking; first click occurs AFTER the selected interval
   - F6 toggles Start/Stop
   - Move mouse into a corner for PyAutoGUI failsafe
   - Minimize or close (X) to hidden system tray
   - Double-click tray icon to open
   - Right-click tray icon for Open, Start/Stop, Exit
   - Ctrl+Q in main window exits

6. BUILD EXE on Windows 11, from the project root:
   .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name Klikz --icon "assets\klikz.ico" --add-data "assets;assets" --collect-all customtkinter "src\main.py"

7. The EXE should be generated at:
   dist\Klikz.exe

IMPORTANT SAFETY NOTES
- Clicking happens at the CURRENT CURSOR POSITION when the interval expires.
- Do not run unattended while production dashboards or sensitive applications
  can receive input. Start/stop and the failsafe reduce but do not eliminate risk.
- Synthetic clicks may not prevent screen lock/sleep on all Windows setups;
  organizational security policies can still take effect.
- Windows 11 decides whether the tray icon is immediately visible or hidden.
- This code has syntax validation but has not been run on your Windows PC.
- Log file: %LOCALAPPDATA%\Klikz\klikz.log
