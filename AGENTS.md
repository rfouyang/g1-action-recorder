# AGENTS.md

## Project Architecture

This project follows a **business-capability-first robotics application architecture**.

The main architectural principles are:

- `app/` contains application entrypoints and presentation-layer code.
- `component/` contains reusable business capabilities.
- `util/` contains infrastructure helpers and external-system adapters.
- `config/` contains configuration.
- `tests/` mirrors the production code structure where practical.
- UI and API are separate presentation surfaces.
- UI and API must not depend directly on each other.
- Both UI and API access business capabilities through the application layer or shared components.
- Prefer simple, explicit Python architecture over excessive abstraction.

Do not reorganize the project into generic folders such as:

```text
controllers/
repositories/
managers/
handlers/
services/
```

at the project root.

Prefer domain-oriented modules such as:

```text
joint_control/
navigation/
teleop/
simulation/
retarget/
vision/
```

---

# Recommended Project Structure

```text
project/
├── app/
│   ├── application.py
│   │
│   ├── api/
│   │   ├── api_main.py
│   │   ├── dependencies.py
│   │   │
│   │   ├── joints/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   └── websocket.py        # only when required
│   │   │
│   │   ├── teleop/
│   │   ├── navigation/
│   │   ├── simulation/
│   │   └── system/
│   │
│   └── ui/
│       ├── ui_main.py
│       ├── context.py
│       │
│       ├── state/
│       │   ├── ui_state.py
│       │   └── ...
│       │
│       ├── panels/
│       │   ├── overview.py
│       │   ├── joints.py
│       │   ├── teleop.py
│       │   ├── simulation.py
│       │   ├── retarget.py
│       │   ├── navigation.py
│       │   └── system.py
│       │
│       ├── templates/
│       │   ├── base.html
│       │   ├── layout/
│       │   ├── components/
│       │   └── panels/
│       │
│       └── static/
│           ├── css/
│           │   └── app.css
│           └── js/
│               ├── app.js
│               ├── websocket.js
│               ├── viser.js
│               └── panels/
│
├── component/
│   ├── common/
│   ├── joint_control/
│   ├── teleop/
│   ├── navigation/
│   ├── simulation/
│   ├── retarget/
│   └── vision/
│
├── util/
│   ├── ros2_helper.py
│   ├── viser_helper.py
│   ├── mujoco_helper.py
│   └── ...
│
├── config/
├── tests/
├── pyproject.toml
└── AGENTS.md
```

Do not create empty folders only to satisfy this structure. Add folders when the corresponding functionality exists.

---

# Application Layer

`app/application.py` is the main **composition root**.

It owns and assembles long-lived application-level business capabilities.

Example:

```python
class RobotApplication:
    def __init__(self) -> None:
        self.robot = RobotService()

        self.joint_control = JointControlService(
            robot=self.robot,
        )

        self.teleop = TeleopService(
            robot=self.robot,
        )

        self.navigation = NavigationService(
            robot=self.robot,
        )

        self.simulation = SimulationService()
```

`RobotApplication` should contain:

- long-lived business services;
- shared robot interfaces;
- shared application resources;
- dependencies required by multiple presentation surfaces.

It must not contain presentation state such as:

```text
active_panel
selected_joint
camera_view
open_modal
selected_tab
HTML templates
browser clients
```

Those belong to the UI layer.

Avoid turning `RobotApplication` into a god object.

---

# API Architecture

The API uses **FastAPI**.

Treat `APIRouter` as the equivalent of a Blueprint.

Organize API code by business domain:

```text
app/api/
├── dependencies.py
├── joints/
│   ├── router.py
│   ├── schemas.py
│   └── websocket.py
├── navigation/
└── teleop/
```

Typical API domain:

```python
router = APIRouter(
    prefix="/joints",
    tags=["joints"],
)
```

The main API entrypoint should mostly assemble routers:

```python
app.include_router(joints.router)
app.include_router(navigation.router)
app.include_router(teleop.router)
```

Keep `api_main.py` thin.

---

# FastAPI Dependencies

Do not create a duplicated `api/context.py`.

Use:

```text
app/api/dependencies.py
```

for FastAPI dependency injection.

Example:

```python
def get_application(
    request: Request,
) -> RobotApplication:
    return request.app.state.robot_app
```

Routes may access business capabilities through dependency injection:

```python
@router.post("/target")
def set_target(
    command: JointTarget,
    app: RobotApplication = Depends(get_application),
):
    return app.joint_control.set_target(
        command.joint,
        command.value,
    )
```

