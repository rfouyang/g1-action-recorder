# G1 Action Recorder Current State

Last updated: 2026-09-13

## Project status

`g1-action-recorder` currently provides a simulation-only authoring workflow for
Unitree G1 upper-body poses and pose-based robot actions. Pose recording,
pose composition, arm mirroring, time-sampled action generation, NPZ
persistence, and five-camera MuJoCo validation are implemented.

No physical robot commands are sent. Unitree SDK2/DDS integration and real G1
action execution have not been implemented.

## Repository structure

The application follows the dependency direction required by `AGENTS.md`:

```text
app -> component -> util
```

- `app/g1_3d_main.py`: combined process entry point and lifecycle owner.
- `app/application.py`: composition root for long-lived business capabilities.
- `app/ui_g1_3d/`: FastAPI/Jinja/daisyUI panels and the shared Viser runtime.
- `app/api_g1_3d/`: independent REST and WebSocket presentation surface.
- `component/pose_service.py`: pose validation, persistence, composition,
  mirroring, and preview orchestration.
- `component/action_service.py`: action definitions, Pink trajectory generation,
  NPZ persistence, and MuJoCo action preview orchestration.
- `component/common/`: immutable pose/action models and the canonical G1 joint
  schema.
- `util/`: JSON/NPZ file helpers and MuJoCo/Pink adapters.
- `asset/g1/`: pinned G1 URDF, MJCF, meshes, metadata, and DDS joint mapping.
- `data/`: saved pose/action definitions and generated preview output.
- `tests/`: `unittest` coverage for models, services, helpers, UI routes,
  WebSockets, and Viser synchronization.

Implementation and test Python files expose `demo_xxx()`, `main()`, and a
standard `if __name__ == "__main__"` entry point so they can be run directly.

## Environment

- Python: `>=3.10,<3.11`
- Environment and dependency manager: `uv`
- Main packages: FastAPI, Jinja2, MuJoCo, NumPy, Pillow, Pink, Pinocchio,
  `quadprog`, Uvicorn, and Viser
- Default headless MuJoCo backend: EGL

Setup and test commands:

```bash
uv python install 3.10
uv sync
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv lock --check
```

Run the UI:

```bash
uv run python app/g1_3d_main.py
```

The UI is served at `http://127.0.0.1:8000` by default. Direct file execution
selects EGL for MuJoCo and rebuilds stale daisyUI assets automatically.

## G1 model contract

The canonical model is
`unitree_g1_29dof_rev_1_0_fake_hand`: G1 revision 1.0 with fixed rubber hands.

- 29 scalar robot joints in Unitree DDS order.
- 12 leg joints.
- 3 waist joints.
- 7 robot-left arm joints.
- 7 robot-right arm joints.
- 17 authored upper-body joints: waist plus both arms.
- No actuated hand joints.
- Metadata currently records `mode_machine = 5` for this model variant. This
  value must be checked against the physical robot state before hardware work.

Asset provenance is recorded in `asset/g1/model_metadata.json` and
`asset/g1/UPSTREAM.md`:

- URDF/MJCF source: `unitreerobotics/unitree_ros` commit
  `7d6075f7f58588b189b940130e3edab3c839b2df`.
- DDS joint-index source: `unitreerobotics/unitree_mujoco` commit
  `1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d`.

Pink uses the exact fixed-base URDF. MuJoCo uses the matching MJCF. Both assets
are validated against the metadata and canonical DDS joint schema.

## Coordinate and camera conventions

`left` and `right` always mean the robot's anatomical left and right. Images are
unmirrored and described from a camera facing the robot, so the robot's left arm
appears on the image's right in the front view.

The interactive Viser viewer provides six robot-relative camera presets:

1. Robot front.
2. Robot back.
3. Robot-left side.
4. Robot-right side.
5. Front-left 45 degrees.
6. Front-right 45 degrees.

Camera changes use a smooth transition. Mouse orbit, pan, and zoom remain
available. All presets use a tighter 2.30 m orbit, a 45-degree vertical field
of view, and a full-body-centered target so the robot fills roughly 70 percent of
the viewer height with less unused ground. Viser follows the shared MuJoCo
kinematic state and does not send motor commands.

## Pose workflow

Four pose types are supported:

- `base`: all 17 upper-body joints.
- `left_arm`: the 7 robot-left arm joints.
- `right_arm`: the 7 robot-right arm joints.
- `composed`: all 17 upper-body joints after composition.

Pose JSON files use schema version 1 and contain the model ID, exact named joint
values, source, UTC creation timestamp, optional source parts, and notes. Joint
sets, numeric values, limits, model identity, embedded names, and file names are
validated when loading and saving.

### Pose Recorder tab

- Edits the 17 upper-body target joints while showing target and actual values.
- Uses the saved `base/concierge_init` pose for initial and per-joint reset
  values.
- Updates shared MuJoCo state over a UI WebSocket; Viser follows that state.
- Saves base, robot-left-arm, or robot-right-arm poses with explicit overwrite
  protection.
- Uses separate colors for waist, robot-left arm, and robot-right arm groups.

Physical-pose recording is not connected yet. The joint schema already provides
`extract_from_dds()` for extracting the correct base/arm joint subset from a
29-motor `LowState` position sequence.

### Pose Composer tab

Composition always starts with every value in a base pose, then overwrites the
selected arm subsets:

```text
base
base + left_arm
base + right_arm
base + left_arm + right_arm
```

