class PoseRecorderPanel {
  constructor(root = document) {
    this.panel = root.querySelector("[data-pose-recorder]");
    this.groupSelect = root.querySelector("#pose-group");
    this.rows = [...root.querySelectorAll("[data-joint-row]")];
    this.sliders = [...root.querySelectorAll("[data-joint-target]")];
    this.numberInputs = [...root.querySelectorAll("[data-joint-target-number]")];
    this.resetButtons = [...root.querySelectorAll("[data-joint-reset]")];
    this.actualValues = new Map(
      [...root.querySelectorAll("[data-joint-actual]")].map((element) => [
        element.dataset.jointActual,
        element,
      ]),
    );
    this.status = root.querySelector("#simulation-status");
    this.statusLabel = root.querySelector("#simulation-status-label");
    this.visibleCount = root.querySelector("#visible-joint-count");
    this.error = root.querySelector("#simulation-error");
    this.success = root.querySelector("#simulation-success");
    this.resetButton = root.querySelector("#reset-pose");
    this.saveButton = root.querySelector("#save-pose");
    this.saveLabel = root.querySelector("[data-save-label]");
    this.saveLoading = root.querySelector("[data-save-loading]");
    this.poseName = root.querySelector("#pose-name");
    this.poseNotes = root.querySelector("#pose-notes");
    this.poseOverwrite = root.querySelector("#pose-overwrite");
    this.initialTargets = new Map(
      this.resetButtons.map((button) => [
        button.dataset.jointName,
        Number(button.dataset.resetValue),
      ]),
    );
    this.socket = null;
  }

  start() {
    if (!this.panel || !window.G1SimulationSocket) {
      return;
    }
    this.socket = new window.G1SimulationSocket({
      onState: (message) => this.applyState(message),
      onStatus: (state) => this.setConnectionState(state),
      onError: (detail) => this.showError(detail),
    });

    this.groupSelect.addEventListener("change", () => this.filterRows());
    for (const slider of this.sliders) {
      slider.addEventListener("input", () => this.changeTarget(slider));
    }
    for (const input of this.numberInputs) {
      input.addEventListener("change", () => this.changeTarget(input));
    }
    for (const button of this.resetButtons) {
      button.addEventListener("click", () => this.resetJoint(button));
    }
    this.resetButton.addEventListener("click", () => this.resetTargets());
    this.saveButton.addEventListener("click", () => this.savePose());
    this.filterRows();
    this.socket.start();
  }

  filterRows() {
    const group = this.groupSelect.value;
    let visible = 0;
    for (const row of this.rows) {
      const show = group === "base" || row.dataset.jointGroup === group;
      row.classList.toggle("hidden", !show);
      visible += Number(show);
    }
    this.visibleCount.textContent = `${visible} joints`;
  }

  changeTarget(input) {
    const jointName = input.dataset.jointName;
    const value = this.clampToInput(input, Number(input.value));
    if (!Number.isFinite(value)) {
      this.showError("Joint target must be a finite number.");
      return;
    }
    this.setTargetInputs(jointName, value);
    this.hideError();
    this.hideSuccess();
    this.socket.setJointTarget(jointName, value);
  }

  resetJoint(button) {
    const jointName = button.dataset.jointName;
    const value = Number(button.dataset.resetValue);
    this.setTargetInputs(jointName, value);
    this.hideFeedback();
    this.socket.setJointTarget(jointName, value);
  }

  resetTargets() {
    const group = this.groupSelect.value;
    for (const [jointName, value] of this.initialTargets) {
      const row = this.rows.find(
        (candidate) => candidate.querySelector(`[data-joint-name="${jointName}"]`),
      );
      if (group !== "base" && row.dataset.jointGroup !== group) {
        continue;
      }
      this.setTargetInputs(jointName, value);
      this.socket.setJointTarget(jointName, value);
    }
    this.hideFeedback();
  }

  async savePose() {
    const name = this.poseName.value.trim();
    if (!name) {
      this.showError("Enter a pose name before saving.");
      return;
    }

    const poseType = this.groupSelect.value;
    const jointPositions = {};
    for (const slider of this.sliders) {
      const row = slider.closest("[data-joint-row]");
      if (poseType === "base" || row.dataset.jointGroup === poseType) {
        jointPositions[slider.dataset.jointName] = Number(slider.value);
      }
    }

    this.setSaving(true);
    this.hideFeedback();
    try {
      const response = await fetch("/ui/g1-3d/poses", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          pose_type: poseType,
          name,
          notes: this.poseNotes.value,
          joint_positions: jointPositions,
          overwrite: this.poseOverwrite.checked,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || `Save failed with ${response.status}`);
      }
      this.showSuccess(
        `Saved ${this.poseTypeLabel(result.pose_type)} pose “${result.pose_name}”.`,
      );
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setSaving(false);
    }
  }

  applyState(message) {
    for (const [jointName, rawValue] of Object.entries(message.joint_positions)) {
      const actual = this.actualValues.get(jointName);
      if (actual) {
        actual.textContent = Number(rawValue).toFixed(3);
      }
    }
  }

  setTargetInputs(jointName, value) {
    const slider = this.sliders.find(
      (candidate) => candidate.dataset.jointName === jointName,
    );
    const numberInput = this.numberInputs.find(
      (candidate) => candidate.dataset.jointName === jointName,
    );
    slider.value = String(value);
    numberInput.value = value.toFixed(3);
  }

  clampToInput(input, value) {
    if (!Number.isFinite(value)) {
      return value;
    }
    return Math.min(Number(input.max), Math.max(Number(input.min), value));
  }

  setConnectionState(state) {
    const states = {
      ready: ["status-success", "MuJoCo live"],
      connecting: ["status-warning", "Connecting"],
      waiting: ["status-warning", "Reconnecting"],
      error: ["status-error", "Connection error"],
    };
    const [statusClass, label] = states[state];
    this.status.classList.remove(
      "status-success",
      "status-warning",
      "status-error",
    );
    this.status.classList.add(statusClass);
    this.statusLabel.textContent = label;
  }

  showError(detail) {
    this.hideSuccess();
    this.error.textContent = detail;
    this.error.classList.remove("hidden");
  }

  hideError() {
    this.error.classList.add("hidden");
  }

  showSuccess(detail) {
    this.hideError();
    this.success.textContent = detail;
    this.success.classList.remove("hidden");
  }

  hideSuccess() {
    this.success.classList.add("hidden");
  }

  hideFeedback() {
    this.hideError();
    this.hideSuccess();
  }

  setSaving(saving) {
    this.saveButton.disabled = saving;
    this.saveButton.setAttribute("aria-busy", String(saving));
    this.saveLabel.textContent = saving ? "Saving" : "Save pose";
    this.saveLoading.classList.toggle("hidden", !saving);
  }

  poseTypeLabel(poseType) {
    const labels = {
      base: "base",
      left_arm: "robot-left arm",
      right_arm: "robot-right arm",
    };
    return labels[poseType] || poseType;
  }
}

window.PoseRecorderPanel = PoseRecorderPanel;
