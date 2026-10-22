// ---------------------------------------------------------------------------
// chair.js - chairperson pages. Needs api.js loaded first.
// Every rule is also enforced by the server; the page only makes it clear.
// ---------------------------------------------------------------------------

const OTHER_PAGES = {
  member: "../../member/dashboard.html",
  secretary: "../secretary/monthly_lists.html",
  treasurer: "../treasurer/account_overview.html",
};

const state = {
  group: "staff",
  currentUserId: null,
  accounts: [],
  settings: null,
  levies: [],
  levy: null,            // the special contribution open in the detail view
  editingLevyId: null,   // null means the modal creates a new one
  confirmAction: null,
};

let searchTimer = null;


// ----- Helpers -------------------------------------------------------------

function byId(id) { return document.getElementById(id); }

function money(value) {
  const n = Number(value || 0);
  return "KES " + n.toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function shortDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" });
}

function dateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-KE", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// Today's date in Nairobi, as YYYY-MM-DD, to compare with deadlines.
function nairobiToday() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Nairobi" });
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function badge(text, kind) { return el("span", text, "badge badge-" + kind); }

function cell(row, content, className) {
  const td = el("td", null, className);
  if (content instanceof Node) td.appendChild(content);
  else td.textContent = content;
  row.appendChild(td);
  return td;
}

function button(label, className, onClick) {
  const b = el("button", label, "btn btn-small " + className);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function setText(id, text) { byId(id).textContent = text; }

function showWarning(message) { setText("warning-message", message || ""); }

function showNotice(message) {
  setText("notice-message", message || "");
  if (message) window.scrollTo({ top: 0, behavior: "smooth" });
}

function detailOf(err, fallback) {
  return (err && err.data && err.data.detail) || fallback;
}

function setBusy(btn, isBusy, busyText) {
  if (isBusy) {
    btn.dataset.label = btn.textContent;
    btn.textContent = busyText || "Please wait...";
    btn.disabled = true;
  } else {
    btn.textContent = btn.dataset.label || btn.textContent;
    btn.disabled = false;
  }
}

// Puts Django's field errors under the matching fields: prefix + field name.
function showFieldErrors(data, prefix, generalId) {
  let placed = false;
  Object.entries(data || {}).forEach(function ([field, messages]) {
    const slot = byId(prefix + field);
    if (slot) {
      slot.textContent = [].concat(messages).join(" ");
      placed = true;
    }
  });
  if (!placed && generalId) {
    setText(generalId, (data && data.detail) || "Something went wrong. Please check the form.");
  }
}

function clearErrors(container) {
  container.querySelectorAll(".field-error, .modal-error").forEach(function (slot) {
    slot.textContent = "";
  });
}

function handleRequestError(err, fallback) {
  if (err.status === 401) { goToLogin(); return; }
  if (err.status === 403) { showWarning("This page is for the chairperson only."); return; }
  showWarning(detailOf(err, fallback));
}


// ----- Guard, tabs and modals ----------------------------------------------

function guardPage() {
  if (!getAccessToken()) { goToLogin(); return false; }
  const role = getRole();
  if (role && role !== "chairperson") {
    window.location.href = OTHER_PAGES[role] || "../../login.html";
    return false;
  }
  return true;
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  ["accounts", "settings", "levies"].forEach(function (tab) {
    byId("tab-" + tab).hidden = tab !== name;
  });
  showWarning("");
  if (name === "accounts") loadAccounts();
  if (name === "settings") loadSettings();
  if (name === "levies") { showLevyList(); loadLevies(); }
}

function openModal(id) {
  const modal = byId(id);
  clearErrors(modal);
  modal.hidden = false;
  const first = modal.querySelector("input, textarea, select");
  if (first) first.focus();
}

function closeModal(id) { byId(id).hidden = true; }

function askConfirm(title, text, confirmLabel, action) {
  setText("confirm-title", title);
  setText("confirm-text", text);
  setText("confirm-yes", confirmLabel);
  state.confirmAction = action;
  openModal("confirm-modal");
}


// ===========================================================================
// Accounts
// ===========================================================================

async function loadAccounts() {
  const search = byId("account-search").value.trim();
  const query = "?group=" + state.group + (search ? "&search=" + encodeURIComponent(search) : "");
  try {
    const data = await apiRequest("/chair/accounts/" + query, "GET");
    state.currentUserId = data.current_user_id;
    state.accounts = data.accounts;
    renderAccounts();
  } catch (err) {
    handleRequestError(err, "Could not load the accounts.");
  }
}

function renderAccounts() {
  const isStaff = state.group === "staff";
  byId("new-staff-btn").hidden = !isStaff;
  setText(
    "accounts-explainer",
    isStaff
      ? "Officials' accounts for their official pages. A role is fixed once created; end a term by deactivating."
      : "Members' accounts. A deactivated member stops owing new contributions; debts already owed stay owed."
  );

  const body = document.querySelector("#accounts-table tbody");
  body.innerHTML = "";
  byId("no-accounts").hidden = state.accounts.length > 0;

  state.accounts.forEach(function (acc) {
    const tr = document.createElement("tr");
    if (!acc.is_active) tr.className = "is-inactive";

    const nameCell = cell(tr, acc.full_name, "strong");
    nameCell.appendChild(el("span", acc.username + (acc.phone ? " · " + acc.phone : ""), "sub-note"));

    cell(tr, badge(acc.role_label, "role"));

    const statusCell = document.createElement("span");
    if (acc.is_active) {
      statusCell.appendChild(badge("Active", "active"));
    } else {
      statusCell.appendChild(badge("Deactivated", "deactivated"));
      statusCell.appendChild(el("span", "Reason: " + (acc.deactivation_reason || "—"), "sub-note"));
      statusCell.appendChild(el(
        "span",
        "By " + (acc.deactivated_by_name || "unknown") + " on " + dateTime(acc.deactivated_at),
        "sub-note"
      ));
    }
    cell(tr, statusCell);

    cell(tr, shortDate(acc.date_joined_sacco));
    cell(tr, acc.last_login ? dateTime(acc.last_login) : "Never");

    const actions = cell(tr, "", "actions");
    if (acc.id === state.currentUserId) {
      actions.appendChild(badge("You", "you"));
    } else if (acc.is_active) {
      actions.appendChild(button("Deactivate", "btn-warn", function () { openDeactivate(acc); }));
    } else {
      actions.appendChild(button("Reactivate", "btn-sky", function () { confirmReactivate(acc); }));
    }

    body.appendChild(tr);
  });
}

function setGroup(group) {
  state.group = group;
  document.querySelectorAll(".segmented button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.group === group);
  });
  loadAccounts();
}

