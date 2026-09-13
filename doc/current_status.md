# G1 Action Recorder 当前进度

更新时间：2026-09-13

仓库名称：`g1-action-recorder`

本地目录：`/home/rfouyang/workspace/services/g1-action-recorder`

## 当前结论

3D 工程控制台已经完成第一轮端到端功能。当前唯一 Web UI 使用 FastAPI、
Jinja2、daisyUI、Tailwind CSS 和 Viser，并通过共享的 `RobotApplication`
直接访问业务能力；UI 与外部 REST/WebSocket API 保持独立，不互相调用。

当前阶段仅操作 MuJoCo 仿真状态，不会向真实机器人发送运动命令。

## 启动方式

直接在 IDE 中右键运行：

```text
app/g1_3d_main.py
```

然后打开：

```text
http://127.0.0.1:8000
```

入口文件会自动：

- 设置默认的 `MUJOCO_GL=egl`；
- 检查并按需编译 Tailwind/daisyUI CSS；
- 启动 FastAPI Web 应用；
- 启动共享 Viser 服务；
- 在进程退出时停止 Viser。

不需要手工执行 `npm run build:css` 或设置 `MUJOCO_GL`。

## 已完成的架构

```text
app/g1_3d_main.py
├── app/application.py          # 共享业务能力组合根
├── app/ui_g1_3d/               # Jinja/daisyUI/Viser UI
├── app/api_g1_3d/              # 独立 FastAPI REST/WebSocket API
└── component/                  # Pose、Action、Simulation 业务能力
```

- `app/ui_g1_3d/`：新的三工作区 Web UI。
- `app/api_g1_3d/`：系统健康、仿真状态、关节更新和 WebSocket。
- `app/application.py`：持有共享的 `PoseService`、`ActionService` 和
  `SimulationService`。
- UI 不通过 HTTP 调用同进程 API；UI 和 API 分别使用共享业务能力。

## 新 3D UI 已完成功能

### 1. 顶部导航

顶部提供三个工作区：

1. Pose Recorder
2. Pose Composer
3. Action

左侧编辑区域约占屏幕宽度的三分之一，右侧 Viser 约占三分之二。整体采用
daisyUI `wireframe` 主题，保持紧凑的机器人研发工具风格。

### 2. Viser 机器人视图

- G1 URDF 只加载一次，之后只更新关节配置。
- Viser 以最高约 30 Hz 同步共享 MuJoCo 状态。
- 支持鼠标自由旋转、平移和缩放视角。
- 支持六个机器人相对固定视角：Front、Back、Left、Right、Front-left 45°、
  Front-right 45°。
- 六个预设使用一致的 2.30 m 观察距离、45° 垂直视场角和全身中心焦点，
  让机器人约占画面高度七成，并减少无关地面区域。
- 固定视角切换使用约 0.7 秒的平滑相机过渡，不会瞬间跳转。

方向规则已经统一：

- 所有 left/right 都从机器人自身视角定义。
- Front 是观察者面对机器人正面。
- Back 是观察机器人背面。
- Left 是从机器人的左侧观察。
- Right 是从机器人的右侧观察。
- “robot left arm” 始终表示机器人的左臂；“robot right arm” 始终表示机器人的
  右臂。

### 3. Pose Recorder

- 显示并编辑 17 个上半身关节。
- Target 与 Actual 分开显示，并通过 UI WebSocket 同步仿真状态。
- 每个关节右侧都有独立 Reset 按钮。
- Reset 值来自 `base/concierge_init`，不是固定零位。
- 支持整组重置和保存 `base`、`left_arm`、`right_arm` pose。
- 保存时验证关节集合和 MuJoCo 限位。
- 默认拒绝覆盖同名 pose，用户必须显式启用替换。
- 颜色分组：腰部为中性色、机器人左臂为蓝色、机器人右臂为橙色。

### 4. Pose Composer

- 以完整 base pose 为基础。
- 可选替换机器人左臂、右臂或两侧手臂。
- 选择来源后可直接预览到共享 MuJoCo/Viser 状态。
- 可保存最终 `composed` pose，并记录 `source_parts`。
- 支持同名覆盖保护。

### 5. Action

- 固定以 `base/concierge_init` 开始并返回该姿态结束。
- 中间帧只允许完整的 `base` 或 `composed` pose，不允许直接使用局部手臂 pose。
- 可按顺序添加多个中间帧，并设置每帧的 travel time 和 hold time。
- 可删除单个中间帧或清空全部中间帧；固定首尾帧不能删除。
- 点击中间帧名称可把该 pose 显示到 MuJoCo/Viser。
- 可保存 JSON action definition，并重新加载继续编辑。
- 可设置最终返回时间和 trajectory sample frequency。
- 可通过现有 Pink/Pinocchio 轨迹能力编译 NPZ。
- 编译后显示采样数、时长、频率和最大跟踪误差，并可下载 NPZ。
- JSON 和 NPZ 都有显式覆盖保护。
- 可从已编译 NPZ 列表选择 trajectory，并在共享 MuJoCo/Viser 中播放。
- 支持 Play、Pause/Resume、Stop 和循环播放。
- Stop 会回到 trajectory 的第一个 `concierge_init` 样本。
- 播放状态、样本位置、经过时间和进度通过 UI WebSocket 实时更新。
- 后台播放器按 trajectory 时间戳更新仿真；Viser 保持独立的可视化刷新频率。
- 播放区显示当前语义阶段：Keyframe、Moving 或 Holding。
- Moving 状态显示来源 pose → 目标 pose；到达后显示 pose 名称和 keyframe 序号。
- 已决定不把原五视角 MuJoCo GIF 加入新 UI；交互可视化统一使用 Viser 六视角。

## API 当前能力

外部客户端可使用：

```text
GET /api/g1/system/health
GET /api/g1/simulation/state
PUT /api/g1/simulation/joints
WS  /api/g1/simulation/ws
```

这些接口与新 UI 共用同一个 `RobotApplication` 和仿真状态，但 UI 不依赖这些
API 路由。

## 验证状态

2026-09-13 最新验证：

- `uv run python -m unittest discover -s tests`
  - 101 个测试全部通过（已移除旧 Gradio UI 的对应测试）。
- `uv run ruff check .`
  - 通过。
- `node --check app/ui_g1_3d/static/js/panels/action.js`
  - 通过。
- `npm run build:css`
  - 通过。
- `uv run python app/g1_3d_main.py`
  - FastAPI 与 Viser 均能正常启动和关闭。

新增 Action 路由测试覆盖：

- 页面控件和完整 pose 来源；
- action definition 保存、覆盖保护和重新加载；
- NPZ 编译、重新验证和下载；
- Action pose 预览更新共享仿真状态。
- 播放、暂停、恢复和停止路由；
- 播放状态 WebSocket；
- 后台播放器的完成、暂停保持、停止复位和循环行为。
- 根据 NPZ keyframe index 和 hold metadata 区分 transition、keyframe 和 hold。

实际运行 `app/g1_3d_main.py` 后，已使用仓库中的 `test.npz` 完成
Play → Pause → Resume → Stop 冒烟测试，FastAPI、MuJoCo 和 Viser 均正常关闭。

## 尚未完成 / 下一步建议

建议下一次继续完善 Action 的检查和播放体验：

1. 完成浏览器人工视觉检查，包括窄窗口、长 action 名称和多 keyframe 滚动。
2. 根据实际使用反馈决定是否增加播放速度和可拖动时间轴。

真实机器人控制仍不在当前范围内。后续如果接入硬件，必须先实现独立的安全
控制层、模式检查、限位、速度限制、通信状态检查以及停止/联锁机制。
