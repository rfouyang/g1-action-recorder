class PoseComposerPanel {
  constructor(root = document) {
    this.panel = root.querySelector("[data-pose-composer]");
    this.base = root.querySelector("#composer-base");
    this.leftArm = root.querySelector("#composer-left-arm");
    this.rightArm = root.querySelector("#composer-right-arm");
    this.name = root.querySelector("#composer-name");
    this.notes = root.querySelector("#composer-notes");
    this.overwrite = root.querySelector("#composer-overwrite");
    this.previewButton = root.querySelector("#preview-composition");
    this.saveButton = root.querySelector("#save-composition");
    this.saveLabel = root.querySelector("[data-composer-save-label]");
    this.saveLoading = root.querySelector("[data-composer-save-loading]");
    this.status = root.querySelector("#composer-status");
    this.success = root.querySelector("#composer-success");
    this.error = root.querySelector("#composer-error");
    this.defaultBase = this.panel?.dataset.defaultBase || "";
    this.request = 0;
  }

  start() {
    if (!this.panel) {
      return;
    }
    for (const select of [this.base, this.leftArm, this.rightArm]) {
      select.addEventListener("change", () => this.preview());
    }
    this.previewButton.addEventListener("click", () => this.preview());
    this.saveButton.addEventListener("click", () => this.save());
    document.addEventListener("g1:panel-activated", (event) => {
      if (event.detail.panelName === "pose-composer") {
        this.refreshSources();
      }
    });
  }

  async refreshSources() {
    const selected = {
      base: this.base.value,
      left_arm: this.leftArm.value,
      right_arm: this.rightArm.value,
    };
    try {
      const response = await fetch("/ui/g1-3d/poses", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Could not refresh poses (${response.status}).`);
      }
      const poses = await response.json();
      this.fillSelect(this.base, poses.base, {
        optional: false,
        selected: selected.base || this.defaultBase,
        emptyLabel: "No base poses saved",
      });
      this.fillSelect(this.leftArm, poses.left_arm, {
        optional: true,
        selected: selected.left_arm,
        emptyLabel: "Use arm from base",
      });
      this.fillSelect(this.rightArm, poses.right_arm, {
        optional: true,
        selected: selected.right_arm,
        emptyLabel: "Use arm from base",
      });
      if (this.base.value) {
        await this.preview();
      } else {
        this.showStatus("Save a base pose in Pose Recorder to begin composing.");
      }
    } catch (error) {
      this.showError(error.message);
    }
  }

  fillSelect(select, names, { optional, selected, emptyLabel }) {
    select.replaceChildren();
    if (optional || names.length === 0) {
      select.add(new Option(emptyLabel, ""));
    }
    for (const name of names) {
      select.add(new Option(name, name));
    }
    if ([...select.options].some((option) => option.value === selected)) {
      select.value = selected;
    }
  }

  async preview() {
    if (!this.base.value) {
      this.showError("Save or select a base pose before composing.");
      return;
    }
    const request = ++this.request;
    this.setBusy(this.previewButton, true, "Previewing");
    this.hideFeedback();
    try {
      const result = await this.send("/ui/g1-3d/pose-composer/preview", false);
      if (request !== this.request) {
        return;
      }
      this.showStatus(this.sourceSummary(result.source_parts));
    } catch (error) {
      if (request === this.request) {
        this.showError(error.message);
      }
    } finally {
      if (request === this.request) {
        this.setBusy(this.previewButton, false, "Preview composition");
      }
    }
  }

  async save() {
    if (!this.name.value.trim()) {
      this.showError("Enter a final pose name before saving.");
      return;
    }
    this.setSaving(true);
    this.hideFeedback();
    try {
      const result = await this.send("/ui/g1-3d/pose-composer/save", true);
      this.showSuccess(`Saved composed pose “${result.pose_name}”.`);
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setSaving(false);
    }
  }

  async send(url, save) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        base_pose: this.base.value,
        left_arm_pose: this.leftArm.value || null,
        right_arm_pose: this.rightArm.value || null,
        name: save ? this.name.value.trim() : "",
        notes: this.notes.value,
        overwrite: save && this.overwrite.checked,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || `Composition failed (${response.status}).`);
    }
    return result;
  }

  sourceSummary(sourceParts) {
    const parts = [`Base: ${sourceParts.base}`];
    if (sourceParts.left_arm) {
      parts.push(`robot-left: ${sourceParts.left_arm}`);
    }
    if (sourceParts.right_arm) {
      parts.push(`robot-right: ${sourceParts.right_arm}`);
    }
    return `Previewing ${parts.join(" · ")}.`;
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

  setBusy(button, busy, label) {
    button.disabled = busy;
    button.textContent = label;
    button.setAttribute("aria-busy", String(busy));
  }

  setSaving(saving) {
    this.saveButton.disabled = saving;
    this.saveButton.setAttribute("aria-busy", String(saving));
    this.saveLabel.textContent = saving ? "Saving" : "Compose and save";
    this.saveLoading.classList.toggle("hidden", !saving);
  }
}

window.PoseComposerPanel = PoseComposerPanel;
