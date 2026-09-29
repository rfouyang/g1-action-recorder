/* The live link to the robot state, the Viser view with its camera buttons, and the shared playback bar. */

class RobotLink {
  // One WebSocket: it brings robot and playback updates in and takes slider moves out.
  constructor() {
    this.socket = null;
    this.listeners = { robot: [], playback: [], error: [] };
    this.pending = {};
    this.flushTimer = null;
    this.status = document.getElementById("link-status");
  }

  start() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${location.host}/api/robot/ws`);
    this.socket.addEventListener("open", () => this.setStatus(true));
    this.socket.addEventListener("close", () => {
      this.setStatus(false);
      setTimeout(() => this.start(), 1000);
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      for (const listener of this.listeners[message.type] || []) listener(message);
    });
  }

  on(type, listener) {
    this.listeners[type].push(listener);
  }

  sendJoints(jointPositions) {
    // Slider drags fire fast; send at most every 40 ms, latest values winning.
    Object.assign(this.pending, jointPositions);
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      if (this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ joint_positions: this.pending }));
        this.pending = {};
      }
    }, 40);
  }

  setStatus(live) {
    this.status.querySelector("[data-dot]").className = `size-2 rounded-full ${live ? "bg-green-500" : "bg-amber-500"}`;
    this.status.querySelector("[data-text]").textContent = live ? "Connected" : "Reconnecting";
  }
}

class Viewer {
  constructor() {
    this.frame = document.getElementById("viewer");
    this.buttons = [...document.querySelectorAll("[data-view]")];
  }

  start() {
    this.frame.src = this.resolveViserUrl();
    for (const button of this.buttons) {
      button.addEventListener("click", () => this.setView(button));
    }
  }

  resolveViserUrl() {
    // VISER_PUBLIC_URL when the iframe must hit a dedicated Ingress host, not hostname:port.
    const configured = (this.frame.dataset.viserUrl || "").trim();
    if (configured) {
      return configured.endsWith("/") ? configured : `${configured}/`;
    }
    return `${location.protocol}//${location.hostname}:${this.frame.dataset.port}/`;
  }

  async setView(button) {
    await run(null, () => api("POST", `/api/robot/camera/${button.dataset.view}`));
    for (const candidate of this.buttons) candidate.dataset.active = String(candidate === button);
  }
}

class PlayerBar {
  constructor() {
    const root = document.getElementById("player");
    this.find = (selector) => root.querySelector(selector);
    this.playButton = this.find("[data-play]");
    this.stopButton = this.find("[data-stop]");
    this.stepButtons = [...root.querySelectorAll("[data-step]")];
    this.scrub = this.find("[data-scrub]");
    this.loop = this.find("[data-loop]");
    this.snapshot = { state: "empty", index: 0, count: 0 };
    this.dragging = false;
    this.seekTimer = null;
  }

  start() {
    robotLink.on("playback", (snapshot) => this.show(snapshot));
    this.playButton.addEventListener("click", () => {
      const command = this.snapshot.state === "playing" ? "pause" : "play";
      run(this.playButton, () => api("POST", `/api/playback/${command}`, {}));
    });
    this.stopButton.addEventListener("click", () => run(this.stopButton, () => api("POST", "/api/playback/stop")));
    for (const button of this.stepButtons) {
      button.addEventListener("click", () => this.seek(this.snapshot.index + Number(button.dataset.step)));
    }
    this.scrub.addEventListener("pointerdown", () => { this.dragging = true; });
    this.scrub.addEventListener("pointerup", () => { this.dragging = false; });
    this.scrub.addEventListener("input", () => {
      // Dragging pauses and shows each frame; requests are spaced so a fast drag doesn't queue up.
      clearTimeout(this.seekTimer);
      this.seekTimer = setTimeout(() => this.seek(Number(this.scrub.value)), 30);
    });
    this.loop.addEventListener("change", () => run(null, () => api("POST", "/api/playback/loop", { enabled: this.loop.checked })));
  }

  seek(index) {
    run(null, () => api("POST", "/api/playback/seek", { index }));
  }

  show(snapshot) {
    this.snapshot = snapshot;
    const loaded = snapshot.state !== "empty";
    const playing = snapshot.state === "playing";
    for (const control of [this.playButton, this.stopButton, this.scrub, ...this.stepButtons]) control.disabled = !loaded;
    this.find("[data-play-icon]").classList.toggle("hidden", playing);
    this.find("[data-pause-icon]").classList.toggle("hidden", !playing);
    this.playButton.setAttribute("aria-label", playing ? "Pause" : "Play");
    this.scrub.max = String(Math.max(0, snapshot.count - 1));
    if (!this.dragging) this.scrub.value = String(snapshot.index);
    this.loop.checked = snapshot.loop;
    this.find("[data-time]").textContent = `${snapshot.time.toFixed(2)} / ${snapshot.duration.toFixed(2)} s`;
    const states = {
      empty: ["No action", "bg-gray-100 text-gray-600"],
      ready: ["Ready", "bg-gray-100 text-gray-700"],
      playing: ["Playing", "bg-blue-100 text-blue-800"],
      paused: ["Paused", "bg-amber-100 text-amber-800"],
      done: ["Done", "bg-green-100 text-green-800"],
    };
    const [label, color] = states[snapshot.state];
    const badge = this.find("[data-state]");
    badge.textContent = label;
    badge.className = `inline-flex shrink-0 items-center whitespace-nowrap rounded-md px-1.5 py-0.5 font-medium ${color}`;
    this.find("[data-name]").textContent = loaded ? `${snapshot.name} · ${snapshot.source}` : "";
    this.find("[data-phase]").textContent = loaded ? snapshot.phase : "Preview, play or import an action to see it here.";
    this.find("[data-frame]").textContent = loaded ? `frame ${snapshot.index + 1} / ${snapshot.count}` : "";
    document.dispatchEvent(new CustomEvent("recorder:playback", { detail: snapshot }));
  }
}

let robotLink;

document.addEventListener("DOMContentLoaded", () => {
  robotLink = new RobotLink();
  new Viewer().start();
  new PlayerBar().start();
  robotLink.on("error", (message) => toast(message.detail, "error"));
  robotLink.start();
});
