"use strict";

const POLL_INTERVAL = 2000;
const requestUrl = new URL("./api/state", window.location.href);
requestUrl.search = window.location.search;

const elements = {
  main: document.querySelector("#queue-content"),
  workspace: document.querySelector("#workspace-name"),
  board: document.querySelector("#board-name"),
  connection: document.querySelector("#connection-status"),
  connectionDot: document.querySelector("#connection-dot"),
  refreshed: document.querySelector("#refresh-time"),
  syncMessage: document.querySelector("#sync-message"),
  loading: document.querySelector("#loading-state"),
  error: document.querySelector("#error-state"),
  errorCopy: document.querySelector("#error-copy"),
  empty: document.querySelector("#empty-state"),
  emptyTitle: document.querySelector("#empty-title"),
  emptyCopy: document.querySelector("#empty-copy"),
  queue: document.querySelector("#queue"),
  history: document.querySelector("#group-finished"),
};

const groupElements = Object.fromEntries(
  ["now", "waiting", "next", "finished"].map((name) => [name, {
    section: document.querySelector(`#group-${name}`),
    list: document.querySelector(`#list-${name}`),
    count: document.querySelector(`#group-count-${name}`),
    total: document.querySelector(`#count-${name}`),
  }]),
);

const rows = new Map();
let revision = null;
let hasSnapshot = false;
let timer = null;

function setText(node, value) {
  const next = value == null ? "" : String(value);
  if (node.textContent !== next) node.textContent = next;
}

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function taskCount(value) {
  return `${value} ${value === 1 ? "task" : "tasks"}`;
}

function formatTime(seconds, includeDate = true) {
  const date = new Date(finiteNumber(seconds, Date.now() / 1000) * 1000);
  if (Number.isNaN(date.getTime())) return "Unknown";
  const options = includeDate
    ? { dateStyle: "medium", timeStyle: "short" }
    : { hour: "2-digit", minute: "2-digit", second: "2-digit" };
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

function makeElement(tagName, className) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  return node;
}

function makeMetaItem(label) {
  const wrapper = makeElement("div");
  const term = makeElement("dt");
  const value = makeElement("dd");
  setText(term, label);
  wrapper.append(term, value);
  return { wrapper, value };
}

function createTaskRow(id) {
  const root = makeElement("details", "task");
  root.dataset.taskId = id;

  const summary = makeElement("summary", "task-summary");
  const status = makeElement("span", "task-status");
  const taskId = makeElement("span", "task-id");
  const title = makeElement("span", "task-title");
  const owner = makeElement("span", "task-owner");
  summary.append(status, taskId, title, owner);

  const body = makeElement("div", "task-body");
  const description = makeElement("p", "task-description");
  const waiting = makeElement("p", "waiting-copy");
  waiting.hidden = true;

  const update = makeElement("section", "latest-update");
  const updateHeading = makeElement("h3");
  const updateCopy = makeElement("p");
  setText(updateHeading, "Latest update");
  update.append(updateHeading, updateCopy);
  update.hidden = true;

  const meta = makeElement("dl", "task-meta");
  const priority = makeMetaItem("Priority");
  const updated = makeMetaItem("Updated");
  const created = makeMetaItem("Created");
  meta.append(priority.wrapper, updated.wrapper, created.wrapper);

  body.append(description, waiting, update, meta);
  root.append(summary, body);

  return {
    root,
    summary,
    status,
    taskId,
    title,
    owner,
    description,
    waiting,
    update,
    updateCopy,
    priority: priority.value,
    updated: updated.value,
    created: created.value,
  };
}

function displayStatus(task, group) {
  if (task.status === "doing") return { label: "Doing", className: "is-doing" };
  if (task.status === "blocked") return { label: "Blocked", className: "is-blocked" };
  if (group === "waiting") return { label: "Waiting", className: "is-waiting" };
  if (task.status === "done") return { label: "Done", className: "is-done" };
  if (task.status === "cancelled") return { label: "Cancelled", className: "is-cancelled" };
  return { label: "Queued", className: "is-queued" };
}

