# Quick startup

Misty only (no Cozmo or tracking):
```powershell
cd C:\Users\user\LSMA
.\.venv\Scripts\python.exe .\wasd_misty_only.py
```

Both robots:
```powershell
cd C:\Users\user\LSMA
```

## 1. Misty
```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py
```

Turn on the overhead camera. Keep Cozmo tag 5 visible for startup.
Checks both robots, their cameras, and Cozmo initial position.
Odometry runs movement; tracking corrects drift. Missing tags after startup do not stop it.
Close other Cozmo programs first. **Cozmo ON/OFF**: ON drives forward and turns randomly every 5-10 seconds. OFF stops.
Within 15 cm of an edge, Cozmo automatically reverses when heading outward.
**R** reverses Cozmo and restarts its random 5-10 second drive.
**Space** stops both. Closing the window stops both.

## 2. Cozmo
```powershell
.\.venv\Scripts\python.exe .\wasd_cozmo.py # To run and record Cozmo robot
```
