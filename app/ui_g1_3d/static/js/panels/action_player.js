class ActionPlayerPanel {
  constructor(root = document) {
    this.panel = root.querySelector("[data-action-player-panel]");
    this.format = root.querySelector("#action-player-format");
    this.file = root.querySelector("#action-player-file");
    this.fileHelp = root.querySelector("#action-player-file-help");
    this.name = root.querySelector("#action-player-name");
    this.fps = root.querySelector("#action-player-fps");
    this.trust = root.querySelector("#action-player-trust");
    this.loadButton = root.querySelector("#action-player-load");
    this.summary = root.querySelector("#action-player-summary");
    this.summaryName = root.querySelector("#action-player-summary-name");
    this.summaryFormat = root.querySelector("#action-player-summary-format");
    this.summaryFile = root.querySelector("#action-player-summary-file");
    this.summarySourceJoints = root.querySelector("#action-player-summary-source-joints");
    this.summaryArmJoints = root.querySelector("#action-player-summary-arm-joints");
    this.summarySamples = root.querySelector("#action-player-summary-samples");
    this.summaryFps = root.querySelector("#action-player-summary-fps");
    this.summaryDuration = root.querySelector("#action-player-summary-duration");
    this.warnings = root.querySelector("#action-player-warnings");
    this.playButton = root.querySelector("#action-player-play");
    this.pauseButton = root.querySelector("#action-player-pause");
    this.stopButton = root.querySelector("#action-player-stop");
    this.loop = root.querySelector("#action-player-loop");
    this.state = root.querySelector("#action-player-state");
    this.time = root.querySelector("#action-player-time");
    this.progress = root.querySelector("#action-player-progress");
    this.phase = root.querySelector("#action-player-phase");
    this.sample = root.querySelector("#action-player-sample");
    this.frame = root.querySelector("#action-player-frame");
    this.framePrevious = root.querySelector("#action-player-frame-previous");
    this.frameNext = root.querySelector("#action-player-frame-next");
    this.framePosition = root.querySelector("#action-player-frame-position");
    this.frameTime = root.querySelector("#action-player-frame-time");
    this.captureState = root.querySelector("#action-player-capture-state");
    this.poseName = root.querySelector("#action-player-pose-name");
    this.poseNotes = root.querySelector("#action-player-pose-notes");
    this.poseOverwrite = root.querySelector("#action-player-pose-overwrite");
    this.saveLeftButton = root.querySelector("#action-player-save-left");
    this.saveRightButton = root.querySelector("#action-player-save-right");
    this.status = root.querySelector("#action-player-status");
    this.success = root.querySelector("#action-player-success");
    this.error = root.querySelector("#action-player-error");
    this.loaded = false;
    this.playbackState = "idle";
    this.uploadedActionSelected = false;
    this.playbackSocket = null;
    this.reconnectTimer = null;
    this.sampleIndex = 0;
    this.sampleCount = 0;
    this.seekRequest = 0;
    this.seekTimer = null;
    this.seekBusy = false;
    this.captureBusy = false;
  }

  start() {
    if (!this.panel) {
      return;
    }
    this.format.addEventListener("change", () => this.updateFormat());
    this.loadButton.addEventListener("click", () => this.load());
    this.playButton.addEventListener("click", () => this.play());
    this.pauseButton.addEventListener("click", () => this.togglePause());
    this.stopButton.addEventListener("click", () => this.stop());
    this.loop.addEventListener("change", () => this.setLoop());
    this.frame.addEventListener("input", () => this.queueSeek());
    this.framePrevious.addEventListener("click", () => this.seekFrame(this.sampleIndex - 1));
    this.frameNext.addEventListener("click", () => this.seekFrame(this.sampleIndex + 1));
    this.poseName.addEventListener("input", () => this.updateCaptureControls());
    this.saveLeftButton.addEventListener("click", () => this.savePose("left_arm"));
    this.saveRightButton.addEventListener("click", () => this.savePose("right_arm"));
    this.updateFormat();
    this.connectPlaybackSocket();
  }

  updateFormat() {
    const formats = {
      native_npz: {
        accept: ".npz",
        help: "Choose a compiled Action Recorder NPZ.",
        needsFps: false,
        trusted: false,
      },
      kimodo_npz: {
        accept: ".npz",
        help: "Choose a Kimodo G1-34 motion NPZ.",
        needsFps: true,
        trusted: false,
      },
      ardy_pkl: {
        accept: ".pkl",
        help: "Choose an ARDY interactive-session PKL.",
        needsFps: false,
        trusted: true,
      },
    };
    const selected = formats[this.format.value];
    this.file.accept = selected.accept;
    this.file.value = "";
    this.fileHelp.textContent = selected.help;
    this.fps.disabled = !selected.needsFps;
    this.trust.classList.toggle("hidden", !selected.trusted);
    this.hideFeedback();
  }

  async load() {
    if (this.playbackState === "playing" || this.playbackState === "paused") {
      this.showError("Stop the current action before loading another file.");
      return;
    }
    const selectedFile = this.file.files[0];
    if (!selectedFile) {
      this.showError("Choose an action file first.");
      return;
    }
    const parameters = new URLSearchParams({
      source_format: this.format.value,
      filename: selectedFile.name,
    });
    if (this.name.value.trim()) {
      parameters.set("action_name", this.name.value.trim());
    }
    if (this.format.value === "kimodo_npz") {
      const sourceFps = Number(this.fps.value);
      if (!Number.isFinite(sourceFps) || sourceFps <= 0 || sourceFps > 240) {
        this.showError("Kimodo source frequency must be within 1–240 Hz.");
        return;
      }
      parameters.set("source_fps", String(sourceFps));
    }

    this.setLoading(true);
    this.hideFeedback();
    try {
      const response = await fetch(`/ui/g1-3d/action-player/load?${parameters}`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/octet-stream" },
        body: selectedFile,
      });
      const result = await this.responseJson(response, "Could not load action file");
      this.loaded = true;
      this.uploadedActionSelected = false;
      this.sampleCount = result.sample_count;
      this.frame.max = String(Math.max(0, result.sample_count - 1));
      this.renderSummary(result);
      this.updatePlaybackControls();
      this.showSuccess(
        `Loaded “${result.action_name}” for arm-only playback in the Viser scene.`,
      );
    } catch (error) {
      this.loaded = false;
      this.updatePlaybackControls();
      this.showError(error.message);
    } finally {
      this.setLoading(false);
    }
  }

  renderSummary(result) {
    const formatLabels = {
      native_npz: "Recorder NPZ",
      kimodo_npz: "Kimodo NPZ",
      ardy_pkl: "ARDY PKL",
    };
    this.summaryName.textContent = result.action_name;
    this.summaryName.title = result.action_name;
    this.summaryFormat.textContent = formatLabels[result.source_format] || result.source_format;
    this.summaryFile.textContent = result.source_filename;
    this.summaryFile.title = result.source_filename;
    this.summarySourceJoints.textContent = String(result.source_joint_count);
    this.summaryArmJoints.textContent = `${result.arm_joint_count} · both arms`;
    this.summarySamples.textContent = String(result.sample_count);
    this.summaryFps.textContent = `${this.formatNumber(result.sample_frequency_hz)} Hz`;
    this.summaryDuration.textContent = `${this.formatNumber(result.duration_seconds)} s`;
    this.warnings.replaceChildren();
    for (const warning of result.warnings) {
      const item = document.createElement("li");
      item.textContent = warning;
      this.warnings.append(item);
    }
    this.summary.classList.remove("hidden");
  }

  async play() {
    await this.sendPlaybackCommand("play", { enabled: this.loop.checked });
  }

  async togglePause() {
    const command = this.playbackState === "paused" ? "resume" : "pause";
    await this.sendPlaybackCommand(command);
  }

  async stop() {
    await this.sendPlaybackCommand("stop");
  }

  async setLoop() {
    if (!this.uploadedActionSelected) {
      return;
    }
    await this.sendPlaybackCommand("loop", { enabled: this.loop.checked });
  }

  queueSeek() {
    const sampleIndex = Number(this.frame.value);
    this.framePosition.textContent = `Selecting sample ${sampleIndex + 1} / ${this.sampleCount}`;
    window.clearTimeout(this.seekTimer);
    this.seekTimer = window.setTimeout(() => this.seekFrame(sampleIndex), 60);
  }

  async seekFrame(sampleIndex) {
    if (this.playbackState !== "paused") {
      this.showError("Pause action playback before selecting a frame.");
      return;
    }
    const boundedIndex = Math.min(
      Math.max(0, Number(sampleIndex)),
      Math.max(0, this.sampleCount - 1),
    );
    const request = ++this.seekRequest;
    this.seekBusy = true;
    this.updateCaptureControls();
    try {
      const response = await fetch("/ui/g1-3d/action-player/playback/seek", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ sample_index: boundedIndex }),
      });
      const result = await this.responseJson(response, "Could not select frame");
      if (request === this.seekRequest) {
        this.updatePlayback(result);
      }
    } catch (error) {
      if (request === this.seekRequest) {
        this.showError(error.message);
      }
    } finally {
      if (request === this.seekRequest) {
        this.seekBusy = false;
        this.updateCaptureControls();
      }
    }
  }

  async savePose(poseType) {
    const name = this.poseName.value.trim();
    if (!name) {
      this.showError("Enter a pose name before saving the selected arm.");
      return;
    }
    this.setCaptureBusy(true);
    this.hideFeedback();
    try {
      const response = await fetch("/ui/g1-3d/action-player/poses", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          pose_type: poseType,
          name,
          notes: this.poseNotes.value,
          overwrite: this.poseOverwrite.checked,
        }),
      });
      const result = await this.responseJson(response, "Could not save selected arm pose");
      const armLabel = result.pose_type === "left_arm" ? "robot-left" : "robot-right";
      this.showSuccess(
        `Saved ${armLabel} pose “${result.pose_name}” from sample ${result.sample_index + 1}/${result.sample_count} at ${this.fixedMilliseconds(result.timestamp_seconds)} s.`,
      );
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setCaptureBusy(false);
    }
  }

  async sendPlaybackCommand(command, body = null) {
    this.hideFeedback();
    try {
      const response = await fetch(`/ui/g1-3d/action-player/playback/${command}`, {
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

  connectPlaybackSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.playbackSocket = new WebSocket(
      `${protocol}//${window.location.host}/ui/g1-3d/action-player/playback/ws`,
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
    this.playbackSocket.addEventListener("close", () => {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = window.setTimeout(() => this.connectPlaybackSocket(), 1000);
    });
  }

  updatePlayback(playback) {
    this.playbackState = playback.state;
    if (Object.hasOwn(playback, "source")) {
      this.uploadedActionSelected = playback.source === "uploaded";
    }
    this.sampleIndex = Number(playback.sample_index || 0);
    this.sampleCount = Number(playback.sample_count || this.sampleCount || 0);
    this.loop.checked = playback.loop;
    this.progress.value = Number(playback.progress || 0) * 100;
    this.time.textContent = `${this.fixedSeconds(playback.elapsed_seconds)} / ${this.fixedSeconds(playback.duration_seconds)} s`;
    this.sample.textContent = playback.sample_count > 0
      ? `Sample ${playback.sample_index + 1} / ${playback.sample_count}`
      : "No action loaded";
    this.frame.max = String(Math.max(0, this.sampleCount - 1));
    this.frame.value = String(this.sampleIndex);
    this.framePosition.textContent = this.sampleCount > 0
      ? `Sample ${this.sampleIndex + 1} / ${this.sampleCount}`
      : "Sample 0 / 0";
    this.frameTime.textContent = `${this.fixedMilliseconds(playback.elapsed_seconds)} s`;
    const statePresentation = {
      idle: ["Idle", "ghost"],
      playing: ["Playing", "success"],
      paused: ["Paused", "warning"],
      stopped: ["Stopped", "ghost"],
      completed: ["Completed", "info"],
      failed: ["Failed", "error"],
    };
    const phasePresentation = {
      none: ["Waiting", "ghost"],
      keyframe: ["Keyframe", "success"],
      transition: ["Moving", "info"],
      hold: ["Holding", "warning"],
    };
    this.setBadge(this.state, statePresentation[playback.state] || [playback.state, "ghost"]);
    this.setBadge(this.phase, phasePresentation[playback.phase] || ["Waiting", "ghost"]);
    this.updatePlaybackControls();
    if (playback.error) {
      this.showError(`Playback failed: ${playback.error}`);
    }
  }

  setBadge(element, [label, color]) {
    element.textContent = label;
    element.classList.remove(
      "badge-ghost", "badge-success", "badge-warning", "badge-info", "badge-error",
    );
    element.classList.add(`badge-${color}`);
  }

  updatePlaybackControls() {
    const active = this.playbackState === "playing" || this.playbackState === "paused";
    const ownedActive = this.uploadedActionSelected && active;
    this.playButton.disabled = !this.loaded || active;
    this.pauseButton.disabled = !ownedActive;
    this.pauseButton.textContent = this.playbackState === "paused" ? "Resume" : "Pause";
    this.stopButton.disabled = !this.uploadedActionSelected || (
      !active && this.playbackState !== "completed"
    );
    this.updateCaptureControls();
  }

  updateCaptureControls() {
    const paused = this.loaded && this.uploadedActionSelected && this.playbackState === "paused";
    this.frame.disabled = !paused || this.captureBusy || this.seekBusy;
    this.framePrevious.disabled = (
      !paused || this.captureBusy || this.seekBusy || this.sampleIndex <= 0
    );
    this.frameNext.disabled = (
      !paused || this.captureBusy || this.seekBusy || this.sampleIndex >= this.sampleCount - 1
    );
    const canSave = (
      paused && !this.captureBusy && !this.seekBusy && Boolean(this.poseName.value.trim())
    );
    this.saveLeftButton.disabled = !canSave;
    this.saveRightButton.disabled = !canSave;
    let presentation = paused ? ["Ready", "success"] : ["Pause to select", "ghost"];
    if (this.seekBusy) {
      presentation = ["Selecting", "info"];
    } else if (this.captureBusy) {
      presentation = ["Saving", "info"];
    }
    this.setBadge(this.captureState, presentation);
  }

  setCaptureBusy(busy) {
    this.captureBusy = busy;
    this.saveLeftButton.textContent = busy ? "Saving" : "Save left arm";
    this.saveRightButton.textContent = busy ? "Saving" : "Save right arm";
    this.updateCaptureControls();
  }

  setLoading(loading) {
    this.loadButton.disabled = loading;
    this.loadButton.querySelector("[data-action-player-load-label]").textContent = loading
      ? "Validating"
      : "Load action";
    this.loadButton.querySelector("[data-action-player-load-spinner]").classList.toggle(
      "hidden",
      !loading,
    );
  }

  async responseJson(response, fallback) {
    let result;
    try {
      result = await response.json();
    } catch (_error) {
      throw new Error(`${fallback} (${response.status}).`);
    }
    if (!response.ok) {
      throw new Error(result.detail || `${fallback} (${response.status}).`);
    }
    return result;
  }

  hideFeedback() {
    this.status.classList.add("hidden");
    this.success.classList.add("hidden");
    this.error.classList.add("hidden");
  }

  showSuccess(message) {
    this.hideFeedback();
    this.success.textContent = message;
    this.success.classList.remove("hidden");
  }

  showError(message) {
    this.hideFeedback();
    this.error.textContent = message;
    this.error.classList.remove("hidden");
  }

  formatNumber(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
  }

  fixedSeconds(value) {
    return Number(value || 0).toFixed(2);
  }

  fixedMilliseconds(value) {
    return Number(value || 0).toFixed(3);
  }
}

window.ActionPlayerPanel = ActionPlayerPanel;