FastAPI-specific objects such as:

```text
Request
Response
WebSocket
Depends
APIRouter
HTTPException
```

must stay inside the API layer whenever possible.

Do not import FastAPI inside core business components.

---

# UI Architecture

The UI is organized around **business panels**.

The main concept is:

```text
Navigation Item
      ↓
Panel
      ↓
Business Capability
```

Each top-level navigation item should normally correspond to one business workspace.

Example navigation:

```text
Overview
Joints
Teleop
Retarget
Navigation
Simulation
Vision
System
```

A Panel represents the user's business workflow, not simply a visual component.

Examples:

```text
Joint Panel
Navigation Panel
Simulation Panel
Retarget Panel
```

---

# Panel Structure

Python Panel logic belongs in:

```text
app/ui/panels/
```

Example:

```text
app/ui/panels/joints.py
app/ui/panels/navigation.py
```

A panel may define:

```python
class JointPanel:
    name = "Joints"
    icon = "..."
    order = 20
    template = "panels/joints.html"

    def register(self, ctx):
        ...

    def activate(self, ctx):
        ...

    def deactivate(self, ctx):
        ...
```

Keep panel lifecycle logic in Python.

Do not embed large HTML strings inside panel Python files.

---

# UI Templates

All Jinja templates are centralized under:

```text
app/ui/templates/
```

Do not place separate `templates/` directories inside every panel.

Recommended layout:

```text
templates/
├── base.html
├── layout/
│   ├── navbar.html
│   └── status_bar.html
├── components/
│   ├── status_badge.html
│   ├── viewer.html
│   └── panel_header.html
└── panels/
    ├── overview.html
    ├── joints.html
    ├── teleop.html
    ├── navigation.html
    └── simulation.html
```

Use Jinja:

```text
extends
include
macro
```

to share common UI fragments.

Avoid duplicating markup across panels.

---

# Static Assets

All browser assets are centralized under:

```text
app/ui/static/
```

Do not create a separate `static/` folder inside every Panel.

Recommended structure:

```text
static/
├── css/
│   └── app.css
└── js/
    ├── app.js
    ├── websocket.js
    ├── viser.js
    └── panels/
        ├── joints.js
        ├── navigation.js
        └── teleop.js
```

Panel-specific JavaScript is encouraged when the behavior is genuinely panel-specific.

Avoid creating panel-specific CSS unless necessary.

Prefer daisyUI and Tailwind utility classes for layout and styling.

---

# UI Technology Stack

Preferred frontend stack:

```text
FastAPI
Jinja2
HTMX
daisyUI
Tailwind CSS
Alpine.js when useful
AG Grid for complex tables
Viser for 3D
WebSocket for realtime robot data
```

Avoid introducing React, Vue, Next.js, Vite, or another frontend application framework unless there is a strong technical reason.

The project should remain Python-centered and lightweight.

---

# daisyUI

Use daisyUI as the primary UI design system.

Prefer existing daisyUI components:

```text
navbar
tabs
button
badge
card
drawer
modal
dropdown
table
alert
tooltip
loading
progress
```

Do not invent custom styling when an existing daisyUI component is sufficient.

Use Tailwind mainly for:

- layout;
- spacing;
- sizing;
- grid;
- flex;
- positioning.

Avoid unnecessary custom CSS.

---

# UI Design Principles

This is a **robotics engineering console**, not a marketing website or generic SaaS dashboard.

Prioritize:

- high information density;
- fast visual scanning;
- compact layouts;
- clear system state;
- predictable interaction;
- low cognitive load;
- consistent alignment;
- useful status colors;
- efficient use of screen space.

Avoid:

- excessive empty space;
- oversized headings;
- unnecessary gradients;
- decorative cards everywhere;
- large rounded containers without purpose;
- excessive animations;
- generic AI-generated SaaS aesthetics.

Use color primarily to communicate meaning:

```text
success
warning
error
connected
disconnected
active
disabled
```

---

# UI Context

`app/ui/context.py` is UI-specific.

It may contain dependencies such as:

```python
@dataclass
class UIContext:
    app: RobotApplication
    viser: ViserManager
    state: UIState
```

UIContext may contain:

- the shared RobotApplication;
- Viser runtime;
- Panel registry;
- UI state;
- UI event infrastructure.

Do not duplicate business services directly inside UIContext when they already exist in `RobotApplication`.