// ----- Create a staff account ----------------------------------------------

function openStaffModal() {
  byId("staff-form").reset();
  openModal("staff-modal");
}

async function submitStaff(event) {
  event.preventDefault();
  const form = byId("staff-modal");
  clearErrors(form);

  const body = {
    first_name: byId("staff-first").value.trim(),
    last_name: byId("staff-last").value.trim(),
    username: byId("staff-username").value.trim(),
    email: byId("staff-email").value.trim(),
    role: byId("staff-role").value,
    password: byId("staff-password").value,
    password2: byId("staff-password2").value,
  };

  const btn = byId("staff-save");
  setBusy(btn, true, "Creating...");
  try {
    const created = await apiRequest("/chair/accounts/staff/", "POST", body);
    closeModal("staff-modal");
    showNotice(
      "Staff account " + created.username + " created as " + created.role_label +
        ". Share the temporary password privately, and ask them to change it through Forgot password."
    );
    setGroup("staff");
  } catch (err) {
    if (err.status === 401) { goToLogin(); return; }
    showFieldErrors(err.data, "staff-error-", "staff-error");
  } finally {
    setBusy(btn, false);
  }
}

// ----- Deactivate and reactivate -------------------------------------------

function openDeactivate(acc) {
  state.deactivating = acc;
  byId("deactivate-reason").value = "";
  setText(
    "deactivate-text",
    "Deactivate " + acc.full_name + " (" + acc.username + ")? They will be logged out and unable to log in." +
      (acc.role === "member"
        ? " They stop owing new contributions until reactivated; existing debts stay owed."
        : "")
  );
  openModal("deactivate-modal");
}

