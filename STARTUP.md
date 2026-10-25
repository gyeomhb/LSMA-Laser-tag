# Easy startup

Use PowerShell on the PC. This assumes the existing shared `.venv` is installed.
No environment activation is needed.

```powershell
cd C:\Users\user\LSMA
```

## 1. Turn on and connect

- Turn on Cozmo, Misty, and the Jetson with its overhead camera.
- Connect the PC to the network used by Misty and the Jetson.
- Plug the Kindle into the PC with its USB data cable.
- Connect the Kindle to Cozmo's Wi-Fi. Open the Cozmo app, connect to Cozmo,
  and enable **Settings > Cozmo SDK > Enable SDK**. Leave the app open.
- Place Cozmo off its charger. Keep both tags visible from above: **Cozmo = 5,
  Misty = 8**.

Check the Kindle connection:

```powershell
adb devices
```

It should show `G0W0MA0772441FQ8` with status `device`. If it says
`unauthorized`, accept the USB debugging prompt on the Kindle.

## 2. Open overhead tracking

Open [the live camera](http://192.168.1.37:8088/stream.mjpg).
If it is already updating and showing both tags, continue to step 3.

If the stream is unavailable or frozen, copy the current script and connect:

```powershell
scp .\jetson_camera_stream.py aimsjetson@192.168.1.37:/tmp/lsma_camera_stream.py
ssh aimsjetson@192.168.1.37
```

Enter the Jetson password when prompted. In that **Jetson terminal**, check for
an existing server:

```bash
pgrep -af '[l]sma_camera_stream.py'
```

If it lists an old server, stop that process with `kill PID`, replacing `PID`
with its displayed process number. Then start the camera:

```bash
python3 /tmp/lsma_camera_stream.py
```

Leave this terminal open. Refresh the live camera page. Start a separate
PowerShell window for robot control. The camera server must be started again
after a Jetson reboot.

## 3. Choose a control mode

Run these commands from `C:\Users\user\LSMA`.

### Manual WASD

For Cozmo:

```powershell
.\.venv\Scripts\python.exe .\wasd_cozmo.py
```

For Misty, use another PowerShell window:

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py --ip 192.168.1.38
```

Click the robot's control window, then use **W/S** to move and **A/D** to turn.
Release the keys or press **Space** to stop; **Esc** closes the controller.
Both controllers can be open together; the focused window receives WASD.
Each shows its robot camera and overhead coordinates. Manual WASD has no
boundary restriction.

### Cozmo escapes from Misty

**Close Cozmo's WASD window first.** Keep Misty stationary for an initial trial.
Place Cozmo's tag inside **X: 90 to 860, Y: 90 to 560**, away from Misty
(at least 85 pixels between tag centers).

If calibration is missing, a tag was remounted, or the overhead camera direction
changed, point **both robots left in the overhead image**, toward X=50. Point
Misty's head/laser forward too, then run:

```powershell
.\.venv\Scripts\python.exe .\escape_cozmo.py --calibrate-left
```

Calibration is saved in `escape_calibration.json`. Skip this step if the existing
calibration still applies. Ordinary robot turns do not require recalibration.

Start a 10-second run:

```powershell
.\.venv\Scripts\python.exe .\escape_cozmo.py --seconds 10 --speed 40
```

Press **Space, Esc, or Ctrl+C in its PowerShell window** to stop early.
The run stops automatically after 10 seconds, on tracking loss, or at the inner
boundary. The yellow camera rectangle is **X: 50 to 900, Y: 50 to 600**; the
controller reserves an additional stopping margin inside it.

Escape mode estimates Misty's aim from its tag. Independent laser/head turning
is not tracked. Escape mode does not record a dataset yet.

## 4. Record images and commands (manual mode)

Click **Start recording** in a WASD window, drive, then click **Stop recording**.

| Robot | Saved sessions |
| --- | --- |
| Cozmo | `dataset_cozmo/` |
| Misty | `datasets_misty4/` |

Each session contains `images/`, `labels.csv`, and `metadata.json`.

## When something does not start

| Problem | Check |
| --- | --- |
| Cozmo cannot connect | Kindle USB, `adb devices`, Cozmo Wi-Fi, app SDK mode; close other Cozmo controllers. |
| Misty cannot connect | Its current IP and the PC's network; the configured address is `192.168.1.38`. |
| Tracking is missing or frozen | Restart the camera server in step 2; make sure both tags are visible. |
| Escape says outside boundary | Move Cozmo inside X 90 to 860, Y 90 to 560, then rerun. |
| `.venv` is missing | Follow the one-time uv setup in [README.md](README.md#setup-with-uv). |

## Finish

Stop recording and close the robot control windows. Stop an escape run with
Space or Esc. If you started the camera in an SSH terminal, press Ctrl+C there,
then type `exit` to disconnect.

See [README.md](README.md) for installation, random movement, and full details.
