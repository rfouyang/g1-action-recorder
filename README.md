# G1 Action Recorder

Tools for recording, composing, mirroring, and validating Unitree G1 upper-body
poses, then compiling pose sequences into time-sampled robot actions.
Physical robot execution is deliberately outside the current scope.

## Environment

```bash
uv python install 3.10
uv sync
uv run python -m unittest discover -s tests
```

The pose phase is read-only with respect to the physical robot. It will subscribe
to G1 state data but will not publish motor commands.

## Pose coordinate convention

- `left` and `right` always mean the G1's anatomical left and right.
- In model coordinates, the G1 faces `+X`; its anatomical left is `+Y` and its
  anatomical right is `-Y`.
- Camera 1 is directly in front of the G1. The G1's left arm therefore appears
  on the right side of this unmirrored image.
- Camera 2 is located on the G1's anatomical right side.
- Camera 3 is located 45 degrees between the front and anatomical right side.
- Camera 4 is located on the G1's anatomical left side.
- Camera 5 is located 45 degrees between the front and anatomical left side.

## Simulated pose preview

```bash
MUJOCO_GL=egl uv run python util/mujoco_pose_helper.py
```

Pose previews are forward-kinematics snapshots; they do not advance physics or
send robot commands. Joints omitted from a partial left-arm or right-arm pose
remain at the neutral value in the preview.

## Run the authoring UI

```bash
uv run python app/g1_3d_main.py
```

Open `http://127.0.0.1:8000`. The page exposes Pose Recorder, Pose Composer, and
Action workspaces, while `GET /api/g1/system/health` verifies the independent
REST surface. The embedded Viser scene loads the G1 URDF once and tracks the
shared MuJoCo joint state at up to 30 Hz. Mouse orbit, pan, and zoom remain
native Viser interactions, and the six buttons below the viewer apply
robot-relative camera presets. Those presets use a tighter 2.30 m orbit and a
45-degree vertical field of view so the robot fills more of the viewer.
You can also right-click `app/g1_3d_main.py` in the IDE and run it directly.
The entrypoint selects EGL for MuJoCo and rebuilds stale daisyUI styles itself.

The configured startup pose is `data/poses/base/concierge_init.json`. Recorder
controls, reset behavior, Composer base selection, and the initial Viser robot
state use this pose. A missing file falls back to an unsaved neutral base pose.

Simulation clients can read or update state through:

```text
GET /api/g1/simulation/state
PUT /api/g1/simulation/joints
WS  /api/g1/simulation/ws
```

These transports update simulation only. They validate model joint names and
MuJoCo limits before publishing a new state revision to Viser.

## Action IK foundation

The first action milestone uses Pink with Pinocchio and the `quadprog` QP solver.
The G1 URDF is loaded as a fixed-base 29-joint model. Each IK request then builds
a reduced model containing only the explicitly active joints, so a left-arm
solve cannot move the waist, legs, or right arm.

Run the standalone IK demo and render its solved joint values through the G1
MJCF with:

```bash
MUJOCO_GL=egl uv run python util/pink_ik_helper.py
```

The demo moves the left rubber-hand frame upward by 3 cm while preserving its
orientation and writes `data/pose_previews/pink_ik_left_hand.png`. This only
validates the IK and MuJoCo model bridge; it does not yet define an action file
or send commands to a robot.

## Action definition contract

Every action follows the fixed structure `concierge_init → one or more
intermediate poses → concierge_init`. The user adds the intermediate poses and
selects the duration of every transition. Partial `left_arm` and `right_arm`
poses must be composed before they can be used as intermediate action frames.

```json
{
  "schema_version": 1,
  "name": "welcome_left",
  "robot_model_id": "unitree_g1_29dof_rev_1_0_fake_hand",
  "initial_pose": {"pose_type": "base", "name": "concierge_init"},
  "transitions": [
    {
      "target_pose": {
        "pose_type": "composed",
        "name": "concierge_present_left"
      },
      "duration_seconds": 1.5,
      "hold_seconds": 1.0
    },
    {
      "target_pose": {
        "pose_type": "base",
        "name": "concierge_init"
      },
      "duration_seconds": 1.0,
      "hold_seconds": 0.0
    }
  ],
  "created_at": "2026-09-12T10:00:00Z",
  "notes": "Present with the robot's left arm"
}
```