The result is saved as a complete `composed` pose and can be inspected from all
six interactive Viser presets. Partial arm poses cannot be used directly as
action keyframes.

### Current saved poses

The repository currently includes:

- `data/poses/base/concierge_init.json`
- `data/poses/left_arm/concierge_present_left.json`
- `data/poses/right_arm/concierge_present_right.json`
- `data/poses/composed/concierge_present_left.json`
- `data/poses/composed/concierge_present_right.json`

## Action workflow

Every action has at least three keyframes and follows this invariant:

```text
base/concierge_init
    -> one or more complete base/composed intermediate poses
    -> base/concierge_init
```

Each transition has two timing values:

- `duration_seconds`: positive travel time from the preceding keyframe into the
  target keyframe.
- `hold_seconds`: nonnegative time to maintain the exact target keyframe before
  starting the next transition. Zero means no hold.

Action JSON uses schema version 1. `hold_seconds` is included in newly saved
definitions; older definitions without it load with a zero hold.

### Action tab

- Adds any number of intermediate complete poses in order.
- Sets incoming travel time and hold time for every intermediate pose.
- Removes individual intermediate frames or clears all intermediate frames.
- Keeps `base/concierge_init` as fixed start and return frames.
- Saves and loads editable JSON action definitions.
- Compiles the current editor state into an NPZ trajectory.
- Displays/downloads the compiled NPZ.
- Plays a compiled NPZ in shared MuJoCo/Viser with pause/resume, stop, loop,
  elapsed time, progress, and sample position.
- Reports Keyframe, Moving, and Holding phases from NPZ keyframe metadata.
- Protects existing JSON and NPZ files unless overwrite is enabled.
- Reports invalid names, missing poses, unreachable short transitions, and
  overwrite conflicts as visible UI errors.

## Trajectory generation

`ActionService.generate_trajectory()` resolves every pose reference, extracts
the canonical 17 upper-body joints, and asks Pink to track a minimum-jerk
posture reference.

- Position and velocity limits come from the pinned G1 URDF.
- Velocity and acceleration are zero at movement endpoints.
- Transition timestamps and total requested duration remain exact.
- A requested frequency controls the maximum interval between samples.
- The default is 25 Hz, matching the researched ARDy G1 motion frequency.
- A hold greater than zero inserts stationary samples at the exact keyframe.
- A zero hold inserts no extra samples.
- Generation fails if a travel duration is too short to reach the target within
  the model's velocity limits.

## NPZ action format

New trajectory archives use schema version 2 and are saved under
`data/actions/trajectories/`. Loading uses `allow_pickle=False` and revalidates
all fields, shapes, values, timestamps, joint order, model identity, limits, and
boundary poses.

Schema-2 arrays:

- `schema_version`
- `action_name`
- `robot_model_id`
- `fps`
- `joint_names`
- `timestamps`
- `joint_positions`
- `keyframe_sample_indices`
- `source_pose_names`
- `keyframe_hold_seconds`
- `max_tracking_error`

`joint_positions` has shape `[sample, joint]` and stores radians. The archive is
self-contained for time-based playback. Schema-1 NPZ files remain loadable and
receive zero-valued keyframe-hold metadata.

## MuJoCo action validation

`ActionService.render_saved_trajectory_preview()` loads the saved NPZ again,
applies every sample without stepping dynamics, renders all five views, labels
them, and writes an animated GIF under `data/action_previews/`.

The five images for a timestamp are composed into a three-column by two-row
canvas. The empty sixth cell remains black. The last GIF frame has a short
visual hold so the ending `concierge_init` pose can be inspected.

Generated pose PNGs and action GIFs are ignored by Git. Saved pose JSON, action
JSON, and trajectory NPZ files are not globally ignored.

## Validation status

The latest verification completed successfully on 2026-09-13:

- Ruff: passed.
- Unit tests: 101 passed after removal of the legacy Gradio UI tests.
- `uv lock --check`: passed.
- EGL MuJoCo rendering: passed.
- NPZ schema-1 backward-compatibility test: passed.

## Known limitations and next work

- No Unitree SDK2 Python package is vendored or installed for this project yet.
- No DDS `LowState` subscription or live physical-pose recorder exists yet.
- No robot command publisher, arm controller, safety state machine, or emergency
  stop integration exists.
- `mode_machine = 5` is metadata derived from the chosen model contract; it has
  not been verified against the user's physical G1.
- Pink and MuJoCo currently use a fixed-base model for upper-body action
  authoring. Balance and whole-body dynamics are not validated.
- MuJoCo action GIF rendering remains an offline validation capability, while
  Viser playback is an interactive kinematic player rather than physics or
  hardware execution. The five-camera GIF will not be added to the web UI;
  interactive visualization uses the six Viser camera presets.
- The Action panel supports append, individual removal, and clear. Arbitrary
  insertion, drag reordering, and editing an existing intermediate row in place
  are not yet implemented.
- Navigation, TTS, concierge dialogue, gesture execution, and the full robot
  application remain future phases.

The next hardware-facing milestone should remain read-only: add the pinned
Unitree SDK2 dependency, subscribe to G1 low-state data, verify the real robot's
model/machine mode and 29-joint ordering, then record base/left-arm/right-arm
poses without publishing any motor command.

## Repository identity

The published project and Python distribution name is `g1-action-recorder`.
The local checkout directory may retain its older workspace name without
affecting imports or package metadata.