async function submitDeactivate(event) {
  event.preventDefault();
  const modal = byId("deactivate-modal");
  clearErrors(modal);

  const reason = byId("deactivate-reason").value.trim();
  if (reason.length < 5) {
    setText("deactivate-error-reason", "Give a reason of at least 5 characters.");
    return;
  }

  const acc = state.deactivating;
  const btn = byId("deactivate-save");
  setBusy(btn, true, "Deactivating...");
  try {
    await apiRequest("/chair/accounts/" + acc.id + "/deactivate/", "POST", { reason });
    closeModal("deactivate-modal");
    showNotice(acc.full_name + " has been deactivated.");
    loadAccounts();
  } catch (err) {
    if (err.status === 401) { goToLogin(); return; }
    showFieldErrors(err.data, "deactivate-error-", "deactivate-error");
  } finally {
    setBusy(btn, false);
  }
}

function confirmReactivate(acc) {
  askConfirm(
    "Reactivate Account",
    "Reactivate " + acc.full_name + " (" + acc.username + ")? They will be able to log in again." +
      (acc.role === "member"
        ? " They owe contributions again from this month; the months while deactivated are skipped."
        : ""),
    "Reactivate",
    async function () {
      await apiRequest("/chair/accounts/" + acc.id + "/reactivate/", "POST");
      showNotice(acc.full_name + " has been reactivated.");
      loadAccounts();
    }
  );
}


// ===========================================================================
// Monthly settings
// ===========================================================================

async function loadSettings() {
  try {
    const data = await apiRequest("/chair/settings/", "GET");
    state.settings = data;
    setText("current-amount", data.monthly_amount ? money(data.monthly_amount) : "Not set");
    setText("current-rate", Number(data.penalty_rate) + "%");
    setText("settings-updated", data.updated_at ? dateTime(data.updated_at) : "—");
    byId("set-amount").value = data.monthly_amount ? Math.round(Number(data.monthly_amount)) : "";
    byId("set-rate").value = Number(data.penalty_rate);

    const on = Boolean(data.auto_prompt_enabled);
    byId("set-auto-enabled").checked = on;
    byId("set-auto-threshold").value =
      data.auto_prompt_threshold != null ? Math.round(Number(data.auto_prompt_threshold)) : 3000;
    byId("set-auto-max").value =
      data.auto_prompt_max_per_day != null ? Number(data.auto_prompt_max_per_day) : 3;
    setText(
      "current-auto",
      on
        ? "On · from " + money(data.auto_prompt_threshold) + " · " +
            Number(data.auto_prompt_max_per_day) + " a day"
        : "Off"
    );
  } catch (err) {
    handleRequestError(err, "Could not load the monthly settings.");
  }
}

