/* Map page: loads the map, the panels, preview -> confirm -> apply, undo and redo, history, candidates, save,
   opening another map, shortcuts. Ported from map-editor's map_editor.js. */

const mapBands = {};          // id -> [low slider, high slider]
let mapQueue = Promise.resolve();
let mapUnsaved = false;
let mapToolNames = {};
let mapStarted = false;
// Layer addresses change on every refresh, or the browser would not ask again.
let layerVersion = 0;
let mapCandidates = [];
let candidateKind = "ghost";
let selectedCandidate = null;

// Colours no layer uses (the projection is red, changes teal/orange/violet), so candidates never blend in.
const CANDIDATE_STYLE = {
  ghost: { stroke: "#c026d3", fill: "rgba(192, 38, 211, 0.30)", name: "ghosts", label: "ghost", verb: "Clear", tool: "candidate_erase" },
  missing: { stroke: "#2563eb", fill: "rgba(37, 99, 235, 0.30)", name: "gaps", label: "gap", verb: "Fill", tool: "candidate_fill" },
};
const CANDIDATE_NOTES = {
  ghost: "Obstacles in the grid with no points near them: usually people or carts that moved while mapping. Hints only; nothing changes until you clear one.",
  missing: "Many points at robot height over free cells: usually furniture the grid missed, or a ghost left in the point cloud. Check it in 3D before filling.",
};

// Every change waits for the one before: a click or key during a request is neither lost nor interleaved.
function runInOrder(action) {
  const guarded = () => Promise.resolve().then(action).catch((error) => toast(error.message, "error"));
  mapQueue = mapQueue.then(guarded, guarded);
  return mapQueue;
}

function bandValue(id) {
  return mapBands[id].map((slider) => Number(slider.value));
}

function showSliderValues() {
  for (const [id, [low, high]] of Object.entries(mapBands)) {
    document.getElementById(`${id}-lo-value`).textContent = Number(low.value).toFixed(2);
    document.getElementById(`${id}-hi-value`).textContent = Number(high.value).toFixed(2);
  }
  for (const id of ["map-brush-radius", "map-wall-width"]) document.getElementById(`${id}-value`).textContent = Number(document.getElementById(id).value).toFixed(2);
  for (const id of ["map-cand-min-points", "map-cand-min-cells"]) document.getElementById(`${id}-value`).textContent = document.getElementById(id).value;
}

// A band's low and high are a pair: dragged past each other they stop one step apart, so the band never empties.
function keepBandOrder(slider) {
  const band = Object.values(mapBands).find((pair) => pair.includes(slider));
  if (!band) return;
  const [low, high] = band;
  const step = Number(low.step);
  if (Number(high.value) - Number(low.value) > step / 2) return;
  if (slider === low) low.value = String(Number(high.value) - step);
  else high.value = String(Number(low.value) + step);
}

function setDefaults(defaults) {
  const pairs = { "map-proj-z": "projection_z_range_rel", "map-erase-z": "erase_z_range_rel", "map-ground-z": "ground_erase_z_range_rel", "map-cand-z": "candidate_z_range_rel" };
  for (const [id, key] of Object.entries(pairs)) [mapBands[id][0].value, mapBands[id][1].value] = defaults[key];
  document.getElementById("map-erase-value").value = String(defaults.erase_grid_value);
  document.getElementById("map-brush-radius").value = defaults.brush_radius_m;
  document.getElementById("map-wall-width").value = defaults.wall_width_m;
  document.getElementById("map-cand-min-points").value = defaults.candidate_min_points;
  document.getElementById("map-cand-min-cells").value = defaults.candidate_min_cells;
  showSliderValues();
}

