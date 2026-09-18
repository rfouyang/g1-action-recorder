class SpeechPanel {
  constructor(root = document) {
    this.panel = root.querySelector("[data-speech-panel]");
    this.name = root.querySelector("#speech-name");
    this.text = root.querySelector("#speech-text");
    this.speaker = root.querySelector("#speech-speaker");
    this.tone = root.querySelector("#speech-tone");
    this.emotionStrength = root.querySelector("#speech-emotion-strength");
    this.emotionStrengthValue = root.querySelector("#speech-emotion-strength-value");
    this.speechRate = root.querySelector("#speech-rate");
    this.speechRateValue = root.querySelector("#speech-rate-value");
    this.loudness = root.querySelector("#speech-loudness");
    this.loudnessValue = root.querySelector("#speech-loudness-value");
    this.pitch = root.querySelector("#speech-pitch");
    this.pitchValue = root.querySelector("#speech-pitch-value");
    this.styleInstruction = root.querySelector("#speech-style-instruction");
    this.characterCount = root.querySelector("#speech-character-count");
    this.overwrite = root.querySelector("#speech-overwrite");
    this.generateButton = root.querySelector("#speech-generate");
    this.generateLabel = root.querySelector("[data-speech-generate-label]");
    this.generateLoading = root.querySelector("[data-speech-generate-loading]");
    this.refreshButton = root.querySelector("#speech-refresh");
    this.summary = root.querySelector("#speech-catalog-summary");
    this.clips = root.querySelector("#speech-clips");
    this.success = root.querySelector("#speech-success");
    this.error = root.querySelector("#speech-error");
    this.configured = this.panel?.dataset.ttsConfigured === "true";
  }

  start() {
    if (!this.panel) {
      return;
    }
    this.text.addEventListener("input", () => this.updateCharacterCount());
    for (const control of [
      this.emotionStrength,
      this.speechRate,
      this.loudness,
      this.pitch,
    ]) {
      control.addEventListener("input", () => this.updateDeliveryLabels());
    }
    this.generateButton.addEventListener("click", () => this.generate());
    this.refreshButton.addEventListener("click", () => this.refresh());
    document.addEventListener("g1:panel-activated", (event) => {
      if (event.detail.panelName === "speech") {
        this.refresh();
      }
    });
    this.updateCharacterCount();
    this.updateDeliveryLabels();
    this.refresh();
  }

  async generate() {
    const name = this.name.value.trim();
    const text = this.text.value.trim();
    if (!name) {
      this.showError("Enter a clip name before generating.");
      return;
    }
    if (!text) {
      this.showError("Enter text to speak before generating.");
      return;
    }

    this.setGenerating(true);
    this.hideFeedback();
    try {
      const response = await fetch("/ui/g1-3d/tts", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          text,
          speaker: this.speaker.value,
          tone: this.tone.value,
          emotion_strength: Number(this.emotionStrength.value),
          speech_rate: Number(this.speechRate.value),
          loudness_rate: Number(this.loudness.value),
          pitch: Number(this.pitch.value),
          style_instruction: this.styleInstruction.value.trim(),
          overwrite: this.overwrite.checked,
        }),
      });
      const clip = await this.responseJson(response, "Speech generation failed");
      this.showSuccess(
        `Generated “${clip.wav_filename}” · ${this.formatDuration(clip.duration_seconds)}.`,
      );
      await this.refresh(false);
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.setGenerating(false);
    }
  }

  async refresh(showErrors = true) {
    this.refreshButton.disabled = true;
    try {
      const response = await fetch("/ui/g1-3d/tts", {
        headers: { Accept: "application/json" },
      });
      const result = await this.responseJson(response, "Could not load speech clips");
      this.configured = result.configured;
      this.generateButton.disabled = !this.configured;
      this.renderClips(result.clips);
    } catch (error) {
      if (showErrors) {
        this.showError(error.message);
      }
    } finally {
      this.refreshButton.disabled = false;
    }
  }

  renderClips(clips) {
    this.clips.replaceChildren();
    this.summary.textContent = `${clips.length} clip${clips.length === 1 ? "" : "s"}`;
    if (clips.length === 0) {
      const empty = document.createElement("p");
      empty.className = "border border-dashed border-base-300 p-3 text-xs text-base-content/55";
      empty.textContent = "No speech clips saved yet.";
      this.clips.append(empty);
      return;
    }

    for (const clip of clips) {
      const item = document.createElement("article");
      item.className = "border border-base-300 bg-base-100 p-3";

      const header = document.createElement("div");
      header.className = "flex items-start justify-between gap-3";
      const identity = document.createElement("div");
      identity.className = "min-w-0";
      const name = document.createElement("h3");
      name.className = "truncate text-sm font-semibold";
      name.textContent = clip.name;
      name.title = clip.name;
      const filename = document.createElement("p");
      filename.className = "mt-0.5 truncate font-mono text-[0.65rem] text-base-content/50";
      filename.textContent = clip.wav_filename;
      identity.append(name, filename);
      const duration = document.createElement("span");
      duration.className = "badge badge-neutral badge-sm shrink-0 font-mono";
      duration.textContent = this.formatDuration(clip.duration_seconds);
      header.append(identity, duration);

      const spokenText = document.createElement("p");
      spokenText.className = "mt-2 whitespace-pre-wrap text-sm leading-5";
      spokenText.textContent = clip.text;

      const details = document.createElement("p");
      details.className = "mt-2 font-mono text-[0.65rem] text-base-content/50";
      details.textContent = `${clip.speaker_name} · ${clip.tone_name} ${clip.emotion_strength}/5 · rate ${this.formatSigned(clip.speech_rate)} · volume ${this.formatSigned(clip.loudness_rate)} · pitch ${this.formatSigned(clip.pitch)} · ${clip.sample_rate_hz} Hz · mono · 16-bit · ${this.formatDate(clip.created_at)}`;

      const styleInstruction = document.createElement("p");
      styleInstruction.className = "mt-1 text-xs text-base-content/60";
      styleInstruction.textContent = clip.style_instruction
        ? `Delivery: ${clip.style_instruction}`
        : "";

      const audio = document.createElement("audio");
      audio.className = "mt-3 w-full";
      audio.controls = true;
      audio.preload = "metadata";
      audio.src = clip.audio_url;

      const actions = document.createElement("div");
      actions.className = "mt-2 flex items-center gap-2";

      const download = document.createElement("a");
      download.className = "btn btn-ghost btn-xs";
      download.href = clip.audio_url;
      download.download = clip.wav_filename;
      download.textContent = "Download WAV";

      const deleteButton = document.createElement("button");
      deleteButton.className = "btn btn-error btn-outline btn-xs";
      deleteButton.type = "button";
      deleteButton.textContent = "Delete";
      deleteButton.addEventListener("click", () =>
        this.deleteClip(clip, deleteButton),
      );
      actions.append(download, deleteButton);

      item.append(header, spokenText, details);
      if (clip.style_instruction) {
        item.append(styleInstruction);
      }
      item.append(audio, actions);
      this.clips.append(item);
    }
  }

  async deleteClip(clip, button) {
    if (!window.confirm(`Delete “${clip.name}” and its WAV file?`)) {
      return;
    }

    button.disabled = true;
    this.hideFeedback();
    try {
      const response = await fetch(
        `/ui/g1-3d/tts/${encodeURIComponent(clip.name)}`,
        { method: "DELETE", headers: { Accept: "application/json" } },
      );
      await this.responseJson(response, "Could not delete speech clip");
      this.showSuccess(`Deleted “${clip.name}”.`);
      await this.refresh(false);
    } catch (error) {
      button.disabled = false;
      this.showError(error.message);
    }
  }

  updateCharacterCount() {
    this.characterCount.textContent = `${this.text.value.length} / 5000`;
  }

  updateDeliveryLabels() {
    this.emotionStrengthValue.textContent = `${this.emotionStrength.value} / 5`;
    this.speechRateValue.textContent = this.formatSigned(this.speechRate.value);
    this.loudnessValue.textContent = this.formatSigned(this.loudness.value);
    this.pitchValue.textContent = this.formatSigned(this.pitch.value);
  }

  formatSigned(value) {
    const number = Number(value);
    return number > 0 ? `+${number}` : String(number);
  }

  setGenerating(generating) {
    this.generateButton.disabled = generating || !this.configured;
    this.generateButton.setAttribute("aria-busy", String(generating));
    this.generateLabel.textContent = generating ? "Generating" : "Generate WAV";
    this.generateLoading.classList.toggle("hidden", !generating);
  }

  async responseJson(response, fallback) {
    const responseText = await response.text();
    let result = {};
    if (responseText) {
      try {
        result = JSON.parse(responseText);
      } catch (_error) {
        if (!response.ok) {
          throw new Error(`${fallback} with ${response.status}: ${responseText}`);
        }
        throw new Error(`${fallback}: the server returned an invalid response.`);
      }
    }
    if (!response.ok) {
      throw new Error(result.detail || `${fallback} with ${response.status}`);
    }
    return result;
  }

  formatDuration(value) {
    return `${Number(value).toFixed(3)} s`;
  }

  formatDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  showError(detail) {
    this.success.classList.add("hidden");
    this.error.textContent = detail;
    this.error.classList.remove("hidden");
  }

  showSuccess(detail) {
    this.error.classList.add("hidden");
    this.success.textContent = detail;
    this.success.classList.remove("hidden");
  }

  hideFeedback() {
    this.error.classList.add("hidden");
    this.success.classList.add("hidden");
  }
}

window.SpeechPanel = SpeechPanel;