Prefer:

```python
ctx.app.joint_control
```

rather than:

```python
ctx.joint_control
ctx.app.joint_control
```

both existing simultaneously.

---

# UI State vs Business State

Keep UI state separate from robot/business state.

Business state example:

```python
RobotState(
    joint_position=...,
    joint_velocity=...,
    torque=...,
    base_pose=...,
)
```

UI state example:

```python
UIState(
    active_panel="joints",
    selected_joint="left_knee",
    camera_view="left45",
    follow_robot=True,
)
```

Business state belongs in:

```text
component/
```

or shared application services.

UI state belongs in:

```text
app/ui/state/
```

Never use UI state as the source of truth for robot state.

---

# UI and API Independence

The UI and API must not directly depend on each other.

Do not implement:

```text
UI
 ↓ HTTP
API
 ↓
Component
```

when UI and API run in the same application process.

Instead:

```text
               RobotApplication
                      ▲
              ┌───────┴───────┐
              │               │
            UI             API
```

Both presentation layers use the same business capabilities.

An external client may call the API normally.

---

# Components

`component/` contains actual business capabilities.

Examples:

```text
component/
├── joint_control/
├── teleop/
├── navigation/
├── simulation/
├── retarget/
└── vision/
```

Each component should be usable without the Web UI.

For example:

```python
JointControlService
```

should be callable from:

- UI;
- FastAPI;
- CLI;
- tests;
- ROS integration;
- scripts.

Do not import:

```text
FastAPI
Jinja2
HTMX
daisyUI
browser state
```

inside business components.

---

# Panel and Component Relationship

Panel and Component are related but are not required to be strictly 1:1.

Typical case:

```text
Joint Panel
    ↓
joint_control
```

A Panel may also aggregate capabilities:

```text
Overview Panel
├── joint_control
├── navigation
├── teleop
└── system_monitor
```

Another example:

```text
Simulation Panel
├── simulation
├── joint_control
└── retarget
```

Definition:

> Panel is a user-facing business workspace.

> Component is a reusable software business capability.

---

# Viser Architecture

Viser is the main 3D visualization system.

Prefer one shared Viser runtime rather than creating a new Viser server for each panel.

Use a shared manager such as:

```python
ViserManager
```

Panels may own logical scene groups:

```text
/scene/joints
/scene/teleop
/scene/simulation
/scene/retarget
/scene/navigation
```

When changing panels:

```text
activate panel
      ↓
switch visible scene
      ↓
switch camera configuration
      ↓
switch UI controls
      ↓
switch telemetry subscription if needed
```

Prefer scene visibility switching over destroying and rebuilding large scenes.

---

# Viser Performance

For robot visualization:

- load robot meshes once;
- reuse scene handles;
- update transforms or joint configuration only;
- do not recreate meshes every frame;
- keep physics/control rate separate from visualization rate.

Typical rates:

```text
Robot control / simulation:
100–1000+ Hz depending on subsystem

Browser visualization:
20–50 Hz

Dashboard telemetry:
10–30 Hz depending on data
```

Do not force browser UI updates at control-loop frequency.

---

# Robot 3D Camera

Support a freely controllable camera plus useful robot-relative presets.

Recommended views:

```text
Free
Front
Left 45°
Left
Right 45°
Right
```

Camera presets should preferably be defined relative to the robot coordinate frame rather than fixed world coordinates.

Preserve panel-specific or user camera state when practical.

---

# Realtime Data

Use WebSocket for continuously changing robot data such as:

```text
joint position
joint velocity
torque
current
temperature
robot pose
navigation state
simulation state
```

Do not use HTMX polling for high-frequency telemetry.

HTMX is appropriate for low-frequency interactions such as:

```text
forms
configuration
panel fragments
settings
simple actions
```

---

# Joint UI

For joint inspection, prefer a structured table instead of a long list of independent widgets.

AG Grid is preferred when the table requires:

- many rows;
- sorting;
- filtering;
- editable values;
- sliders;
- row selection;
- status rendering;
- efficient updates.

Typical Joint Inspector columns:

```text
Joint
Target
Actual
Error
Velocity
Torque
Current
Temperature
Limit
Enabled
Status
```

Target and actual values must remain conceptually separate.

Preferred flow:

```text
UI target
    ↓
controller / simulation / robot
    ↓
actual state
    ↓
telemetry
    ↓
UI + Viser
```

Do not silently treat target as actual except in explicit preview-only modes.

---

