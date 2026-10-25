# Robot keyboard control and dataset recording

For everyday use, follow [Easy startup](STARTUP.md).

Windows/Python controllers for Cozmo and Misty 4. Both provide WASD driving,
a live color camera view, and image/command dataset recording.

## Files

| File | Purpose |
| --- | --- |
| `wasd_cozmo.py` | Cozmo controller, color camera, and recording. Sets the head to 5 degrees below level at startup. |
| `random_cozmo.py` | Short random movements for Cozmo with strict tracking checks, an inner boundary buffer, and optional image/command recording. |
| `escape_cozmo.py` | Continuous escape steering using Cozmo tag 5, Misty tag 8, calibrated headings, and boundary checks. |
| `test_escape_cozmo.py` | Tests steering, escape path clearance, and stopping when tracking fails. |
| `wasd_misty.py` | Misty controller using HTTP commands and a camera WebSocket. Defaults to `192.168.1.38`; accepts `--ip`. Rotates camera frames 90 degrees clockwise before displaying or saving them. |
| `dataset_recorder.py` | Shared background writer for PNG images, CSV labels, and session metadata. Supports uncapped recording or an optional sampling rate. |
| `jetson_camera_stream.py` | Runs on the Jetson with its existing OpenCV installation. Streams the overhead RealSense color camera and detects ArUco tags in image coordinates. |
| `tracking_panel.py` | Shared coordinate panel. Polls the Jetson in a background thread and displays fresh per-tag X/Y pixel coordinates in both controllers. |
| `movement_limits.py` | Strict boundary and tracking checks used by autonomous random and escape controllers. |
| `requirements.txt` | Installs both robots' dependencies in the shared Python 3.8 environment. |
| `test_dataset_recorder.py` | Tests image/label pairing, sampling, uncapped recording, and command labels without hardware. |
| `test_misty.py` | Tests Misty key mapping, camera decoding, recording, and mocked HTTP commands without hardware. |
| `test_tracking_panel.py` | Tests coordinate units, tag filtering, and hiding stale or unavailable positions. |
| `test_movement_limits.py` | Tests the autonomous controller's boundary edges, tracking freshness, and tag identity checks. |
| `test_random_cozmo.py` | Tests random action bounds and automatic stopping on tracking loss, boundary approach, keyboard stop, pickup, or SDK errors. |
| `.gitignore` | Excludes environments, datasets, logs, caches, and local reference files from Git. |

Local files that are excluded from Git:

| File or directory | Purpose |
| --- | --- |
| `Cozmo.pdf`, `Misty.pdf` | Supplied robot setup guides. The Misty guide includes local network details and an older IP address. |
| `robot_tracking.pdf` | Reference for the overhead RealSense/Jetson tracking setup. |
| `.venv/` | Shared Python 3.8 environment managed with uv; runs both controllers. |
| `dataset_cozmo/` | Cozmo recording sessions. |
| `datasets_misty4/` | Misty recording sessions. |
| `*-controller.log`, `*-controller-errors.log` | Output from controllers launched with log redirection. Normal PowerShell launches print output in the terminal instead. |
| `__pycache__/` | Automatically generated Python bytecode cache. |

## Escape from Misty

The escape controller uses tags 5 and 8 to choose 140-pixel waypoints away from
Misty and its estimated firing direction. It steers continuously, replans once
per second, and checks tracking every 50 ms. It assumes Misty's laser stays aligned
with the calibrated tag direction; independent head/laser rotation is not tracked.
It uses image pixels and a heuristic firing cone, not a calibrated physical laser model.
This controller does not record a dataset yet.

With both robots facing image-left (toward X=50), calibrate once:

```powershell
.\.venv\Scripts\python.exe .\escape_cozmo.py --calibrate-left
```

