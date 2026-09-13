class ActionPanel {
  constructor(root = document) {
    this.panel = root.querySelector("[data-action-panel]");
    this.saved = root.querySelector("#action-saved");
    this.loadButton = root.querySelector("#action-load");
    this.name = root.querySelector("#action-name");
    this.notes = root.querySelector("#action-notes");
    this.pose = root.querySelector("#action-pose");
    this.travel = root.querySelector("#action-travel");
    this.hold = root.querySelector("#action-hold");
    this.addButton = root.querySelector("#action-add-frame");
    this.clearButton = root.querySelector("#action-clear");
    this.sequence = root.querySelector("#action-sequence");
    this.endFrame = root.querySelector("[data-action-end]");
    this.endIndex = root.querySelector("[data-action-end-index]");
    this.returnDuration = root.querySelector("#action-return");
    this.frequency = root.querySelector("#action-frequency");
    this.overwrite = root.querySelector("#action-overwrite");
    this.saveButton = root.querySelector("#action-save");
    this.compileButton = root.querySelector("#action-compile");
    this.download = root.querySelector("#action-download");
    this.playbackTrajectory = root.querySelector("#action-playback-trajectory");
    this.playButton = root.querySelector("#action-play");
    this.pauseButton = root.querySelector("#action-pause");
    this.stopButton = root.querySelector("#action-stop");
    this.loop = root.querySelector("#action-loop");
    this.playbackStateBadge = root.querySelector("#action-playback-state");
    this.playbackProgress = root.querySelector("#action-playback-progress");
    this.playbackTime = root.querySelector("#action-playback-time");
    this.playbackPhase = root.querySelector("#action-playback-phase");
    this.playbackPath = root.querySelector("#action-playback-path");
    this.playbackSample = root.querySelector("#action-playback-sample");
    this.status = root.querySelector("#action-status");
    this.success = root.querySelector("#action-success");
    this.error = root.querySelector("#action-error");
    this.frames = [];
    this.playbackState = "idle";
    this.playbackSocket = null;
    this.playbackReconnectTimer = null;
  }

  start() {
    if (!this.panel) {
      return;
    }
    this.loadButton.addEventListener("click", () => this.load());
    this.addButton.addEventListener("click", () => this.addFrame());
    this.clearButton.addEventListener("click", () => this.clearFrames());
    this.saveButton.addEventListener("click", () => this.save());
    this.compileButton.addEventListener("click", () => this.compile());
    this.playButton.addEventListener("click", () => this.play());
    this.pauseButton.addEventListener("click", () => this.togglePause());
    this.stopButton.addEventListener("click", () => this.stop());
    this.loop.addEventListener("change", () => this.setLoop());
    this.playbackTrajectory.addEventListener("change", () => this.updatePlaybackControls());
    this.connectPlaybackSocket();
    document.addEventListener("g1:panel-activated", (event) => {
      if (event.detail.panelName === "action") {
        this.refreshSources();
      }
    });
  }

  async refreshSources() {
    const selectedPose = this.pose.value;
    const selectedAction = this.saved.value;
    const selectedTrajectory = this.playbackTrajectory.value;
    try {
      const response = await fetch("/ui/g1-3d/action/sources", {
        headers: { Accept: "application/json" },
      });
      const result = await this.responseJson(response, "Could not refresh action sources");
      this.fillOptions(
        this.pose,
        result.pose_choices.map((choice) => ({ value: choice.value, label: choice.label })),
        selectedPose,
        result.pose_choices.length ? "Select a pose" : "No intermediate poses saved",
      );
      this.fillOptions(
        this.saved,
        result.saved_actions.map((name) => ({ value: name, label: name })),
        selectedAction,
        "Select a definition",
      );
      this.fillOptions(
        this.playbackTrajectory,
        result.compiled_actions.map((name) => ({ value: name, label: name })),
        selectedTrajectory,
        "Select a compiled NPZ",
      );
      this.updatePlaybackControls();
    } catch (error) {
      this.showError(error.message);
    }
  }

  fillOptions(select, options, selected, emptyLabel) {
    select.replaceChildren(new Option(emptyLabel, ""));
    for (const option of options) {
      select.add(new Option(option.label, option.value));
    }
    if ([...select.options].some((option) => option.value === selected)) {
      select.value = selected;
    }
  }

  addFrame() {
    try {
      const reference = this.decodeReference(this.pose.value);
      const duration = this.positiveNumber(this.travel, "Travel time");
      const hold = this.nonnegativeNumber(this.hold, "Hold time");
      this.frames.push({
        pose_type: reference.poseType,
        name: reference.name,
        duration_seconds: duration,
        hold_seconds: hold,
      });
      this.renderFrames();
      this.showStatus(`Added ${reference.poseType}/${reference.name}.`);
      this.preview(reference.poseType, reference.name);
    } catch (error) {
      this.showError(error.message);
    }
  }

  clearFrames() {
    this.frames = [];
    this.renderFrames();
    this.showStatus("Cleared all intermediate frames.");
  }

  removeFrame(index) {
    const [removed] = this.frames.splice(index, 1);
    this.renderFrames();
    this.showStatus(`Removed ${removed.pose_type}/${removed.name}.`);
  }

  renderFrames() {
    for (const row of [...this.sequence.querySelectorAll("[data-action-frame]")]) {
      row.remove();
    }
    this.frames.forEach((frame, index) => {
      const row = document.createElement("li");
      row.className = "list-row border border-base-300 bg-base-100 px-3 py-2";
      row.dataset.actionFrame = String(index);

      const badge = document.createElement("span");
      badge.className = frame.pose_type === "composed"
        ? "badge badge-secondary badge-sm"
        : "badge badge-outline badge-sm";
      badge.textContent = String(index + 2).padStart(2, "0");

      const description = document.createElement("div");
      description.className = "min-w-0";
      const poseButton = document.createElement("button");
      poseButton.className = "block max-w-full truncate text-left text-sm font-semibold hover:underline";
      poseButton.type = "button";
      poseButton.textContent = `${frame.pose_type}/${frame.name}`;
      poseButton.title = "Show this pose in the 3D viewer";
      poseButton.addEventListener("click", () => this.preview(frame.pose_type, frame.name));
      const timing = document.createElement("p");
      timing.className = "font-mono text-[0.65rem] uppercase text-base-content/50";
      timing.textContent = `Travel ${frame.duration_seconds}s · hold ${frame.hold_seconds}s`;
      description.append(poseButton, timing);

      const remove = document.createElement("button");
      remove.className = "btn btn-ghost btn-xs text-error";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${frame.name}`);
      remove.addEventListener("click", () => this.removeFrame(index));

      row.append(badge, description, remove);
      this.sequence.insertBefore(row, this.endFrame);
    });
    this.endIndex.textContent = String(this.frames.length + 2).padStart(2, "0");
    this.download.classList.add("hidden");
  }

  async preview(poseType, name) {
    try {
      const response = await fetch("/ui/g1-3d/action/preview-pose", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ pose_type: poseType, name }),
      });
      await this.responseJson(response, "Could not preview pose");
    } catch (error) {
      this.showError(error.message);
    }
  }

  async load() {
    if (!this.saved.value) {
      this.showError("Select a saved action first.");
      return;
    }
    this.setBusy(this.loadButton, true, "Loading");
    this.hideFeedback();
    try {
      const response = await fetch(
        `/ui/g1-3d/action/definitions/${encodeURIComponent(this.saved.value)}`,
        { headers: { Accept: "application/json" } },
      );
      const result = await this.responseJson(response, "Could not load action");
      this.name.value = result.name;
      this.notes.value = result.notes;
      this.frames = result.frames;
      this.returnDuration.value = result.return_duration_seconds;
      this.renderFrames();
      if ([...this.playbackTrajectory.options].some((option) => option.value === result.name)) {
        this.playbackTrajectory.value = result.name;
      }
      this.showSuccess(
        `Loaded “${result.name}” · ${result.frames.length} intermediate frame(s) · ${this.formatNumber(result.total_duration_seconds)}s total.`,
      );
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setBusy(this.loadButton, false, "Load");
    }
  }

  async save() {
    let payload;
    try {
      payload = this.payload(false);
    } catch (error) {
      this.showError(error.message);
      return;
    }
    this.setActionBusy("save", true);
    this.hideFeedback();
    try {
      const response = await fetch("/ui/g1-3d/action/save", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await this.responseJson(response, "Could not save action");
      await this.refreshSources();
      this.saved.value = result.action_name;
      this.showSuccess(
        `Saved “${result.action_name}” · ${result.keyframe_count} keyframes · ${this.formatNumber(result.total_duration_seconds)}s.`,
      );
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setActionBusy("save", false);
    }
  }

  async compile() {
    let payload;
    try {
      payload = this.payload(true);
    } catch (error) {
      this.showError(error.message);
      return;
    }
    this.setActionBusy("compile", true);
    this.hideFeedback();
    this.download.classList.add("hidden");
    try {
      const response = await fetch("/ui/g1-3d/action/compile", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await this.responseJson(response, "Could not compile trajectory");
      this.download.href = result.download_url;
      this.download.download = `${result.action_name}.npz`;
      this.download.classList.remove("hidden");
      await this.refreshSources();
      this.playbackTrajectory.value = result.action_name;
      this.updatePlaybackControls();
      this.showSuccess(
        `Compiled ${result.sample_count} samples at ${this.formatNumber(result.sample_frequency_hz)} Hz · ${this.formatNumber(result.duration_seconds)}s · max error ${this.formatNumber(result.max_tracking_error)} rad.`,
      );
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setActionBusy("compile", false);
    }
  }

  connectPlaybackSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.playbackSocket = new WebSocket(
      `${protocol}//${window.location.host}/ui/g1-3d/action/playback/ws`,
    );
    this.playbackSocket.addEventListener("message", (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "action_playback") {
          this.updatePlayback(message);
        }
      } catch (error) {
        this.showError(`Invalid playback message: ${error.message}`);
      }
    });
    this.playbackSocket.addEventListener("error", () => {
      this.setPlaybackBadge("Playback link error", "error");
    });
    this.playbackSocket.addEventListener("close", () => {
      this.setPlaybackBadge("Playback offline", "warning");
      window.clearTimeout(this.playbackReconnectTimer);
      this.playbackReconnectTimer = window.setTimeout(
        () => this.connectPlaybackSocket(),
        1000,
      );
    });
  }

  async play() {
    if (!this.playbackTrajectory.value) {
      this.showError("Select or compile a trajectory before playback.");
      return;
    }
    await this.sendPlaybackCommand("play", {
      action_name: this.playbackTrajectory.value,
      loop: this.loop.checked,
    });
  }

  async togglePause() {
    const command = this.playbackState === "paused" ? "resume" : "pause";
    await this.sendPlaybackCommand(command);
  }

  async stop() {
    await this.sendPlaybackCommand("stop");
  }

  async setLoop() {
    await this.sendPlaybackCommand("loop", { enabled: this.loop.checked });
  }

  async sendPlaybackCommand(command, body = null) {
    this.hideFeedback();
    try {
      const response = await fetch(`/ui/g1-3d/action/playback/${command}`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: body === null ? null : JSON.stringify(body),
      });
      const result = await this.responseJson(response, `Could not ${command} playback`);
      this.updatePlayback(result);
    } catch (error) {
      this.showError(error.message);
    }
  }

  updatePlayback(playback) {
    this.playbackState = playback.state;
    if (
      playback.action_name
      && [...this.playbackTrajectory.options].some(
        (option) => option.value === playback.action_name,
      )
    ) {
      this.playbackTrajectory.value = playback.action_name;
    }
    this.loop.checked = playback.loop;
    this.playbackProgress.value = Number(playback.progress || 0) * 100;
    this.playbackTime.textContent = `${this.fixedSeconds(playback.elapsed_seconds)} / ${this.fixedSeconds(playback.duration_seconds)} s`;
    this.playbackSample.textContent = playback.sample_count > 0
      ? `Sample ${playback.sample_index + 1} / ${playback.sample_count}`
      : "No trajectory loaded";
    this.updatePlaybackPhase(playback);
    const statePresentation = {
      idle: ["Idle", "ghost"],
      playing: ["Playing", "success"],
      paused: ["Paused", "warning"],
      stopped: ["Stopped", "ghost"],
      completed: ["Completed", "info"],
      failed: ["Failed", "error"],
    };
    const [label, color] = statePresentation[playback.state] || [playback.state, "ghost"];
    this.setPlaybackBadge(label, color);
    this.updatePlaybackControls();
    if (playback.error) {
      this.showError(`Playback failed: ${playback.error}`);
    }
  }

  updatePlaybackControls() {
    const hasTrajectory = Boolean(this.playbackTrajectory.value);
    const active = this.playbackState === "playing" || this.playbackState === "paused";
    this.playButton.disabled = !hasTrajectory;
    this.pauseButton.disabled = !active;
    this.pauseButton.textContent = this.playbackState === "paused" ? "Resume" : "Pause";
    this.stopButton.disabled = !active && this.playbackState !== "completed";
  }

  updatePlaybackPhase(playback) {
    const phasePresentation = {
      none: ["Waiting", "ghost"],
      keyframe: ["Keyframe", "success"],
      transition: ["Moving", "info"],
      hold: ["Holding", "warning"],
    };
    const [label, color] = phasePresentation[playback.phase] || ["Waiting", "ghost"];
    this.playbackPhase.textContent = label;
    this.playbackPhase.classList.remove(
      "badge-ghost",
      "badge-success",
      "badge-info",
      "badge-warning",
    );
    this.playbackPhase.classList.add(`badge-${color}`);

    let path = "No trajectory loaded";
    if (playback.phase === "transition") {
      path = `${playback.from_pose_name} → ${playback.target_pose_name}`;
    } else if (playback.target_pose_name) {
      path = `${playback.target_pose_name} · keyframe ${playback.keyframe_index + 1}/${playback.keyframe_count}`;
    }
    this.playbackPath.textContent = path;
    this.playbackPath.title = path;
  }

  setPlaybackBadge(label, color) {
    this.playbackStateBadge.textContent = label;
    this.playbackStateBadge.classList.remove(
      "badge-ghost",
      "badge-success",
      "badge-warning",
      "badge-info",
      "badge-error",
    );
    this.playbackStateBadge.classList.add(`badge-${color}`);
  }

  fixedSeconds(value) {
    return Number(value || 0).toFixed(2);
  }

  payload(includeFrequency) {
    const name = this.name.value.trim();
    if (!name) {
      throw new Error("Enter an action name.");
    }
    if (this.frames.length === 0) {
      throw new Error("Add at least one intermediate frame.");
    }
    const result = {
      name,
      notes: this.notes.value,
      frames: this.frames,
      return_duration_seconds: this.positiveNumber(this.returnDuration, "Return time"),
      overwrite: this.overwrite.checked,
    };
    if (includeFrequency) {
      result.sample_frequency_hz = this.positiveNumber(this.frequency, "Trajectory frequency");
    }
    return result;
  }

  decodeReference(value) {
    const separator = value.indexOf("/");
    if (separator < 1 || separator === value.length - 1) {
      throw new Error("Select an intermediate pose first.");
    }
    return { poseType: value.slice(0, separator), name: value.slice(separator + 1) };
  }

  positiveNumber(input, label) {
    const value = Number(input.value);
    if (!Number.isFinite(value) || value <= 0) {
      throw new Error(`${label} must be greater than zero.`);
    }
    return value;
  }

  nonnegativeNumber(input, label) {
    const value = Number(input.value);
    if (!Number.isFinite(value) || value < 0) {
      throw new Error(`${label} cannot be negative.`);
    }
    return value;
  }

  async responseJson(response, fallback) {
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || `${fallback} (${response.status}).`);
    }
    return result;
  }

  setActionBusy(action, busy) {
    const button = action === "save" ? this.saveButton : this.compileButton;
    const label = this.panel.querySelector(`[data-action-${action}-label]`);
    const loading = this.panel.querySelector(`[data-action-${action}-loading]`);
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
    label.textContent = busy
      ? action === "save" ? "Saving" : "Compiling"
      : action === "save" ? "Save definition" : "Compile NPZ";
    loading.classList.toggle("hidden", !busy);
  }

  setBusy(button, busy, label) {
    button.disabled = busy;
    button.textContent = label;
    button.setAttribute("aria-busy", String(busy));
  }

  formatNumber(value) {
    return Number(value).toFixed(4).replace(/\.?0+$/, "");
  }

  showStatus(message) {
    this.status.textContent = message;
    this.status.classList.remove("hidden");
    this.hideError();
  }

  showSuccess(message) {
    this.success.textContent = message;
    this.success.classList.remove("hidden");
    this.hideError();
  }

  showError(message) {
    this.error.textContent = message;
    this.error.classList.remove("hidden");
    this.success.classList.add("hidden");
  }

  hideError() {
    this.error.classList.add("hidden");
  }

  hideFeedback() {
    this.hideError();
    this.success.classList.add("hidden");
  }
}

window.ActionPanel = ActionPanel;
