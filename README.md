# Robot keyboard control and dataset recording

Cozmo uses odometry for position, initialized and corrected by overhead tag 5. Start with [STARTUP.md](STARTUP.md).
Older waypoint and escape scripts are retained as references; the toggle uses timed movement.

For everyday use, follow [Easy startup](STARTUP.md).

Windows/Python controllers for Cozmo and Misty 4. Both provide WASD driving,
a live color camera view, and image/command dataset recording.

## Files

| File | Purpose |
| --- | --- |
| `wasd_cozmo.py` | Cozmo controller, color camera, and recording. Sets the head to 5 degrees below level at startup. |
| `random_cozmo.py` | Short random movements for Cozmo with strict tracking checks, an inner boundary buffer, and optional image/command recording. |
| `escape_cozmo.py` | Continuous escape steering using Cozmo tag 5, Misty tag 8, calibrated headings, and boundary checks. |
| `waypoint_cozmo.py` | Uses fourteen fixed waypoints and drives toward randomly changing targets. |
| `test_waypoint_cozmo.py` | Tests arrival-only switching, forward steering, target selection, and tracking-loss stops. |
| `test_escape_cozmo.py` | Tests steering, escape path clearance, and stopping when tracking fails. |
| `wasd_misty.py` | Misty controller using HTTP commands and a camera WebSocket. Defaults to `192.168.1.38`; accepts `--ip`. Rotates camera frames 90 degrees clockwise before displaying or saving them. |
| `robot_startup.py` | Checks Misty and Cozmo connections and cameras; manages the Cozmo process. |
| `cozmo_navigation.py` | Fuses Cozmo odometry with overhead tag 5 and checks the 15 cm edge margin. |
| `timed_cozmo.py` | Drives forward at 90 mm/s for 5-10 seconds, then turns randomly left or right for 0.4-1.2 seconds. Supports manual and automatic edge reversal. |
| `cozmo_waypoint_worker.py` | Private SDK process for the Misty window's Cozmo toggle. Stops Cozmo on OFF, shutdown, or lost parent heartbeat. |
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