# ROS2 / MuJoCo / Hardware

Keep external runtime integrations behind components or infrastructure helpers.

Examples:

```text
ROS2
MuJoCo
Unitree SDK
Redis
ZMQ
camera SDKs
```

Do not spread transport-specific code throughout UI panels.

Prefer boundaries such as:

```python
RobotInterface
SimulationInterface
NavigationInterface
```

or focused adapter classes when useful.

Avoid creating interfaces merely for abstraction if only one simple implementation exists.

Use abstraction when it improves testability or isolates external dependencies.

---

# util/

Use `util/` for infrastructure-oriented helpers and thin external adapters.

Examples:

```text
ros2_helper.py
viser_helper.py
mujoco_helper.py
network_helper.py
logging_helper.py
```

Do not place core business logic in `util/`.

If a helper starts owning substantial business behavior, move it into a component.

---

# Naming

Prefer descriptive domain names.

Good:

```text
joint_control
task_execution
map_building
navigation
retarget
teleop
```

Avoid vague names such as:

```text
manager
handler
processor
helper
misc
common_utils
core_logic
```

unless the responsibility is genuinely generic and obvious.

Class names should describe responsibility clearly:

```text
JointControlService
NavigationService
ViserManager
RobotApplication
JointPanel
```

---

# File Size and Complexity

Keep entrypoint files thin.

Avoid very large:

```text
ui_main.py
api_main.py
application.py
panel.py
```

When a file becomes difficult to navigate, split by responsibility.

Do not split tiny functionality into excessive files purely for architectural symmetry.

Prefer meaningful cohesion over strict file-count rules.

---

# Dependencies

Use `uv` for Python environment and dependency management unless the project explicitly requires another tool.

Prefer dependencies defined in:

```text
pyproject.toml
```

Avoid unnecessary dependencies.

Before introducing a new framework or library:

1. check whether the existing stack already solves the problem;
2. prefer lightweight libraries;
3. avoid introducing another frontend build system unless necessary.

---

# Testing

Business components should be testable without launching the browser UI.

Prefer tests around:

- component behavior;
- state transitions;
- limits;
- robot command validation;
- API schemas;
- API endpoints;
- panel-independent utility behavior.

Mock external robot/hardware dependencies when practical.

Do not require a real robot for ordinary unit tests.

---

# Safety for Robot Commands

Any UI command that can move real hardware must respect the robot control safety layer.

Do not send unrestricted browser values directly to hardware.

Validate:

- joint limits;
- velocity limits;
- torque/current limits when relevant;
- enabled state;
- robot mode;
- communication status.

Real robot control must support appropriate stop/interlock mechanisms.

UI widgets are not safety mechanisms.

---

# Coding Style

Prefer:

- explicit code;
- small cohesive classes;
- type hints;
- dataclasses where appropriate;
- clear state ownership;
- simple dependency flow;
- predictable naming.

Avoid:

- unnecessary design patterns;
- deep inheritance;
- metaprogramming for ordinary application logic;
- global mutable state;
- hidden side effects;
- premature generic frameworks.

When choosing between a clever abstraction and straightforward code, prefer straightforward code unless the abstraction clearly reduces repeated complexity.

---

# Architecture Summary

The intended dependency direction is:

```text
                    app/application.py
                           │
                           ▼
                      component/
                       ▲       ▲
                      /         \
                     /           \
               app/ui           app/api
             panel-oriented    router-oriented
```

Infrastructure dependencies sit below the business capabilities where appropriate:

```text
UI / API
   ↓
Application
   ↓
Components
   ↓
ROS2 / MuJoCo / Unitree / external systems
```

The main organizing principles are:

```text
app/ui
= panel-oriented

app/api
= APIRouter/domain-oriented

component
= business-capability-oriented

util
= infrastructure-oriented
```

Preserve these boundaries when adding or refactoring features.

---

# Before Adding a New Feature

When implementing a new feature, first decide:

1. Is this a new user-facing business workspace?
   - Add a new UI Panel.

2. Is this a new external API domain?
   - Add a new API router package.

3. Is this reusable business logic?
   - Add or extend a `component/`.

4. Is this only browser presentation?
   - Keep it under `app/ui`.

5. Is this only FastAPI transport/schema logic?
   - Keep it under `app/api`.

6. Is this external-system integration or a thin infrastructure helper?
   - Put it under `util/` or the relevant component adapter.

Do not place code based only on convenience. Place it according to ownership and responsibility.