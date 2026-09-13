class G1SimulationSocket {
  constructor({ onState, onStatus, onError }) {
    this.onState = onState;
    this.onStatus = onStatus;
    this.onError = onError;
    this.socket = null;
    this.pendingTargets = new Map();
    this.flushTimer = null;
    this.reconnectTimer = null;
  }

  start() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(
      `${protocol}//${window.location.host}/ui/g1-3d/simulation/ws`,
    );
    this.onStatus("connecting");
    this.socket.addEventListener("open", () => {
      this.onStatus("ready");
      this.flush();
    });
    this.socket.addEventListener("message", (event) => this.receive(event));
    this.socket.addEventListener("error", () => this.onStatus("error"));
    this.socket.addEventListener("close", () => {
      this.onStatus("waiting");
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = window.setTimeout(() => this.start(), 1000);
    });
  }

  setJointTarget(jointName, value) {
    this.pendingTargets.set(jointName, value);
    if (this.flushTimer === null) {
      this.flushTimer = window.setTimeout(() => this.flush(), 40);
    }
  }

  flush() {
    window.clearTimeout(this.flushTimer);
    this.flushTimer = null;
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (this.pendingTargets.size === 0) {
      return;
    }
    const jointPositions = Object.fromEntries(this.pendingTargets);
    this.pendingTargets.clear();
    this.socket.send(JSON.stringify({ joint_positions: jointPositions }));
  }

  receive(event) {
    try {
      const message = JSON.parse(event.data);
      if (message.type === "simulation_state") {
        this.onState(message);
        this.onStatus("ready");
      } else if (message.type === "error") {
        this.onError(message.detail);
      }
    } catch (error) {
      this.onError(`Invalid simulation message: ${error.message}`);
    }
  }
}

window.G1SimulationSocket = G1SimulationSocket;