function submitSettings(event) {
  event.preventDefault();
  const form = byId("settings-form");
  clearErrors(form);

  const amount = Number(byId("set-amount").value);
  const rate = Number(byId("set-rate").value);
  const autoEnabled = byId("set-auto-enabled").checked;
  const threshold = Number(byId("set-auto-threshold").value);
  const maxPerDay = Number(byId("set-auto-max").value);

  if (!amount || amount < 1) {
    setText("error-monthly_amount", "Enter an amount of at least KES 1.");
    return;
  }
  if (byId("set-rate").value === "" || rate < 0 || rate > 100) {
    setText("error-penalty_rate", "Enter a percentage between 0 and 100.");
    return;
  }
  if (byId("set-auto-threshold").value === "" || threshold < 0) {
    setText("error-auto_prompt_threshold", "Enter a debt amount of KES 0 or more.");
    return;
  }
  if (!maxPerDay || maxPerDay < 1 || maxPerDay > 10) {
    setText("error-auto_prompt_max_per_day", "Enter a number between 1 and 10.");
    return;
  }

  askConfirm(
    "Change the Monthly Settings",
    "Set the monthly contribution to " + money(amount) + " and the late fine to " + rate + "%. " +
      (autoEnabled
        ? "Automatic reminders on for members owing " + money(threshold) +
            " or more, up to " + maxPerDay + " a day."
        : "Automatic reminders off.") +
      " The new amount applies from next month.",
    "Save changes",
    async function () {
      try {
        await apiRequest("/chair/settings/", "PUT", {
          monthly_amount: amount,
          penalty_rate: rate,
          auto_prompt_enabled: autoEnabled,
          auto_prompt_threshold: threshold,
          auto_prompt_max_per_day: maxPerDay,
        });
      } catch (err) {
        closeModal("confirm-modal");
        showFieldErrors(err.data, "error-", null);
        throw err;
      }
      showNotice("Monthly settings saved.");
      loadSettings();
    }
  );
}


// ===========================================================================
// Special contributions
// ===========================================================================

async function loadLevies() {
  try {
    const data = await apiRequest("/chair/levies/", "GET");
    state.levies = data.levies;
    renderLevies();
  } catch (err) {
    handleRequestError(err, "Could not load the special contributions.");
  }
}

const LEVY_BADGE = { active: "active", closed: "closed", cancelled: "cancelled" };

function renderLevies() {
  const body = document.querySelector("#levies-table tbody");
  body.innerHTML = "";
  byId("no-levies").hidden = state.levies.length > 0;

  state.levies.forEach(function (levy) {
    const s = levy.summary;
    const tr = document.createElement("tr");

    const reason = cell(tr, levy.purpose, "strong");
    reason.appendChild(el("span", "Created " + shortDate(levy.created_at) + " by " + (levy.created_by_name || "—"), "sub-note"));

    cell(tr, money(levy.amount), "num");
    cell(tr, shortDate(levy.deadline));
    cell(tr, levy.fine_label);
    cell(tr, badge(levy.status_label, LEVY_BADGE[levy.status] || "closed"));
    cell(tr, s.fully_paid + " of " + s.members, "num");
    cell(tr, money(s.collected), "num");
    cell(tr, money(s.outstanding), "num");

    const actions = cell(tr, "", "actions");
    actions.appendChild(button("View", "btn-outline", function () { openLevy(levy.id); }));

    body.appendChild(tr);
  });
}

function showLevyList() {
  byId("levy-list-panel").hidden = false;
  byId("levy-detail-panel").hidden = true;
  state.levy = null;
}