function showMapInfo(info) {
  document.getElementById("map-name").textContent = info.map_id;
  document.getElementById("map-size").textContent = `${info.width} × ${info.height} · ${info.resolution} m`;
  document.getElementById("map-direction-text").textContent = info.main_direction_deg.toFixed(1);
  const values = info.grid_values;
  const points = (count, deleted, outside) => `${(count - deleted).toLocaleString()}${deleted ? ` (−${deleted.toLocaleString()} now)` : ""}, ${outside} off the grid`;
  const rows = [
    ["Folder", info.folder.split(/[\\/]/).at(-1)],
    ["Size", `${info.width} × ${info.height} cells`],
    ["Extent", `${(info.width * info.resolution).toFixed(2)} × ${(info.height * info.resolution).toFixed(2)} m`],
    ["Resolution", `${info.resolution} m`],
    ["Origin", `(${info.origin.slice(0, 2).map((value) => value.toFixed(2)).join(", ")})`],
    ["Floor", `per cell ${info.floor_range[0].toFixed(2)} … ${info.floor_range[1].toFixed(2)} m`],
    ["map.pcd", points(info.map_points, info.map_deleted, info.map_outside)],
    ["ground_map", points(info.ground_points, info.ground_deleted, info.ground_outside)],
    ["Occupied 0", `${(values["0"] ?? 0).toLocaleString()} cells`],
    ["Unknown 205", `${(values["205"] ?? 0).toLocaleString()} cells`],
    ["Free 254", `${(values["254"] ?? 0).toLocaleString()} cells`],
    ["Main direction", `${info.main_direction_deg.toFixed(1)}°`],
    ["Tour points", String(info.tour_points.length)],
    ["Compared with", info.original_source],
    ["Changed", `${info.changed_cells.toLocaleString()} cells`],
  ];
  document.getElementById("map-info").replaceChildren(...rows.flatMap(([label, value]) => [
    Object.assign(document.createElement("dt"), { className: "text-gray-500", textContent: label }),
    Object.assign(document.createElement("dd"), { className: "text-end font-medium text-gray-800", textContent: value }),
  ]));
}

// ---- candidates ----
async function refreshCandidates() {
  const [zLo, zHi] = bandValue("map-cand-z");
  const query = new URLSearchParams({ z_lo: zLo, z_hi: zHi, min_points: document.getElementById("map-cand-min-points").value, min_cells: document.getElementById("map-cand-min-cells").value });
  mapCandidates = await api("GET", `/api/map/candidates?${query}`);
  if (!mapCandidates.some((candidate) => candidate.id === selectedCandidate)) selectedCandidate = null;
  showCandidates();
  drawOverlay();
}

function showCandidates() {
  const style = CANDIDATE_STYLE[candidateKind];
  for (const kind of ["ghost", "missing"]) {
    document.getElementById(`map-${kind}-count`).textContent = mapCandidates.filter((candidate) => candidate.kind === kind).length;
    document.querySelector(`[data-kind=${kind}]`).dataset.active = String(kind === candidateKind);
  }
  document.getElementById("map-ghost-badge").textContent = mapCandidates.filter((candidate) => candidate.kind === "ghost").length;
  document.getElementById("map-candidate-note").textContent = CANDIDATE_NOTES[candidateKind];
  const shown = mapCandidates.filter((candidate) => candidate.kind === candidateKind);
  const list = document.getElementById("map-candidates");
  if (shown.length === 0) {
    list.innerHTML = `<li class="px-3 py-4 text-center text-gray-400">No ${style.name}</li>`;
    return;
  }
  list.replaceChildren(...shown.map((candidate) => {
    const item = document.createElement("li");
    item.dataset.candidate = candidate.id;
    item.className = `flex items-center gap-x-2 px-2.5 py-1.5 ${candidate.id === selectedCandidate ? "bg-blue-50" : "hover:bg-gray-50"}`;
    const locate = Object.assign(document.createElement("button"), { type: "button" });
    locate.dataset.action = "locate";
    locate.className = "min-w-0 flex-1 truncate text-start";
    locate.innerHTML = `<span class="font-semibold ${candidate.id === selectedCandidate ? "text-blue-700" : "text-gray-700"}">#${candidate.id}</span> `;
    locate.append(`${candidate.cells} cells · ${candidate.size_m.toFixed(1)} m`);
    locate.title = `Go to (${candidate.centre[0].toFixed(2)}, ${candidate.centre[1].toFixed(2)})`;
    const apply = Object.assign(document.createElement("button"), { type: "button", textContent: style.verb });
    apply.dataset.action = "apply";
    apply.className = candidate.id === selectedCandidate
      ? "rounded-md bg-blue-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-blue-700"
      : "rounded-md border border-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700 hover:bg-gray-100";
    item.append(locate, apply);
    return item;
  }));
}