Offsets are saved in local `escape_calibration.json`. Repeat calibration if a tag
is remounted or the overhead camera orientation changes; normal robot turns do
not require recalibration. Close Cozmo's WASD controller before running escape.
Place Cozmo inside X 90–860, Y 90–560 and at least 85 pixels from Misty's tag.
For the first trial, keep Misty stationary and run:

```powershell
.\.venv\Scripts\python.exe .\escape_cozmo.py --seconds 10 --speed 40
```

Space, Esc, or Ctrl+C in the terminal stops the run. Missing/stale tags, boundary
contact, pickup, charger detection, or proximity to Misty also stop movement.
The full boundary is X 50–900, Y 50–600; the controller keeps a 40-pixel stopping
buffer and selects waypoints with a 60-pixel buffer. WASD remains unrestricted.

## Setup with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is not
already available. Open PowerShell in this project directory. For the original
workspace:

```powershell
cd C:\Users\user\LSMA
```

Create one shared environment for both robots:

```powershell
# Cozmo's legacy SDK determines the Python version for both controllers.
uv venv --python 3.8 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

uv can download the requested Python version. If `.venv` already exists
and works, skip its creation. The commands below invoke the environment's Python
directly, so PowerShell activation is unnecessary.

## Run Cozmo

1. Enable USB debugging/ADB on the Kindle or Android device.
2. Connect it to the PC with a USB data cable and accept its debugging prompt.
3. Install Android Platform-Tools and add its directory to `Path` if needed.
4. Check the connection:

   ```powershell
   adb devices
   ```

   The device must have status `device`, not `unauthorized`.

5. Connect the Kindle to Cozmo's Wi-Fi, then connect to Cozmo in the app.
6. In the app, enable **Settings → Cozmo SDK → Enable SDK**. Keep the app open
   and the USB cable connected.
7. Place Cozmo off the charger and run:

   ```powershell
   .\.venv\Scripts\python.exe .\wasd_cozmo.py
   ```

## Random Cozmo movement

Close the Cozmo WASD controller first. Keep the Kindle connected in SDK mode and
the Jetson tracker running. Place Cozmo's tag 5 inside **X 90–860, Y 90–560**,
the requested X 50–900 / Y 50–600 rectangle with a 40-pixel inner stopping buffer.

```powershell
.\.venv\Scripts\python.exe .\random_cozmo.py
```

This chooses short random forward, reverse, turning, curved, and stopped segments
for up to 60 seconds. Default straight speed is 40 mm/s and turn speed is 30 mm/s.
Segments last 0.2–0.7 seconds, with position checks about every 20 ms against the
latest tracker response. Tracking itself updates separately, about 10 times per second.

To collect images and matching commands during the run:

```powershell
.\.venv\Scripts\python.exe .\random_cozmo.py --seconds 120 --record
```

Optional parameters include `--seed 42`, `--speed 30`, `--turn-speed 20`,
`--margin 50`, `--marker-id 5`, and `--tracking-url`.
Recordings use `dataset_cozmo/` with automation settings in `metadata.json`.

Press **Space**, **Esc**, or **Ctrl+C** in the PowerShell window to stop.
The script ends early if Cozmo reaches the inner buffer, the selected tag is lost
or stale, Cozmo is picked up, or an error occurs. It does not automatically recover
or resume from those conditions: reposition inside the inner rectangle and run
again. The manual WASD allowance for untracked driving does **not** apply here.

This is random wandering with a stop boundary, not navigation to random target
points. It does not detect obstacles. The buffer reduces overshoot but cannot
guarantee containment of the robot's entire body through camera, network, or
braking delays. Increasing `--margin` reserves more room.

## Run Misty 4

Turn on Misty and connect the PC to a network that can reach the robot.
Misty uses the network directly; it does not need the Kindle or ADB.

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py
```