This JSON is the editable action source definition. The compilation step
resolves these pose references and samples a runtime trajectory.

`ActionService` saves definitions atomically under `data/actions/definitions/`.
Before saving or compiling, it resolves every reference through `PoseService`
and verifies that the referenced file name, embedded pose name, pose type, joint
set, limits, and robot model all agree. A saved definition remains readable if
a pose is later removed, but resolution reports the missing reference and the
action cannot be compiled.

## In-memory trajectory generation

`ActionService.generate_trajectory()` resolves the action and produces samples
for the canonical 17 upper-body joints. Each transition uses a minimum-jerk
reference, so velocity and acceleration are zero at every keyframe. Pink solves
the posture at each sample while enforcing the URDF position and velocity
limits.

Each transition also has `hold_seconds`. Zero continues immediately; a positive
value inserts exact, stationary samples at the target pose before the next
minimum-jerk transition begins.

The requested sampling frequency sets the maximum sample interval. If a
transition duration is not an exact multiple of that interval, its samples are
spaced slightly closer together so the keyframe timestamp and total action
duration remain exact. Generation fails when a duration is too short for Pink
to reach the target within the robot's velocity limits.

The default trajectory clock is 25 FPS, matching ARDy's native G1 checkpoints.
It remains configurable for experiments and later robot-controller integration.

## Action trajectory NPZ

`ActionService.save_trajectory()` writes one pickle-free NPZ archive under
`data/actions/trajectories/`. It follows ARDy's choice of an NPZ container with
embedded FPS metadata, while keeping a smaller action-recorder-specific upper-body
schema:

- `schema_version`: archive schema version
- `action_name`, `robot_model_id`: action identity
- `fps`: requested trajectory frequency, normally 25
- `joint_names`: canonical 17 upper-body joint names
- `timestamps`: exact sample times in seconds
- `joint_positions`: `[sample, joint]` positions in radians
- `keyframe_sample_indices`, `source_pose_names`: original keyframe mapping
- `keyframe_hold_seconds`: hold duration aligned with every source keyframe
- `max_tracking_error`: maximum Pink reference error in radians

Archive loading disables NumPy pickle support and revalidates field names,
array shapes, timestamps, G1 joint order, model identity, and joint limits.

## MuJoCo action validation

`ActionService.render_saved_trajectory_preview()` loads the saved NPZ again,
revalidates it, applies every 17-joint sample to a fresh MuJoCo state, and
creates one synchronized animated GIF containing the five established camera
views. This is kinematic playback: it calls forward kinematics for visual
inspection but does not step dynamics or send commands to a robot.

Run the end-to-end service demo with:

```bash
MUJOCO_GL=egl uv run python component/action_service.py
```

It generates and saves a temporary 25 FPS trajectory, reloads that NPZ, and
writes `data/action_previews/concierge_presentation_demo.gif`. Generated action
previews are ignored by Git and may be regenerated in place.

## Action authoring UI

The top-level Action tab keeps `base/concierge_init` as the fixed first and last
keyframes. Choose a saved complete base or composed pose, set the travel time
into it and how long to hold it, then click **Add frame**. A hold of zero means
no pause. Repeat this for as many intermediate frames as needed, then set the
final return duration.

- **Save definition** writes the editable JSON action definition.
- **Compile NPZ** generates and downloads the time-sampled trajectory.
- **Load** restores a saved definition, including keyframe order and durations.
- **Play** runs a compiled NPZ in the shared MuJoCo/Viser simulation with
  pause/resume, stop, loop, progress, and current-transition status.

Existing JSON and NPZ files are protected unless **Allow replacing existing
action JSON and NPZ files** is enabled. Compilation reports unreachable short
transitions from Pink as a visible UI error; increase that transition duration
and compile again.