// Only the kind being checked is drawn. Each area gets a white halo so it reads on black walls and on the
// point projection; one too small to see at this zoom gets a ring round it. A picked one is spotlit: the
// rest of the map dims, the area gets a thick outline and a label.
function drawCandidates(context) {
  const picked = mapCandidates.find((candidate) => candidate.id === selectedCandidate);
  for (const candidate of mapCandidates) {
    if (candidate.kind === candidateKind && candidate !== picked) drawCandidate(context, candidate, picked ? "other" : "all");
  }
  if (!picked) return;
  const rect = mapViewport.getBoundingClientRect();
  const box = candidateBox(picked);
  const margin = Math.max(28, 0.8 / mapView.resolution * mapView.zoom);
  context.save();
  context.beginPath();
  context.rect(0, 0, rect.width, rect.height);
  context.roundRect(box.left - margin, box.top - margin, box.width + margin * 2, box.height + margin * 2, 12);
  context.fillStyle = "rgba(17, 24, 39, 0.55)";
  context.fill("evenodd");
  context.restore();
  drawCandidate(context, picked, "picked");
  const style = CANDIDATE_STYLE[picked.kind];
  const text = `#${picked.id} ${style.label} · ${picked.cells} cells · ${picked.size_m.toFixed(1)} m`;
  context.save();
  context.font = "600 12px ui-sans-serif, system-ui, sans-serif";
  const width = context.measureText(text).width + 16;
  const x = Math.min(Math.max(8, box.left + box.width / 2 - width / 2), rect.width - width - 8);
  const y = Math.max(8, box.top - margin - 30);
  context.fillStyle = style.stroke;
  context.beginPath();
  context.roundRect(x, y, width, 22, 11);
  context.fill();
  context.fillStyle = "#ffffff";
  context.fillText(text, x + 8, y + 15);
  context.restore();
}