The default address is `192.168.1.38`. Override it when the robot's IP changes:

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py --ip 192.168.1.38
```

The controller uses HTTP port 80 and camera WebSocket port 5678. It connects by
IP; the returned serial is displayed and saved as metadata, not used to restrict
connections. It requests 640×480 color frames and rotates them clockwise, giving
480×640 saved images when that requested stream size is returned. It leaves the
head angle unchanged.

Close an existing controller before starting another controller for the same robot.

To run both at once from the project folder:

```powershell
Start-Process .\.venv\Scripts\python.exe -ArgumentList '.\wasd_cozmo.py'
Start-Process .\.venv\Scripts\python.exe -ArgumentList '.\wasd_misty.py'
```

Both processes share the same installed libraries but maintain separate robot
connections. WASD controls the focused window; both cameras can record concurrently.

## Overhead camera and ArUco tracking

The overhead RealSense L515 is connected to the Jetson at `192.168.1.37`.
The camera server runs on the Jetson, independently of both robot controllers.
While the server is running, open these addresses from the PC:

- Live annotated feed: `http://192.168.1.37:8088/stream.mjpg`
- One image: `http://192.168.1.37:8088/snapshot.jpg`
- Current tag IDs, corners, center coordinates, frame age, and errors:
  `http://192.168.1.37:8088/status`

The server uses `/dev/video6`, requests 1280×720 at 30 FPS, and detects
`DICT_4X4_50` tags. Tag IDs do not automatically identify a particular robot.
Coordinates are image pixels, not calibrated 3D positions. This service does not
publish ROS topics or automatically add tracking coordinates to robot recordings.
Check `error` and `frame_age_seconds` before using status data.

To start it again, first make sure another instance or ROS camera driver is not
already using the camera. Copy the script from PowerShell:

```powershell
scp .\jetson_camera_stream.py aimsjetson@192.168.1.37:/tmp/lsma_camera_stream.py
ssh aimsjetson@192.168.1.37
```

Then, in the Jetson SSH terminal:

```bash
python3 /tmp/lsma_camera_stream.py
```

Keep that terminal open; Ctrl+C stops the foreground server. The initially deployed
instance was started in the background. To find it on the Jetson, use
`pgrep -af '[l]sma_camera_stream.py'`; stop the listed server PID with `kill <PID>`
before starting a replacement. Its log is `/tmp/lsma_camera_stream.log`.
It is not configured to start automatically at boot.

This uses the Jetson's existing OpenCV 4.10 installation through V4L2 because the
installed Python RealSense SDK did not enumerate the L515 during testing.
Stop this server before trying the ROS camera driver. The feed is available to
devices that can reach the Jetson's local network address.

### Coordinates in the WASD windows

Both controllers show a live **Overhead tracking** panel. Cozmo defaults to tag
**5**, and Misty defaults to tag **8**, as attached to the robots in this setup.
You can change either selection in the **This robot's tag** dropdown.
The origin is the top-left corner, X increases rightward, and Y increases downward.
These are pixels, not meters or coordinates in the robot's onboard camera.

After identifying the tag attached to your robot, show only that tag, for example:

```powershell
.\.venv\Scripts\python.exe .\wasd_cozmo.py --marker-id 5
.\.venv\Scripts\python.exe .\wasd_misty.py --marker-id 8
```

Tag 5 is assigned to Cozmo; tag 8 is assigned to Misty. You can override
the tracker with `--tracking-url http://192.168.1.37:8088/status`.
The panel updates about 10 times per second. Stale, missing, or unreachable
tracking is reported instead of displaying old coordinates as current.
The tag dropdown controls which coordinates are displayed. Manual WASD movement
does not depend on the selected tag, detected position, or overhead tracking
availability. The WASD controllers and their coordinate panel have no boundary
checks or boundary messages. Coordinates are displayed only; the existing robot
dataset CSV formats are unchanged.

Boundary checks remain in `random_cozmo.py` through `movement_limits.py`, for
autonomous movement only. See **Random Cozmo movement** for its operating area
and stop conditions.

## Controls

Click the controller window, then hold the keys:

| Input | Action |
| --- | --- |
| W / S | Forward / backward |
| A / D | Turn left / right |
| W or S + A or D | Drive in a curve |
| Release movement keys | Stop |
| Space | Stop; release and press movement keys again to resume |
| Switch to another window | Clear movement keys and stop |
| Esc or close window | Stop, finish saving, and exit |
| Start recording / Stop recording | Start or finish a dataset session |

Cozmo drives straight at 60 mm/s, with turning mixed into individual wheel speeds.
Misty uses 10% linear/angular velocity and refreshes 500 ms timed commands while
keys are held. Misty stops sending movement when its camera feed is stale.
Commands and their completion depend on the robot and network connection.

## Record a dataset

Recording starts **off** whenever a controller opens. Click **Start recording**,
drive, and click **Stop recording** when finished. Each start creates a new UTC-named
session directory:

```text
dataset_cozmo/                    # Cozmo
datasets_misty4/                   # Misty
  <session timestamp>/
    images/
      000000.png
      000001.png
    labels.csv
    metadata.json
```

The controllers record every received frame, including stopped frames, without
an application FPS cap. Actual FPS depends on camera delivery, network, decoding,
and disk speed. The window shows the average saved FPS and writer-queue drop count;
this count does not include frames lost before reaching the application. A bounded
background queue prevents disk writes from blocking driving controls.

PNG files preserve the decoded frame pixels. Misty's source stream may already
be compressed. Preview resizing does not resize saved dataset images. Misty's
orientation correction applies to both the preview and new recordings; it does
not modify older sessions.

`labels.csv` associates each relative image path with its command:

| Robot | Label information |
| --- | --- |
| Cozmo | Image number, SDK receipt timestamp, label timestamp, held keys, command name, left/right wheel commands in mm/s, and reported head angle. |
| Misty | Frame number, PC receipt timestamp, held keys, requested command, last acknowledged command, linear/angular commands in percent, send/ack timestamps, and command state. |

Commands include `stop`, `forward`, `backward`, `left`, `right`, and combinations
such as `forward_left`. Misty marks samples as `acknowledged`, `transition`, or
`expired`; filter by that field when selecting training samples.

Labels describe commands at PC receipt time, not measured robot motion or exact
camera exposure time. Transmission latency and command transitions can affect
alignment. Cozmo wheel speeds and Misty velocity percentages are different units;
do not treat their numeric values as interchangeable training targets.

`metadata.json` records session settings and the label interpretation. Keep entire
sessions together when splitting training and validation data to avoid placing
near-identical neighboring frames in both splits.

## Run tests

These tests do not connect to or move a robot:

```powershell
.\.venv\Scripts\python.exe -m unittest test_misty test_dataset_recorder test_tracking_panel test_movement_limits test_random_cozmo
```

## Troubleshooting

- **Cozmo is not connected:** check `adb devices`, the Kindle's Wi-Fi connection,
  and Cozmo SDK mode. Accept the Kindle's USB debugging prompt if unauthorized.
- **Cozmo reports an asyncio `loop` argument error:** use `.venv` with
  Python 3.8 rather than a newer system Python.
- **Misty connection fails:** verify the current IP and network access. Try
  opening `http://192.168.1.38` in a browser, substituting the current IP.
- **Misty camera fails:** check port 5678 and close other camera controllers;
  close and reopen this controller after resolving the problem.
- **Keys do nothing:** click the control window. For Misty, wait for fresh camera
  frames. Release Space and press the movement keys again.
- **Frames are dropped:** check free disk space and storage speed. The queue-drop
  count indicates that the background writer could not keep up.

## Create a Git repository

From this folder:

```powershell
git init
git add .
git status
git diff --cached --stat
git commit -m "Add Cozmo and Misty controllers with dataset recording"
```

Review the staged file list before committing. `.gitignore` keeps generated data,
Python environments, logs, local device details, and the supplied PDFs out of the
repository. It does not remove files that Git already tracks. Source files retain
Misty's default private IP; change the default or use `--ip` for another setup.