function updateTaskRow(row, task, group) {
  const status = displayStatus(task, group);
  row.root.className = "task";
  row.status.className = `task-status ${status.className}`;
  setText(row.status, status.label);
  setText(row.taskId, `#${task.id}`);
  setText(row.title, task.title || "Untitled task");
  setText(row.owner, task.owner_name || "Unassigned");

  const detail = task.detail == null ? "" : String(task.detail);
  setText(row.description, detail || "No description yet.");
  row.description.classList.toggle("is-empty", !detail);

  const waitingOn = Math.max(0, Math.trunc(finiteNumber(task.waiting_on)));
  row.waiting.hidden = waitingOn === 0;
  setText(
    row.waiting,
    waitingOn === 1
      ? "Waiting for 1 prerequisite task."
      : `Waiting for ${waitingOn} prerequisite tasks.`,
  );

  const note = task.note == null ? "" : String(task.note);
  row.update.hidden = !note;
  setText(row.updateCopy, note);

  setText(row.priority, `P${Math.max(0, Math.trunc(finiteNumber(task.priority, 5)))}`);
  setText(row.updated, formatTime(task.updated));
  setText(row.created, formatTime(task.created));
  const updatedDate = new Date(finiteNumber(task.updated) * 1000);
  const createdDate = new Date(finiteNumber(task.created) * 1000);
  row.updated.title = Number.isNaN(updatedDate.getTime()) ? "" : updatedDate.toISOString();
  row.created.title = Number.isNaN(createdDate.getTime()) ? "" : createdDate.toISOString();

  const accessibleTitle = task.title || "Untitled task";
  row.summary.setAttribute("aria-label", `${status.label}, task ${task.id}: ${accessibleTitle}`);
}

function classifyTasks(tasks) {
  const groups = { now: [], waiting: [], next: [], finished: [] };
  for (const task of tasks) {
    if (!task || typeof task !== "object") continue;
    if (task.status === "doing") groups.now.push(task);
    else if (task.status === "blocked" || (task.status === "queued" && finiteNumber(task.waiting_on) > 0)) {
      groups.waiting.push(task);
    } else if (task.status === "queued") groups.next.push(task);
    else if (task.status === "done" || task.status === "cancelled") groups.finished.push(task);
  }
  groups.finished.sort((left, right) =>
    finiteNumber(right.updated) - finiteNumber(left.updated)
      || finiteNumber(right.id) - finiteNumber(left.id));
  return groups;
}

function captureViewAnchor() {
  const activeTask = document.activeElement?.closest?.(".task[data-task-id]");
  const visibleTask = [...document.querySelectorAll(".task[data-task-id]")]
    .find((node) => {
      const bounds = node.getBoundingClientRect();
      return bounds.bottom > 0 && bounds.top < window.innerHeight;
    });
  const anchor = activeTask || visibleTask;
  return {
    id: anchor?.dataset.taskId || null,
    top: anchor?.getBoundingClientRect().top || 0,
    scrollY: window.scrollY,
    focusedId: activeTask?.dataset.taskId || null,
    historyFocused: document.activeElement === elements.history.querySelector("summary"),
  };
}

function restoreViewAnchor(view) {
  const anchor = view.id ? rows.get(view.id)?.root : null;
  if (anchor) {
    window.scrollBy(0, anchor.getBoundingClientRect().top - view.top);
  } else {
    window.scrollTo(0, view.scrollY);
  }

  if (view.focusedId) {
    const summary = rows.get(view.focusedId)?.summary;
    if (summary && !summary.contains(document.activeElement)) summary.focus({ preventScroll: true });
  } else if (view.historyFocused) {
    elements.history.querySelector("summary")?.focus({ preventScroll: true });
  }
}