function candidateBox(candidate) {
  const points = candidate.polygon.map(([x, y]) => worldToScreen(x, y));
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const box = { left: Math.min(...xs), top: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
  return box;
}

// look: "all" (nothing picked), "picked", or "other" (thin dashed, no fill, so the picked one stands alone).
function drawCandidate(context, candidate, look) {
  const style = CANDIDATE_STYLE[candidate.kind];
  const picked = look === "picked";
  context.save();
  context.beginPath();
  candidate.polygon.forEach(([x, y], index) => {
    const screen = worldToScreen(x, y);
    if (index === 0) context.moveTo(screen.x, screen.y);
    else context.lineTo(screen.x, screen.y);
  });
  context.closePath();
  if (look === "other") {
    context.setLineDash([4, 4]);
    context.strokeStyle = style.stroke;
    context.lineWidth = 1.2;
    context.stroke();
    context.restore();
    return;
  }
  context.fillStyle = style.fill;
  context.fill();
  context.lineJoin = "round";
  context.strokeStyle = "#ffffff";
  context.lineWidth = picked ? 7 : 4;
  context.stroke();
  context.strokeStyle = style.stroke;
  context.lineWidth = picked ? 3.5 : 2;
  context.stroke();
  const box = candidateBox(candidate);
  if (Math.max(box.width, box.height) < 14) {
    context.beginPath();
    context.arc(box.left + box.width / 2, box.top + box.height / 2, picked ? 14 : 9, 0, Math.PI * 2);
    context.strokeStyle = "#ffffff";
    context.lineWidth = 4;
    context.stroke();
    context.strokeStyle = style.stroke;
    context.lineWidth = 2;
    context.stroke();
  }
  context.restore();
}

// Back to seeing every candidate of the kind (Esc, another kind, leaving the Check tab).
function clearCandidate() {
  if (selectedCandidate === null) return;
  selectedCandidate = null;
  showCandidates();
  drawOverlay();
  api("POST", "/api/map/highlight", { outline: [] });
}

// The map zooms onto the candidate and the 3D view flies there too.
async function locateCandidate(candidate) {
  selectedCandidate = candidate.id;
  const rect = mapViewport.getBoundingClientRect();
  const spanPx = Math.max(candidate.size_m, 1.0) / mapView.resolution;
  mapView.zoom = Math.min(12, Math.max(1, (Math.min(rect.width, rect.height) / spanPx) * 0.4));
  const pixel = worldToPixel(candidate.centre[0], candidate.centre[1]);
  mapView.panX = rect.width / 2 - pixel.col * mapView.zoom;
  mapView.panY = rect.height / 2 - pixel.row * mapView.zoom;
  mapView.autoFit = false;
  applyTransform();
  showCandidates();
  await api("POST", "/api/map/highlight", { outline: candidate.polygon, kind: candidate.kind });
  await api("POST", "/api/map/focus", { x: candidate.centre[0], y: candidate.centre[1], distance: Math.max(4, candidate.size_m * 3) });
}

async function applyCandidate(candidate) {
  await locateCandidate(candidate);
  await onShapeFinished(CANDIDATE_STYLE[candidate.kind].tool, { polygon: candidate.polygon });
}

// ---- layers ----
async function refreshProjection() {
  showSliderValues();
  layerVersion += 1;
  const [zLo, zHi] = bandValue("map-proj-z");
  const source = document.getElementById("map-projection-source").value;
  await loadLayer(document.getElementById("map-layer-projection"), `/api/map/projection.png?source=${source}&z_lo=${zLo}&z_hi=${zHi}&v=${layerVersion}`);
}

// An edit changes the current grid, the change highlight and the projection (deleted points leave it); not the original.
async function refreshMapLayers() {
  layerVersion += 1;
  const current = document.getElementById("map-layer-current");
  await loadLayer(current, `/api/map/grid.png?which=current&v=${layerVersion}`);
  readGridPixels(current);
  await loadLayer(document.getElementById("map-layer-diff"), `/api/map/diff.png?v=${layerVersion}`);
  await refreshProjection();
}

// Holding "Hold for original" shows only the original grid; letting go brings back each layer's own switch.
function bindCompare() {
  const button = document.getElementById("map-compare");
  const original = document.getElementById("map-layer-original");
  const others = ["current", "projection", "diff", "protection"].map((name) => document.getElementById(`map-layer-${name}`));
  const show = (comparing) => {
    original.style.display = comparing ? "block" : "";
    for (const layer of others) layer.style.visibility = comparing ? "hidden" : "";
  };
  button.addEventListener("pointerdown", () => show(true));
  for (const type of ["pointerup", "pointerleave", "pointercancel"]) button.addEventListener(type, () => show(false));
}

// ---- edits ----
function buildRequest(tool, geometry) {
  const action = TOOLS[tool].action;
  const params = action === "erase"
    ? {
      grid_value: Number(document.getElementById("map-erase-value").value),
      apply_to_pcd: document.getElementById("map-apply-pcd").checked,
      keep_protected: document.getElementById("map-keep-protected").checked,
      z_range_rel: bandValue("map-erase-z"),
      ground_z_range_rel: bandValue("map-ground-z"),
    }
    : {};
  return { tool, action, geometry, params };
}

function geometryCentre(geometry) {
  const points = geometry.polygon ?? geometry.polyline;
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  return {
    x: (Math.min(...xs) + Math.max(...xs)) / 2,
    y: (Math.min(...ys) + Math.max(...ys)) / 2,
    size: Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)),
  };
}

// Called by map_tools.js when a shape is done. Erasing previews and waits; adding obstacles applies at once.
async function onShapeFinished(tool, geometry) {
  const request = buildRequest(tool, geometry);
  if (request.action === "obstacle") {
    await applyEdit(request);
    return;
  }
  const preview = await api("POST", "/api/map/edit/preview", request);
  pendingShape = { tool, geometry, request, preview };
  drawOverlay();
  let text = request.params.apply_to_pcd
    ? `${preview.cells.toLocaleString()} cells cleared · ${preview.map_points.toLocaleString()} map.pcd and ${preview.ground_points.toLocaleString()} ground_map points deleted (red in 3D)`
    : `${preview.cells.toLocaleString()} cells cleared · grid only, no points deleted`;
  if (preview.protected_points > 0) {
    text += preview.kept_protected
      ? ` · ${preview.protected_points.toLocaleString()} protected points kept (magenta in 3D)`
      : ` · ${preview.protected_points.toLocaleString()} protected points deleted too!`;
  }
  const risky = !preview.kept_protected && preview.protected_points > preview.protect_warn_points;
  const card = document.getElementById("map-pending");
  document.getElementById("map-pending-title").textContent = mapToolNames[tool];
  document.getElementById("map-pending-text").textContent = text;
  card.classList.toggle("border-amber-300", risky);
  card.classList.toggle("bg-amber-50", risky);
  card.classList.remove("hidden");
  if (document.getElementById("map-follow").checked) {
    const centre = geometryCentre(geometry);
    await api("POST", "/api/map/focus", { x: centre.x, y: centre.y, distance: Math.max(4, centre.size * 2.5) });
  }
}