async function openLevy(id) {
  try {
    const data = await apiRequest("/chair/levies/" + id + "/", "GET");
    state.levy = data.levy;
    renderLevyDetail(data.levy, data.members);
    byId("levy-list-panel").hidden = true;
    byId("levy-detail-panel").hidden = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (err) {
    handleRequestError(err, "Could not load that special contribution.");
  }
}

function moneyReceived(levy) {
  return Number(levy.summary.collected) + Number(levy.summary.fines_collected) > 0;
}

function renderLevyDetail(levy, members) {
  const s = levy.summary;
  const active = levy.status === "active";
  const beforeDeadline = levy.deadline >= nairobiToday();

  setText("levy-title", levy.purpose);
  setText("levy-description", levy.description || "");

  const facts = byId("levy-facts");
  facts.innerHTML = "";
  [
    ["Status", levy.status_label],
    ["Amount per member", money(levy.amount)],
    ["Deadline", shortDate(levy.deadline)],
    ["Fine if late", levy.fine_label],
    ["Created by", levy.created_by_name || "—"],
  ].forEach(function ([label, value]) {
    const item = el("div");
    item.appendChild(el("span", label + ": "));
    item.appendChild(el("strong", value));
    facts.appendChild(item);
  });

  const cards = byId("levy-cards");
  cards.innerHTML = "";
  [
    ["Members", s.members, s.fully_paid + " paid in full", ""],
    ["Expected", money(s.expected), "", ""],
    ["Collected", money(s.collected), "", ""],
    ["Outstanding", money(s.outstanding), "", "accent"],
    ["Fines", money(s.fines_charged), money(s.fines_collected) + " collected", ""],
  ].forEach(function ([label, value, note, extra]) {
    const card = el("div", null, "card " + extra);
    card.appendChild(el("h3", label));
    card.appendChild(el("p", String(value), "big-number"));
    if (note) card.appendChild(el("p", note, "card-note"));
    cards.appendChild(card);
  });

  // Actions follow the same rules the server enforces.
  byId("levy-edit").hidden = !(active && beforeDeadline);
  byId("levy-close").hidden = !active;
  byId("levy-cancel").hidden = !(active && !moneyReceived(levy));

  const body = document.querySelector("#levy-members-table tbody");
  body.innerHTML = "";
  byId("no-levy-members").hidden = members.length > 0;

  members.forEach(function (m) {
    const tr = document.createElement("tr");
    const name = cell(tr, m.name, "strong");
    name.appendChild(el("span", m.username + (m.phone ? " · " + m.phone : ""), "sub-note"));
    cell(tr, money(m.amount_due), "num");
    cell(tr, money(m.amount_paid), "num");
    cell(tr, money(m.balance), "num");
    cell(tr, m.fine_waived ? "Waived" : (Number(m.fine_amount) > 0 ? money(m.fine_amount) : "—"), "num");
    cell(tr, Number(m.fine_amount) > 0 ? money(m.fine_amount_paid) : "—", "num");
    cell(tr, badge(m.status_label, m.status));
    body.appendChild(tr);
  });
}

// ----- Create and edit ------------------------------------------------------

function updateFineLabel() {
  const fixed = byId("levy-fine-type").value === "fixed";
  setText("levy-fine-label", fixed ? "Fine (KES)" : "Fine (%)");
  byId("levy-fine-value").step = fixed ? "1" : "0.5";
}

function openLevyModal(levy) {
  const form = byId("levy-form");
  form.reset();
  state.editingLevyId = levy ? levy.id : null;

  setText("levy-modal-title", levy ? "Edit Special Contribution" : "New Special Contribution");
  setText("levy-save", levy ? "Save changes" : "Create");
  byId("levy-deadline").min = nairobiToday();

  const amountInput = byId("levy-amount");
  amountInput.disabled = false;
  setText("levy-amount-hint", "");

  if (levy) {
    byId("levy-purpose").value = levy.purpose;
    byId("levy-description-input").value = levy.description || "";
    amountInput.value = Math.round(Number(levy.amount));
    byId("levy-deadline").value = levy.deadline;
    byId("levy-fine-type").value = levy.fine_type;
    byId("levy-fine-value").value = Number(levy.fine_value);
    if (moneyReceived(levy)) {
      amountInput.disabled = true;
      setText("levy-amount-hint", "Locked: members have already paid toward it.");
    }
  } else {
    byId("levy-fine-type").value = "percent";
    byId("levy-fine-value").value = 10;
  }

  updateFineLabel();
  openModal("levy-modal");
}

async function submitLevy(event) {
  event.preventDefault();
  const modal = byId("levy-modal");
  clearErrors(modal);

  const body = {
    purpose: byId("levy-purpose").value.trim(),
    description: byId("levy-description-input").value.trim(),
    deadline: byId("levy-deadline").value,
    fine_type: byId("levy-fine-type").value,
    fine_value: byId("levy-fine-value").value || "0",
  };
  if (!byId("levy-amount").disabled) body.amount = byId("levy-amount").value;

  if (!body.purpose) { setText("levy-error-purpose", "Give the reason for this contribution."); return; }
  if (!byId("levy-amount").disabled && !(Number(body.amount) >= 1)) {
    setText("levy-error-amount", "Enter an amount of at least KES 1.");
    return;
  }
  if (!body.deadline) { setText("levy-error-deadline", "Choose the deadline."); return; }

  const editing = state.editingLevyId;
  const btn = byId("levy-save");
  setBusy(btn, true, editing ? "Saving..." : "Creating...");
  try {
    const saved = editing
      ? await apiRequest("/chair/levies/" + editing + "/", "PATCH", body)
      : await apiRequest("/chair/levies/", "POST", body);
    closeModal("levy-modal");
    showNotice(
      editing
        ? "Special contribution updated."
        : "Special contribution created. " + saved.summary.members + " member(s) now owe it."
    );
    await loadLevies();
    if (editing) openLevy(editing);
  } catch (err) {
    if (err.status === 401) { goToLogin(); return; }
    showFieldErrors(err.data, "levy-error-", "levy-error");
  } finally {
    setBusy(btn, false);
  }
}

// ----- Close and cancel ------------------------------------------------------

function confirmCloseLevy() {
  const levy = state.levy;
  askConfirm(
    "Close Special Contribution",
    "Close \"" + levy.purpose + "\"? No new members will owe it and no fines will be charged. " +
      "Amounts members already owe stay owed.",
    "Close it",
    async function () {
      await apiRequest("/chair/levies/" + levy.id + "/close/", "POST");
      showNotice("\"" + levy.purpose + "\" has been closed.");
      await loadLevies();
      openLevy(levy.id);
    }
  );
}

function confirmCancelLevy() {
  const levy = state.levy;
  askConfirm(
    "Cancel Special Contribution",
    "Cancel \"" + levy.purpose + "\"? Nobody has paid toward it, so members will no longer owe it. " +
      "It stays on record as cancelled.",
    "Cancel it",
    async function () {
      await apiRequest("/chair/levies/" + levy.id + "/cancel/", "POST");
      showNotice("\"" + levy.purpose + "\" has been cancelled.");
      await loadLevies();
      openLevy(levy.id);
    }
  );
}


// ===========================================================================
// Start
// ===========================================================================

if (guardPage()) {
  setText("welcome", "Hello, " + (localStorage.getItem("username") || ""));
  byId("logout-btn").addEventListener("click", logout);

  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () { switchTab(tab.dataset.tab); });
  });

  // Accounts
  document.querySelectorAll(".segmented button").forEach(function (b) {
    b.addEventListener("click", function () { setGroup(b.dataset.group); });
  });
  byId("account-search").addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadAccounts, 300);
  });
  byId("new-staff-btn").addEventListener("click", openStaffModal);
  byId("staff-form").addEventListener("submit", submitStaff);
  byId("deactivate-form").addEventListener("submit", submitDeactivate);

  // Settings
  byId("settings-form").addEventListener("submit", submitSettings);

  // Special contributions
  byId("new-levy-btn").addEventListener("click", function () { openLevyModal(null); });
  byId("levy-form").addEventListener("submit", submitLevy);
  byId("levy-fine-type").addEventListener("change", updateFineLabel);
  byId("levy-back").addEventListener("click", function () { showLevyList(); loadLevies(); });
  byId("levy-edit").addEventListener("click", function () { openLevyModal(state.levy); });
  byId("levy-close").addEventListener("click", confirmCloseLevy);
  byId("levy-cancel").addEventListener("click", confirmCancelLevy);

  // Confirm dialog
  byId("confirm-yes").addEventListener("click", async function () {
    const btn = byId("confirm-yes");
    setBusy(btn, true, "Working...");
    try {
      await state.confirmAction();
      closeModal("confirm-modal");
    } catch (err) {
      if (err && err.status === 401) { goToLogin(); return; }
      setText("confirm-error", detailOf(err, "That did not work. Please try again."));
    } finally {
      setBusy(btn, false);
    }
  });

  // Every modal closes with its x, its Cancel button, the dark background or Escape.
  document.querySelectorAll(".overlay").forEach(function (overlay) {
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay || event.target.hasAttribute("data-close")) {
        overlay.hidden = true;
      }
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      document.querySelectorAll(".overlay").forEach(function (o) { o.hidden = true; });
    }
  });

  switchTab("accounts");
}