function renderGroups(grouped) {
  const view = captureViewAnchor();
  const present = new Set();

  for (const [name, tasks] of Object.entries(grouped)) {
    const group = groupElements[name];
    group.section.hidden = tasks.length === 0;
    setText(group.count, taskCount(tasks.length));
    setText(group.total, tasks.length);

    for (const task of tasks) {
      const id = String(task.id);
      present.add(id);
      let row = rows.get(id);
      if (!row) {
        row = createTaskRow(id);
        rows.set(id, row);
      }
      updateTaskRow(row, task, name);
      group.list.append(row.root);
    }
  }

  for (const [id, row] of rows) {
    if (!present.has(id)) {
      row.root.remove();
      rows.delete(id);
    }
  }

  restoreViewAnchor(view);
}

function showConnection(kind, label) {
  elements.connectionDot.className = `connection-dot is-${kind}`;
  setText(elements.connection, label);
}

function renderState(state) {
  const snapshot = state?.snapshot;
  const workspaceName = state?.workspace_label || "Current space";
  const boardName = snapshot?.board?.name || "Tasks";
  setText(elements.workspace, workspaceName);
  setText(elements.board, boardName);
  document.title = `${workspaceName} / ${boardName}`;

  elements.loading.hidden = true;
  elements.error.hidden = true;
  elements.main.setAttribute("aria-busy", "false");

  if (!snapshot || !Array.isArray(snapshot.tasks)) {
    for (const group of Object.values(groupElements)) setText(group.total, 0);
    elements.queue.hidden = true;
    elements.empty.hidden = false;
    setText(elements.emptyTitle, "No queue is linked to this space");
    setText(elements.emptyCopy, "Ask an agent in this space to join its queue, then reopen this view.");
    return;
  }

  const grouped = classifyTasks(snapshot.tasks);
  renderGroups(grouped);
  const unfinished = grouped.now.length + grouped.waiting.length + grouped.next.length;
  const hasTasks = unfinished + grouped.finished.length > 0;

  elements.queue.hidden = !hasTasks;
  elements.empty.hidden = unfinished > 0 || grouped.finished.length > 0;
  if (!hasTasks) {
    setText(elements.emptyTitle, "The queue is clear");
    setText(elements.emptyCopy, "There is no active, queued, or finished work.");
  } else if (unfinished === 0) {
    elements.empty.hidden = false;
    setText(elements.emptyTitle, "The active queue is clear");
    setText(elements.emptyCopy, "Finished work remains available below.");
  }
}

function markSuccess(state) {
  hasSnapshot = true;
  showConnection("live", "Read-only · Live");
  elements.syncMessage.hidden = true;
  const servedAt = finiteNumber(state?.served_at, Date.now() / 1000);
  elements.refreshed.dateTime = new Date(servedAt * 1000).toISOString();
  setText(elements.refreshed, `Refreshed ${formatTime(servedAt, false)}`);
}

function markFailure(error) {
  showConnection("stale", "Read-only · Reconnecting");
  if (hasSnapshot) {
    elements.syncMessage.hidden = false;
    setText(elements.syncMessage, "Live updates are paused. Retrying automatically.");
    return;
  }
  elements.loading.hidden = true;
  elements.error.hidden = false;
  elements.main.setAttribute("aria-busy", "false");
  setText(elements.errorCopy, "The local viewer will retry automatically. " + (error?.message || ""));
}

async function refresh() {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(requestUrl, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Local viewer returned ${response.status}.`);
    const state = await response.json();
    if (!state || typeof state !== "object") throw new Error("The queue response was invalid.");

    markSuccess(state);
    if (state.revision !== revision) {
      renderState(state);
      revision = state.revision;
    }
  } catch (error) {
    markFailure(error);
  } finally {
    window.clearTimeout(timeout);
    timer = window.setTimeout(refresh, POLL_INTERVAL);
  }
}

window.addEventListener("pagehide", () => window.clearTimeout(timer), { once: true });
refresh();