async function confirmEdit() {
  if (!pendingShape) return;
  const { request, preview } = pendingShape;
  // Deleting many protected points (walls, pillars) can hurt localization: ask once more.
  const risky = !preview.kept_protected && preview.protected_points > preview.protect_warn_points;
  if (risky && !(await confirmDialog({
    title: `Delete ${preview.protected_points.toLocaleString()} protected points?`,
    text: "They belong to walls and pillars; removing them can hurt localization.", ok: "Delete", danger: true,
  }))) return;
  pendingShape = null;
  document.getElementById("map-pending").classList.add("hidden");
  await applyEdit(request);
}

async function cancelEdit() {
  if (!pendingShape) return;
  pendingShape = null;
  document.getElementById("map-pending").classList.add("hidden");
  drawOverlay();
  await api("POST", "/api/map/edit/cancel", {});
}

async function applyEdit(request) {
  const result = await api("POST", "/api/map/edit", request);
  await afterChange(result);
  if (!result.command) {
    toast("The shape covers no cell of the map; nothing changed", "warning");
    return;
  }
  if (request.action === "obstacle") rememberVertices(request.geometry);
  toast(`#${result.command.id} ${result.command.summary}`);
}

async function undoEdit() {
  await cancelEdit();
  const result = await api("POST", "/api/map/undo", {});
  await afterChange(result);
  toast(result.command ? `Undid #${result.command.id} ${result.command.summary}` : "Nothing to undo", "info");
}

async function redoEdit() {
  await cancelEdit();
  const result = await api("POST", "/api/map/redo", {});
  await afterChange(result);
  toast(result.command ? `Redid #${result.command.id} ${result.command.summary}` : "Nothing to redo", "info");
}

// After every change the candidates are found again (about 0.01 s): a cleared ghost leaves the list. They are
// renumbered by size, so the old selection may point elsewhere; it is dropped.
async function afterChange(result) {
  showHistory(result.history);
  await refreshMapLayers();
  clearCandidate();
  await refreshCandidates();
  showMapInfo(await api("GET", "/api/map"));
}

async function saveMap() {
  await cancelEdit();
  const confirmed = await confirmDialog({
    title: "Save and export this map?",
    text: "grid.pgm, map.pcd and ground_map.pcd in its folder are replaced and the manifest checksums updated. The first save keeps the originals as *.orig.*, and every save puts the version before in .backup/. Then the folder's files (manifest.json, map.pcd, ground_map.pcd, grid.pgm, grid.yaml) download as a .zip.",
    ok: "Save & export",
  });
  if (!confirmed) return;
  const button = document.getElementById("map-save");
  button.disabled = true;
  try {
    const result = await api("POST", "/api/map/save", {});
    showHistory(result.history);
    showMapInfo(await api("GET", "/api/map"));
    const name = result.package_url.split("/").at(-1);
    const link = Object.assign(document.createElement("a"), { href: result.package_url, download: name });
    link.click();
    toast(`Saved: ${result.map_points.toLocaleString()} map.pcd points, ${result.cells_changed.toLocaleString()} cells changed from the original. Downloading ${name}.`, "success");
  } finally {
    button.disabled = false;
  }
}

function showHistory(history) {
  document.getElementById("map-undo").disabled = !history.can_undo;
  document.getElementById("map-redo").disabled = !history.can_redo;
  const restore = document.getElementById("map-restore");
  restore.disabled = !history.can_restore;
  restore.title = history.can_restore ? "" : "There is an original to go back to only after the first save";
  mapUnsaved = history.dirty;
  document.getElementById("map-dirty").classList.toggle("invisible", !history.dirty);
  document.getElementById("map-history-badge").textContent = history.entries.filter((entry) => !entry.undone).length;
  // Newest first; the last row goes back to before the first change.
  const entries = [...history.entries].reverse();
  const latest = history.entries.filter((entry) => !entry.undone).at(-1)?.id ?? 0;
  const item = (id, label, text, undone) => {
    const button = Object.assign(document.createElement("button"), { type: "button" });
    button.dataset.jump = id;
    button.className = `flex w-full items-start gap-x-2 rounded-lg px-2.5 py-1.5 text-start ${id === latest ? "bg-blue-50 ring-1 ring-blue-600" : "hover:bg-gray-50"} ${undone ? "text-gray-400 line-through" : "text-gray-700"}`;
    button.append(Object.assign(document.createElement("span"), { className: `shrink-0 font-semibold ${id === latest ? "text-blue-700" : "text-gray-500"}`, textContent: label }),
      Object.assign(document.createElement("span"), { className: "min-w-0", textContent: text }));
    const row = document.createElement("li");
    row.append(button);
    return row;
  };
  document.getElementById("map-history").replaceChildren(
    ...entries.map((entry) => item(entry.id, `#${entry.id}`, entry.summary, entry.undone)),
    item(0, "Opened", entries.length === 0 ? "no changes yet" : "before the first change", false),
  );
}