For automatic waypoint movement instead, see [Cozmo waypoints](#cozmo-waypoints).

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
Place Cozmo inside X 90–960, Y 90–560 and at least 85 pixels from Misty's tag.
For the first trial, keep Misty stationary and run:

```powershell
.\.venv\Scripts\python.exe .\escape_cozmo.py --seconds 10 --speed 90
```

Space, Esc, or Ctrl+C in the terminal stops the run. Missing/stale tags, boundary
contact, pickup, charger detection, or proximity to Misty also stop movement.
The full boundary is X 50–1000, Y 50–600; the controller keeps a 40-pixel stopping
buffer and selects waypoints with a 60-pixel buffer. WASD remains unrestricted.

## Legacy Cozmo waypoints

Close other Cozmo controllers. Start overhead tracking and keep the Kindle in SDK
mode. This mode uses Cozmo tag 5 and its saved heading in `escape_calibration.json`.
If calibration is missing or a tag/camera was remounted, perform the left-facing
calibration described above first.

```powershell
.\.venv\Scripts\python.exe .\waypoint_cozmo.py
```

Running the command starts movement automatically. The code uses fourteen fixed points
around the perimeter (X: 130, 335, 540, 745, 950; Y: 130, 280, 430, 530), with the six middle points omitted; there is no editor or saved-point file.
Waypoint mode uses the actual boundary: X 50-1000, Y 50-600, with no additional inset.

Cozmo drives at 90 mm/s and keeps its target until it arrives within 25 pixels.
It immediately selects another target on arrival. There is no target timer.
The next target excludes the previous point and its immediate horizontal,
vertical, and diagonal neighbors. Earlier points can be revisited later.
Cozmo brakes when switching targets, turns in place to face the target, then drives forward; it does not reverse
toward waypoints. By default the run continues until stopped. Use `--seconds 60`
only when you want an optional overall run limit.
Steering finishes alignment within 8 degrees and only returns to turning above
30 degrees. A 3-degree deadband ignores tiny heading changes, turn commands ramp
smoothly, and near-180-degree turns keep one direction despite angle-wrap noise.
Forward motion ramps up to the same 90 mm/s cruise speed.
On arrival, the next target is selected immediately, but the stop command is held
for at least 0.4 seconds. Turning starts only after fresh camera frames show the
tag position staying within 3 pixels for at least 0.2 seconds. If it has not
settled within 2 seconds, the run ends with motors stopped. Tracking and boundary
checks remain active during braking.
This is direct waypoint steering, without Misty avoidance or obstacle planning.

Click the PowerShell terminal and press **Space**, **Esc**, or **Ctrl+C** to stop.
Tracking loss, boundary contact, pickup, or charger detection also stops the run.
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
the Jetson tracker running. Place Cozmo's tag 5 inside **X 90–960, Y 90–560**,
the requested X 50–1000 / Y 50–600 rectangle with a 40-pixel inner stopping buffer.

```powershell
.\.venv\Scripts\python.exe .\random_cozmo.py
```

This chooses short random forward, reverse, turning, curved, and stopped segments
for up to 60 seconds. Default straight speed is 90 mm/s and turn speed is 60 mm/s.
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

Close other Cozmo controllers first. This window now manages both robots:
Misty uses WASD and **Cozmo ON/OFF** toggles autonomous Cozmo movement.
Startup checks Misty's API and camera and Cozmo's SDK connection and camera.
Startup needs a fresh tag 5 observation from the overhead camera and the saved
facing offset in `escape_calibration.json`. Tag 8 is not required.
Cozmo must be on the floor, off its charger. The toggle starts OFF.
Startup keeps the verified Misty camera socket open for the control window.
If video is stuck, it stops the video service, waits five seconds for camera
release, then starts it on a fresh WebSocket port and verifies an image before
continuing. It tries up to two fresh ports if needed; the chosen port is automatic.

ON drives forward at 90 mm/s for a random 5-10 seconds, then turns left or right
for 0.4-1.2 seconds and repeats. It uses estimated position to reverse near arena edges; it does not detect obstacles.
Press R in the Misty window while Cozmo is ON to reverse its travel direction
and start a new random 5-10 second drive. R also interrupts a turn. Each press
switches forward/backward; holding R does not repeat. Random turns continue.
The yellow box X=50-1000, Y=50-600 represents 2050 x 1200 mm.
`cozmo_navigation.py` initializes position and heading from tag 5, then applies
SDK odometry changes continuously. Fresh tag readings gently correct drift;
stale, duplicate, ambiguous, or large outlier readings are ignored.
Tag loss after initialization does not interrupt movement.
Within 150 mm of an edge, outward travel triggers the same reversal as R,
with a fresh 5-10 second timer. Inward travel is allowed even outside the box.
This approximate scale and odometry do not guarantee exact containment.
An SDK pose-origin reset needs fresh tracking to re-anchor; otherwise Cozmo stops
with an explicit reset error rather than applying a false position jump.
OFF, Space, closing the window, pickup, or a lost controller heartbeat stops Cozmo.

To check connections without opening controls or driving:

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py --check-only
```

Turn on Misty and connect the PC to a network that can reach the robot.
Misty uses the network directly. The integrated Cozmo control requires the Kindle
connected over USB with the Cozmo app in SDK mode.

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py
```

The default address is `192.168.1.38`. Override it when the robot's IP changes:

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py --ip 192.168.1.38
```

The controller uses HTTP port 80. It tries the existing camera WebSocket on port
5678, then uses a fresh port between 10000 and 60000 when restarting video to
avoid Misty's intermittent port-reuse failures. Recording metadata includes the
actual port. It connects by
IP; the returned serial is displayed and saved as metadata, not used to restrict
connections. It requests 640×480 color frames and rotates them clockwise, giving
480×640 saved images when that requested stream size is returned. It leaves the
head angle unchanged.

Close an existing controller before starting another controller for the same robot.

To drive Misty while Cozmo runs timed random movement, open the integrated controller:

```powershell
.\.venv\Scripts\python.exe .\wasd_misty.py
```

Turn on **Cozmo ON/OFF**. Do not run another Cozmo controller at the same
time. Misty's recording button records Misty; the Cozmo worker does not record
Cozmo images.

## Legacy overhead camera and ArUco tracking

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

Cozmo drives straight at 90 mm/s, with a 60 mm/s turning component mixed into
individual wheel speeds (up to 150 mm/s during curves). Escape mode defaults to
90 mm/s, with a 60 mm/s maximum turning component and a 150 mm/s wheel cap.
Misty uses 20% linear / 15% angular velocity and refreshes 500 ms timed commands while
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

Both robot controllers cap recording and camera previews at 15 FPS, including
stopped frames. Screenshot previews also use this cap; Space still saves one picture.
This is an application limit, not a camera hardware setting. Slower sources are
not padded with duplicate frames. Actual FPS depends on camera delivery, network, decoding,
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
- **Misty camera fails:** close other camera controllers; startup prints the chosen video port;
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
