class WorkspaceTabs {
  constructor(root = document) {
    this.tabs = [...root.querySelectorAll("[data-panel-target]")];
    this.panels = [...root.querySelectorAll("[data-panel]")];
  }

  start() {
    for (const tab of this.tabs) {
      tab.addEventListener("click", () => this.activate(tab.dataset.panelTarget));
    }

    const requestedPanel = window.location.hash.replace("#", "");
    if (this.panels.some((panel) => panel.dataset.panel === requestedPanel)) {
      this.activate(requestedPanel, false);
    }
  }

  activate(panelName, updateLocation = true) {
    for (const tab of this.tabs) {
      const active = tab.dataset.panelTarget === panelName;
      tab.classList.toggle("tab-active", active);
      tab.setAttribute("aria-selected", String(active));
    }

    for (const panel of this.panels) {
      panel.classList.toggle("hidden", panel.dataset.panel !== panelName);
    }

    if (updateLocation) {
      window.history.replaceState(null, "", `#${panelName}`);
    }
    document.dispatchEvent(
      new CustomEvent("g1:panel-activated", { detail: { panelName } }),
    );
  }
}

class ViserViewer {
  constructor(root = document) {
    this.frame = root.querySelector("#viser-frame");
    this.status = root.querySelector("#viser-status");
    this.statusLabel = root.querySelector("#viser-status-label");
    this.cameraButtons = [...root.querySelectorAll("[data-camera-view]")];
    this.transitionTimer = null;
    this.cameraRequest = 0;
  }

  start() {
    if (!this.frame) {
      return;
    }
    const port = this.frame.dataset.viserPort;
    this.frame.src = `${window.location.protocol}//${window.location.hostname}:${port}/`;
    this.frame.addEventListener("load", () => this.setConnectionState("ready"));
    this.frame.addEventListener("error", () => this.setConnectionState("error"));

    for (const button of this.cameraButtons) {
      button.addEventListener("click", () => this.selectCamera(button));
    }
  }

  async selectCamera(button) {
    const cameraView = button.dataset.cameraView;
    const request = ++this.cameraRequest;
    window.clearTimeout(this.transitionTimer);
    this.setConnectionState("pending");
    try {
      const response = await fetch(`/ui/g1-3d/viewer/camera/${cameraView}`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Camera request failed with ${response.status}`);
      }
      const result = await response.json();
      if (request !== this.cameraRequest) {
        return;
      }
      if (result.connected_clients < 1) {
        this.setConnectionState("waiting");
        return;
      }
      for (const candidate of this.cameraButtons) {
        const active = candidate === button;
        candidate.classList.toggle("btn-active", active);
        candidate.classList.toggle("btn-ghost", !active);
        candidate.classList.toggle("bg-neutral-content", active);
        candidate.classList.toggle("text-neutral", active);
        candidate.classList.toggle("text-neutral-content/70", !active);
        candidate.setAttribute("aria-pressed", String(active));
      }
      this.transitionTimer = window.setTimeout(
        () => this.setConnectionState("ready"),
        Number(result.transition_seconds || 0) * 1000,
      );
    } catch (error) {
      console.error(error);
      this.setConnectionState("error");
    }
  }

  setConnectionState(state) {
    const states = {
      ready: ["status-success", "Live 3D scene"],
      pending: ["status-info", "Changing camera"],
      waiting: ["status-warning", "Waiting for viewer"],
      error: ["status-error", "3D scene unavailable"],
    };
    const [statusClass, label] = states[state];
    this.status.classList.remove(
      "status-success",
      "status-info",
      "status-warning",
      "status-error",
    );
    this.status.classList.add(statusClass);
    this.statusLabel.textContent = label;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  new WorkspaceTabs().start();
  new window.PoseRecorderPanel().start();
  new window.PoseComposerPanel().start();
  new window.ActionPanel().start();
  new ViserViewer().start();
});