async function jumpTo(commandId) {
  await cancelEdit();
  const result = await api("POST", `/api/map/history/jump/${commandId}`, {});
  await afterChange(result);
  if (result.moved > 0) toast(commandId === 0 ? "Back to the map as opened" : `Back at #${commandId}`, "info");
}

async function restoreOriginal() {
  await cancelEdit();
  const confirmed = await confirmDialog({
    title: "Restore the original map?",
    text: "The *.orig files go back into place; the current version is kept in .backup/ first and this session's history is cleared. Exported .g1map files are not affected.",
    ok: "Restore",
  });
  if (!confirmed) return;
  const result = await api("POST", "/api/map/restore", {});
  if (!result.restored) {
    toast("This map hasn't been saved yet, so there is no original to restore", "warning");
    return;
  }
  // A new document: the protected zone is worked out again and the original grid is fetched again.
  layerVersion += 1;
  await loadLayer(document.getElementById("map-layer-protection"), `/api/map/protection.png?v=${layerVersion}`);
  await loadLayer(document.getElementById("map-layer-original"), `/api/map/grid.png?which=original&v=${layerVersion}`);
  await afterChange(result);
  toast(`Restored the original; the version before is in ${result.backup_dir}`);
}

// ---- opening another map ----
async function showOpenDialog(closable) {
  const dialog = document.getElementById("map-open-dialog");
  for (const id of ["map-open-close", "map-open-cancel"]) document.getElementById(id).hidden = !closable;
  // Without a map there is nothing behind the dialog to go back to.
  dialog.oncancel = closable ? null : (event) => event.preventDefault();
  const listing = await api("GET", "/api/map/maps");
  document.getElementById("map-root").textContent = listing.root;
  const list = document.getElementById("map-list");
  list.replaceChildren(...listing.maps.map((entry) => mapListItem(entry, entry.folder === listing.current)));
  if (listing.maps.length === 0) list.innerHTML = '<li class="text-xs text-gray-400">No maps yet; upload a map .zip.</li>';
  if (!dialog.open) dialog.showModal();
}

function mapListItem(entry, current) {
  const button = Object.assign(document.createElement("button"), { type: "button" });
  button.dataset.folder = entry.folder;
  button.className = `flex w-full items-center gap-x-3 rounded-[10px] border px-3 py-2.5 text-start hover:bg-gray-50 ${current ? "border-blue-600 bg-blue-50" : "border-gray-200"}`;
  button.innerHTML = `<svg class="size-[18px] shrink-0 ${current ? "text-blue-600" : "text-gray-400"}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/></svg>`;
  const text = document.createElement("span");
  text.className = "min-w-0";
  const time = new Date(entry.modified * 1000).toLocaleString([], { hour12: false });
  const state = [current ? "Open now" : "", entry.saved ? "saved changes" : "", `${entry.tour_points} tour point${entry.tour_points === 1 ? "" : "s"}`, `grid edited ${time}`].filter(Boolean).join(" · ");
  text.append(Object.assign(document.createElement("span"), { className: "block text-sm font-semibold text-gray-900", textContent: entry.folder }),
    Object.assign(document.createElement("span"), { className: "block text-xs text-gray-500", textContent: state }));
  button.append(text);
  const item = document.createElement("li");
  item.append(button);
  return item;
}

// Changing map drops unsaved changes (asked first); the page then reloads, so layers, settings and 3D start fresh.
async function openMap(send) {
  if (mapUnsaved && !(await confirmDialog({ title: "Discard unsaved changes?", text: "Opening another map drops the changes made to this one.", ok: "Discard and open", danger: true }))) return;
  const dialog = document.getElementById("map-open-dialog");
  const buttons = dialog.querySelectorAll("button");
  for (const button of buttons) button.disabled = true;
  document.getElementById("map-open-status").classList.remove("hidden");
  try {
    await send();
  } catch (error) {
    for (const button of buttons) button.disabled = false;
    document.getElementById("map-upload").disabled = document.getElementById("map-upload-file").files.length === 0;
    document.getElementById("map-open-status").classList.add("hidden");
    toast(`Couldn't open it: ${error.message}`, "error");
    return;
  }
  mapUnsaved = false;
  location.reload();
}

function bindOpenDialog() {
  const dialog = document.getElementById("map-open-dialog");
  const file = document.getElementById("map-upload-file");
  document.getElementById("map-open").addEventListener("click", () => runInOrder(() => showOpenDialog(true)));
  for (const id of ["map-open-close", "map-open-cancel"]) document.getElementById(id).addEventListener("click", () => dialog.close());
  document.getElementById("map-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-folder]");
    if (button) openMap(() => api("POST", "/api/map/maps/open", { folder: button.dataset.folder }));
  });
  file.addEventListener("change", () => {
    document.getElementById("map-upload").disabled = file.files.length === 0;
    document.getElementById("map-upload-label").textContent = file.files[0]?.name ?? "Choose a map .zip";
  });
  document.getElementById("map-upload").addEventListener("click", () => openMap(() => api("POST", "/api/map/maps/upload", file.files[0])));
}

// Ctrl+Z undo, Ctrl+Shift+Z / Ctrl+Y redo, Ctrl+S save, Enter confirms or finishes a wall, Esc cancels;
// only while the Map page is shown and no field has the keyboard.
function bindShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (currentPage() !== "map" || !mapView.loaded) return;
    if (event.target.closest("input, select, textarea, dialog")) return;
    const key = event.key.toLowerCase();
    const control = event.ctrlKey || event.metaKey;
    if (control && key === "z" && !event.shiftKey) runInOrder(undoEdit);
    else if (control && ((key === "z" && event.shiftKey) || key === "y")) runInOrder(redoEdit);
    else if (control && key === "s") runInOrder(saveMap);
    else if (key === "enter" && pendingShape) runInOrder(confirmEdit);
    else if (key === "enter" && toolPoints.length > 0) finishShape();
    else if (key === "escape" && pendingShape) runInOrder(cancelEdit);
    else if (key === "escape" && toolPoints.length === 0 && selectedCandidate !== null) clearCandidate();
    else if (key === "escape") cancelDrawing();
    else return;
    event.preventDefault();
  });
  window.addEventListener("beforeunload", (event) => {
    if (mapUnsaved) event.preventDefault();
  });
}

function showMapTab(tab) {
  for (const button of document.querySelectorAll("[data-map-tab]")) button.dataset.active = String(button.dataset.mapTab === tab);
  for (const pane of document.querySelectorAll("[data-map-pane]")) pane.classList.toggle("hidden", pane.dataset.mapPane !== tab);
  // While checking, the point projection is faded to grey: context for the candidates, not a red sea.
  document.getElementById("map-layer-projection").classList.toggle("map-checking", tab === "check");
  if (tab !== "check") clearCandidate();
}

function bindPanels() {
  for (const id of ["map-proj-z", "map-erase-z", "map-ground-z", "map-cand-z"]) mapBands[id] = [document.getElementById(`${id}-lo`), document.getElementById(`${id}-hi`)];
  for (const button of document.querySelectorAll("[data-map-tab]")) button.addEventListener("click", () => showMapTab(button.dataset.mapTab));
  for (const input of document.querySelectorAll("[data-layer]")) input.addEventListener("change", () => setLayerVisible(input.dataset.layer, input.checked));
  for (const button of document.querySelectorAll("[data-tool]")) button.addEventListener("click", () => selectTool(button.dataset.tool));
  for (const slider of document.querySelectorAll('[data-page="map"] input[type=range]')) {
    slider.addEventListener("input", () => {
      keepBandOrder(slider);
      showSliderValues();
      drawOverlay();
    });
  }
  for (const slider of mapBands["map-proj-z"]) slider.addEventListener("change", () => runInOrder(refreshProjection));
  document.getElementById("map-projection-source").addEventListener("change", () => runInOrder(refreshProjection));
  for (const slider of [...mapBands["map-cand-z"], document.getElementById("map-cand-min-points"), document.getElementById("map-cand-min-cells")]) {
    slider.addEventListener("change", () => runInOrder(refreshCandidates));
  }
  for (const button of document.querySelectorAll("[data-kind]")) {
    button.addEventListener("click", () => {
      candidateKind = button.dataset.kind;
      clearCandidate();
      showCandidates();
      drawOverlay();
    });
  }
  document.getElementById("map-candidates").addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const candidate = mapCandidates.find((item) => item.id === Number(button.closest("[data-candidate]").dataset.candidate));
    runInOrder(() => (button.dataset.action === "locate" ? locateCandidate(candidate) : applyCandidate(candidate)));
  });
  document.getElementById("map-fit").addEventListener("click", fitView);
  // The card sits on the map: without stopping them, its clicks would reach the map and start a new shape.
  const card = document.getElementById("map-pending");
  for (const type of ["pointerdown", "pointermove", "pointerup", "dblclick", "wheel"]) card.addEventListener(type, (event) => event.stopPropagation());
  document.getElementById("map-confirm").addEventListener("click", () => runInOrder(confirmEdit));
  document.getElementById("map-cancel").addEventListener("click", () => runInOrder(cancelEdit));
  document.getElementById("map-history").addEventListener("click", (event) => {
    const button = event.target.closest("[data-jump]");
    if (button) runInOrder(() => jumpTo(Number(button.dataset.jump)));
  });
  document.getElementById("map-restore").addEventListener("click", () => runInOrder(restoreOriginal));
  for (const input of document.querySelectorAll("[data-scene]")) {
    input.addEventListener("change", () => runInOrder(() => api("POST", "/api/map/scene/layer", { name: input.dataset.scene, visible: input.checked })));
  }
  document.getElementById("map-undo").addEventListener("click", () => runInOrder(undoEdit));
  document.getElementById("map-redo").addEventListener("click", () => runInOrder(redoEdit));
  document.getElementById("map-save").addEventListener("click", () => runInOrder(saveMap));
}

function resolveViewerUrl(viewerUrl) {
  // MAP_VISER_PUBLIC_URL is already a full origin; otherwise rewrite loopback/bind-all to the page host.
  try {
    const url = new URL(viewerUrl);
    if (url.hostname === "127.0.0.1" || url.hostname === "0.0.0.0" || url.hostname === "localhost") {
      url.protocol = location.protocol;
      url.hostname = location.hostname;
    }
    return url.href.endsWith("/") ? url.href : `${url.href}/`;
  } catch {
    return viewerUrl.replace("127.0.0.1", location.hostname).replace("0.0.0.0", location.hostname);
  }
}

async function startMap() {
  // Opening a map reads its point clouds (a few seconds), so it waits until the Map page is first shown.
  if (mapStarted) {
    if (mapView.autoFit) fitView();
    return;
  }
  mapStarted = true;
  bindOpenDialog();
  bindPanels();
  bindPanZoom();
  bindShortcuts();
  bindCompare();
  showMapTab("tools");
  document.getElementById("map-tool-hint").textContent = "Loading the map…";
  const info = await api("GET", "/api/map");
  document.getElementById("map-viewer").src = resolveViewerUrl(info.viewer_url);
  if (!info.loaded) {
    document.getElementById("map-empty").classList.replace("hidden", "flex");
    document.getElementById("map-tool-hint").textContent = "";
    await showOpenDialog(false);
    return;
  }
  setMapView(info);
  showMapInfo(info);
  setDefaults(info.defaults);
  mapToolNames = info.tool_names;
  snapRadius = info.snap_radius_m;
  for (const input of document.querySelectorAll("[data-scene]")) input.checked = info.scene_layers[input.dataset.scene];
  selectTool("pan");
  await loadLayer(document.getElementById("map-layer-original"), "/api/map/grid.png?which=original");
  await loadLayer(document.getElementById("map-layer-protection"), "/api/map/protection.png");
  await refreshMapLayers();
  showHistory(await api("GET", "/api/map/history"));
  await refreshCandidates();
  fitView();
}

document.addEventListener("DOMContentLoaded", () => {
  onTabShown("map", () => runInOrder(startMap));
});
