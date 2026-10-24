// ---------------------------------------------------------------------------
// secretary.js - monthly and special contribution lists. Needs api.js first.
// ---------------------------------------------------------------------------

const SACCO_NAME = "Nyikwa Abiya Welfare";

const OTHER_PAGES = {
  member: "../../member/dashboard.html",
  treasurer: "../treasurer/account_overview.html",
  chairperson: "../chairperson/settings.html",
};

const STATUS_TEXT = {
  paid: "Paid",
  partial: "Partial",
  unpaid: "Unpaid",
  overdue: "Overdue",
};

const PENALTY_TEXT = {
  paid: "Paid",
  "part-paid": "Part paid",
  unpaid: "Unpaid",
  waived: "Waived",
};

let yearsData = [];        // [{year, months: [{month, name, label}]}]
let monthData = null;      // the loaded month's full response
let visibleMembers = [];   // members after the search filter
let requestCounter = 0;    // ignores late answers when months change quickly

// Special contributions
let leviesLoaded = false;
let leviesList = [];
let currentLevy = null;        // {levy, members}
let levyVisibleMembers = [];
let levyRequestCounter = 0;


// ----- Small helpers -------------------------------------------------------

function money(value) {
  const n = Number(value || 0);
  return "KES " + n.toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function shortDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-KE", {
    day: "numeric", month: "short", year: "numeric",
  });
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function cell(row, content, className) {
  const td = el("td", null, className);
  if (content instanceof Node) {
    td.appendChild(content);
  } else {
    td.textContent = content;
  }
  row.appendChild(td);
  return td;
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function showWarning(message) {
  setText("warning-message", message || "");
}

function sum(rows, pick) {
  return rows.reduce(function (total, row) { return total + Number(pick(row) || 0); }, 0);
}


// ----- Page guard ----------------------------------------------------------

function guardPage() {
  if (!getAccessToken()) {
    goToLogin();
    return false;
  }
  const role = getRole();
  if (role && role !== "secretary") {
    window.location.href = OTHER_PAGES[role] || "../../login.html";
    return false;
  }
  return true;
}

function handleRequestError(err, fallback) {
  if (err.status === 401) {
    goToLogin();
    return;
  }
  if (err.status === 403) {
    showWarning("This page is for the secretary only.");
    return;
  }
  showWarning((err.data && err.data.detail) || fallback);
}


// ----- Tabs ----------------------------------------------------------------

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  document.getElementById("tab-monthly").hidden = name !== "monthly";
  document.getElementById("tab-special").hidden = name !== "special";
  showWarning("");

  if (name === "special" && !leviesLoaded) {
    leviesLoaded = true;
    loadLevyChoices();
  }
}


// ----- Year and month dropdowns --------------------------------------------

async function loadMonthChoices() {
  let data;
  try {
    data = await apiRequest("/contributions/secretary/months/", "GET");
  } catch (err) {
    handleRequestError(err, "Could not load the list of months.");
    return;
  }

  yearsData = data.years || [];
  if (!yearsData.length) {
    setText("month-title", "No months on record yet");
    return;
  }

  const fromUrl = new URLSearchParams(window.location.search).get("month");
  const wanted = findMonth(fromUrl) ? fromUrl : data.current;

  const yearSelect = document.getElementById("year-select");
  yearSelect.innerHTML = "";
  yearsData.forEach(function (y) {
    yearSelect.appendChild(new Option(String(y.year), String(y.year)));
  });

  yearSelect.value = wanted.slice(0, 4);
  fillMonthSelect(yearSelect.value, wanted);
  loadMonth(document.getElementById("month-select").value);
}

function findMonth(monthIso) {
  if (!monthIso) return null;
  for (const y of yearsData) {
    const hit = y.months.find(function (m) { return m.month === monthIso; });
    if (hit) return hit;
  }
  return null;
}

function fillMonthSelect(year, preferredMonth) {
  const monthSelect = document.getElementById("month-select");
  const entry = yearsData.find(function (y) { return String(y.year) === String(year); });
  monthSelect.innerHTML = "";
  if (!entry) return;

  entry.months.forEach(function (m) {
    monthSelect.appendChild(new Option(m.name, m.month));
  });

  const hasPreferred = entry.months.some(function (m) { return m.month === preferredMonth; });
  monthSelect.value = hasPreferred ? preferredMonth : entry.months[0].month;
}


// ----- Loading one month ---------------------------------------------------

async function loadMonth(monthIso) {
  if (!monthIso) return;
  const requestId = ++requestCounter;

  setText("month-title", "Loading...");
  showWarning("");

  const url = new URL(window.location.href);
  url.searchParams.set("month", monthIso);
  window.history.replaceState(null, "", url);

  let data;
  try {
    data = await apiRequest("/contributions/secretary/month/?month=" + monthIso, "GET");
  } catch (err) {
    if (requestId !== requestCounter) return;
    handleRequestError(err, "Could not load this month's list.");
    return;
  }
  if (requestId !== requestCounter) return;

  monthData = data;
  renderMonth();
}

function renderMonth() {
  const data = monthData;
  const summary = data.summary;

  setText("month-title", data.label);
  const tag = document.getElementById("month-tag");
  tag.hidden = false;
  tag.textContent = data.is_current ? "Open: payments still coming in" : "Closed";
  tag.className = "month-tag " + (data.is_current ? "open" : "closed");

  document.getElementById("summary-cards").hidden = false;
  setText("sum-members", String(summary.members_count));
  setText(
    "sum-members-note",
    summary.fully_paid_count + " fully paid, " +
      summary.partial_count + " partial, " +
      summary.unpaid_count + " not paid"
  );
  setText("sum-expected", money(summary.expected));
  setText("sum-collected", money(summary.collected));
  setText("sum-outstanding", money(summary.outstanding));
  setText("sum-pen-charged", money(summary.penalties_charged));
  setText(
    "sum-pen-note",
    summary.waived_penalties_count
      ? summary.waived_penalties_count + " waived, not counted"
      : (data.is_current ? "Charged after the month ends" : "")
  );
  setText("sum-pen-collected", money(summary.penalties_collected));
  setText("sum-total", money(summary.total_collected));

  document.getElementById("list-panel").hidden = false;
  applySearch();
}


// ----- Search and table (monthly) ------------------------------------------

function applySearch() {
  if (!monthData) return;
  const term = document.getElementById("search-input").value.trim().toLowerCase();

  visibleMembers = monthData.members.filter(function (m) {
    if (!term) return true;
    return (
      m.name.toLowerCase().includes(term) ||
      m.username.toLowerCase().includes(term) ||
      (m.phone || "").includes(term)
    );
  });

  renderTable(visibleMembers, term);
}

function contributionStatusCell(member) {
  const wrap = document.createElement("span");
  if (member.fully_paid) {
    wrap.appendChild(el("span", "✔", "tick"));
  }
  wrap.appendChild(el("span", STATUS_TEXT[member.status] || member.status, "badge badge-" + member.status));
  if (!member.fully_paid && Number(member.amount_paid) > 0) {
    wrap.appendChild(el("span", money(member.balance) + " owing", "sub-note"));
  }
  return wrap;
}

function penaltyStatusCell(penalty) {
  const wrap = document.createElement("span");
  const kind = penalty.state === "part-paid" ? "partial"
    : penalty.state === "unpaid" ? "overdue"
    : penalty.state;
  wrap.appendChild(el("span", PENALTY_TEXT[penalty.state] || penalty.state, "badge badge-" + kind));
  if (penalty.state === "waived" && penalty.waived_reason) {
    wrap.appendChild(el("span", penalty.waived_reason, "sub-note"));
  } else if (penalty.state === "part-paid") {
    wrap.appendChild(el("span", money(penalty.balance) + " owing", "sub-note"));
  }
  return wrap;
}

function renderTable(rows, term) {
  const body = document.querySelector("#members-table tbody");
  const foot = document.querySelector("#members-table tfoot");
  body.innerHTML = "";
  foot.innerHTML = "";

  const total = monthData.members.length;
  document.getElementById("no-members").hidden = total !== 0;
  document.getElementById("no-results").hidden = !(total > 0 && rows.length === 0);

  setText(
    "showing-count",
    term ? "Showing " + rows.length + " of " + total + " members" : total + " members"
  );

  rows.forEach(function (m, index) {
    const tr = document.createElement("tr");

    cell(tr, String(index + 1), "num");

    const nameCell = cell(tr, m.name, "member-name");
    nameCell.appendChild(el("span", m.username + (m.phone ? " · " + m.phone : ""), "sub-note"));

    cell(tr, money(m.amount_due), "num");
    cell(tr, money(m.amount_paid), "num");
    cell(tr, contributionStatusCell(m));

    if (m.penalty) {
      const waived = m.penalty.state === "waived";
      cell(tr, waived ? "—" : money(m.penalty.amount), "num group-start");
      cell(tr, waived ? "—" : money(m.penalty.amount_paid), "num");
      cell(tr, penaltyStatusCell(m.penalty));
    } else {
      cell(tr, "—", "num group-start");
      cell(tr, "—", "num");
      cell(tr, monthData.is_current ? "Not yet due" : "None");
    }

    cell(tr, money(m.total_paid), "num group-start");
    cell(tr, m.fully_paid ? shortDate(m.date_paid) : "—");

    body.appendChild(tr);
  });

  if (rows.length) {
    const penaltyRows = rows.filter(function (m) { return m.penalty && m.penalty.state !== "waived"; });
    const tr = document.createElement("tr");
    cell(tr, "");
    cell(tr, term ? "Total (shown)" : "Total");
    cell(tr, money(sum(rows, function (m) { return m.amount_due; })), "num");
    cell(tr, money(sum(rows, function (m) { return m.amount_paid; })), "num");
    cell(tr, "");
    cell(tr, money(sum(penaltyRows, function (m) { return m.penalty.amount; })), "num group-start");
    cell(tr, money(sum(penaltyRows, function (m) { return m.penalty.amount_paid; })), "num");
    cell(tr, "");
    cell(tr, money(sum(rows, function (m) { return m.total_paid; })), "num group-start");
    cell(tr, "");
    foot.appendChild(tr);
  }
}


// ----- Special contributions -----------------------------------------------

const LEVY_TAG = {
  active: ["Active", "open"],
  closed: ["Closed", "closed"],
  cancelled: ["Cancelled", "closed"],
};

async function loadLevyChoices() {
  let data;
  try {
    data = await apiRequest("/contributions/secretary/levies/", "GET");
  } catch (err) {
    handleRequestError(err, "Could not load the special contributions.");
    return;
  }

  leviesList = data.levies || [];
  const select = document.getElementById("levy-select");
  select.innerHTML = "";

  if (!leviesList.length) {
    setText("levy-title", "No special contributions yet");
    document.getElementById("levy-tag").hidden = true;
    document.getElementById("levy-sub").textContent = "";
    document.getElementById("levy-summary-cards").hidden = true;
    document.getElementById("levy-list-panel").hidden = true;
    document.getElementById("levy-none").hidden = false;
    return;
  }
  document.getElementById("levy-none").hidden = true;

  leviesList.forEach(function (lv) {
    select.appendChild(new Option(lv.purpose + " (" + lv.status_label + ")", String(lv.id)));
  });
  select.value = String(leviesList[0].id);
  loadLevy(select.value);
}

async function loadLevy(id) {
  if (!id) return;
  const requestId = ++levyRequestCounter;

  setText("levy-title", "Loading...");
  document.getElementById("levy-tag").hidden = true;
  showWarning("");

  let data;
  try {
    data = await apiRequest("/contributions/secretary/levies/" + id + "/", "GET");
  } catch (err) {
    if (requestId !== levyRequestCounter) return;
    handleRequestError(err, "Could not load this special contribution.");
    return;
  }
  if (requestId !== levyRequestCounter) return;

  currentLevy = data;
  renderLevy();
}

function renderLevy() {
  const levy = currentLevy.levy;
  const s = levy.summary;

  setText("levy-title", levy.purpose);

  const tag = document.getElementById("levy-tag");
  const pair = LEVY_TAG[levy.status] || [levy.status_label, "closed"];
  tag.hidden = false;
  tag.textContent = pair[0];
  tag.className = "month-tag " + pair[1];

  setText(
    "levy-sub",
    money(levy.amount) + " per member · Deadline " + shortDate(levy.deadline) +
      " · Fine if late: " + levy.fine_label +
      (levy.description ? " · " + levy.description : "")
  );

  document.getElementById("levy-summary-cards").hidden = false;
  setText("lsum-members", String(s.members));
  setText("lsum-members-note", s.fully_paid + " paid in full");
  setText("lsum-expected", money(s.expected));
  setText("lsum-collected", money(s.collected));
  setText("lsum-outstanding", money(s.outstanding));
  setText("lsum-fines-charged", money(s.fines_charged));
  setText("lsum-fines-collected", money(s.fines_collected));

  document.getElementById("levy-list-panel").hidden = false;
  applyLevySearch();
}

function applyLevySearch() {
  if (!currentLevy) return;
  const term = document.getElementById("levy-search-input").value.trim().toLowerCase();

  levyVisibleMembers = currentLevy.members.filter(function (m) {
    if (!term) return true;
    return (
      m.name.toLowerCase().includes(term) ||
      m.username.toLowerCase().includes(term) ||
      (m.phone || "").includes(term)
    );
  });

  renderLevyTable(levyVisibleMembers, term);
}

function levyFine(m) {
  return m.fine_waived ? "Waived" : (Number(m.fine_amount) > 0 ? money(m.fine_amount) : "—");
}

function levyFinePaid(m) {
  return (!m.fine_waived && Number(m.fine_amount) > 0) ? money(m.fine_amount_paid) : "—";
}

function renderLevyTable(rows, term) {
  const body = document.querySelector("#levy-members-table tbody");
  const foot = document.querySelector("#levy-members-table tfoot");
  body.innerHTML = "";
  foot.innerHTML = "";

  const total = currentLevy.members.length;
  document.getElementById("levy-no-members").hidden = total !== 0;
  document.getElementById("levy-no-results").hidden = !(total > 0 && rows.length === 0);

  setText(
    "levy-showing-count",
    term ? "Showing " + rows.length + " of " + total + " members" : total + " members"
  );

  rows.forEach(function (m, index) {
    const tr = document.createElement("tr");

    cell(tr, String(index + 1), "num");

    const nameCell = cell(tr, m.name, "member-name");
    nameCell.appendChild(el("span", m.username + (m.phone ? " · " + m.phone : ""), "sub-note"));

    cell(tr, money(m.amount_due), "num");
    cell(tr, money(m.amount_paid), "num");
    cell(tr, money(m.balance), "num");
    cell(tr, levyFine(m), "num group-start");
    cell(tr, levyFinePaid(m), "num");
    cell(tr, el("span", m.status_label, "badge badge-" + m.status));

    body.appendChild(tr);
  });

  if (rows.length) {
    const fined = rows.filter(function (m) { return !m.fine_waived && Number(m.fine_amount) > 0; });
    const tr = document.createElement("tr");
    cell(tr, "");
    cell(tr, term ? "Total (shown)" : "Total");
    cell(tr, money(sum(rows, function (m) { return m.amount_due; })), "num");
    cell(tr, money(sum(rows, function (m) { return m.amount_paid; })), "num");
    cell(tr, money(sum(rows, function (m) { return m.balance; })), "num");
    cell(tr, money(sum(fined, function (m) { return m.fine_amount; })), "num group-start");
    cell(tr, money(sum(fined, function (m) { return m.fine_amount_paid; })), "num");
    cell(tr, "");
    foot.appendChild(tr);
  }
}


// ----- Print ---------------------------------------------------------------

function preparePrint() {
  if (!monthData) return;
  const term = document.getElementById("search-input").value.trim();
  setText(
    "print-month",
    monthData.label + (term ? " (filtered: \"" + term + "\")" : "") +
      (monthData.is_current ? ", month still open" : "")
  );
  setText("print-date", "Printed " + new Date().toLocaleString("en-KE"));
}

function printList() {
  if (!monthData) return;
  preparePrint();
  window.print();
}

function prepareLevyPrint() {
  if (!currentLevy) return;
  const levy = currentLevy.levy;
  const term = document.getElementById("levy-search-input").value.trim();
  setText(
    "levy-print-name",
    levy.purpose + " · " + levy.status_label + (term ? " (filtered: \"" + term + "\")" : "")
  );
  setText("levy-print-date", "Printed " + new Date().toLocaleString("en-KE"));
}

function printLevy() {
  if (!currentLevy) return;
  prepareLevyPrint();
  window.print();
}


// ----- CSV download --------------------------------------------------------

function csvField(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

function csvRow(values) {
  return values.map(csvField).join(",");
}

function plainNumber(value) {
  return Number(value || 0).toFixed(2);
}

function saveCsv(lines, filename) {
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function downloadCsv() {
  if (!monthData) return;
  const term = document.getElementById("search-input").value.trim();
  const rows = visibleMembers;
  const s = monthData.summary;

  const lines = [
    csvRow([SACCO_NAME + ": Monthly Contribution List"]),
    csvRow(["Month", monthData.label + (monthData.is_current ? " (open)" : " (closed)")]),
    csvRow(["Generated", new Date().toLocaleString("en-KE")]),
  ];
  if (term) lines.push(csvRow(["Filtered by", term]));
  lines.push("");

  lines.push(csvRow([
    "#", "Member", "Username", "Phone",
    "Due (KES)", "Paid (KES)", "Balance (KES)", "Contribution Status", "Fully Paid On",
    "Penalty (KES)", "Penalty Paid (KES)", "Penalty Status",
    "Total Paid (KES)",
  ]));

  rows.forEach(function (m, index) {
    const p = m.penalty;
    const waived = p && p.state === "waived";
    lines.push(csvRow([
      index + 1,
      m.name,
      m.username,
      m.phone,
      plainNumber(m.amount_due),
      plainNumber(m.amount_paid),
      plainNumber(m.balance),
      STATUS_TEXT[m.status] || m.status,
      m.fully_paid && m.date_paid ? m.date_paid.slice(0, 10) : "",
      p && !waived ? plainNumber(p.amount) : "",
      p && !waived ? plainNumber(p.amount_paid) : "",
      p ? (PENALTY_TEXT[p.state] || p.state) + (waived && p.waived_reason ? ": " + p.waived_reason : "") : "",
      plainNumber(m.total_paid),
    ]));
  });

  lines.push("");
  if (term) {
    lines.push(csvRow(["Totals below cover the whole month, not only the filtered rows."]));
  }
  lines.push(csvRow(["Members", s.members_count]));
  lines.push(csvRow(["Fully paid", s.fully_paid_count]));
  lines.push(csvRow(["Partial", s.partial_count]));
  lines.push(csvRow(["Not paid", s.unpaid_count]));
  lines.push(csvRow(["Contributions expected (KES)", plainNumber(s.expected)]));
  lines.push(csvRow(["Contributions collected (KES)", plainNumber(s.collected)]));
  lines.push(csvRow(["Still outstanding (KES)", plainNumber(s.outstanding)]));
  lines.push(csvRow(["Penalties charged (KES)", plainNumber(s.penalties_charged)]));
  lines.push(csvRow(["Penalties collected (KES)", plainNumber(s.penalties_collected)]));
  lines.push(csvRow(["Total received (KES)", plainNumber(s.total_collected)]));

  saveCsv(lines, "contributions_" + monthData.month.slice(0, 7) + ".csv");
}

function downloadLevyCsv() {
  if (!currentLevy) return;
  const levy = currentLevy.levy;
  const s = levy.summary;
  const term = document.getElementById("levy-search-input").value.trim();
  const rows = levyVisibleMembers;

  const lines = [
    csvRow([SACCO_NAME + ": Special Contribution List"]),
    csvRow(["Contribution", levy.purpose]),
    csvRow(["Status", levy.status_label]),
    csvRow(["Amount per member (KES)", plainNumber(levy.amount)]),
    csvRow(["Deadline", levy.deadline]),
    csvRow(["Fine if late", levy.fine_label]),
    csvRow(["Generated", new Date().toLocaleString("en-KE")]),
  ];
  if (term) lines.push(csvRow(["Filtered by", term]));
  lines.push("");

  lines.push(csvRow([
    "#", "Member", "Username", "Phone",
    "Due (KES)", "Paid (KES)", "Balance (KES)",
    "Fine (KES)", "Fine Paid (KES)", "Status",
  ]));

  rows.forEach(function (m, index) {
    lines.push(csvRow([
      index + 1,
      m.name,
      m.username,
      m.phone,
      plainNumber(m.amount_due),
      plainNumber(m.amount_paid),
      plainNumber(m.balance),
      m.fine_waived ? "Waived" : plainNumber(m.fine_amount),
      (!m.fine_waived && Number(m.fine_amount) > 0) ? plainNumber(m.fine_amount_paid) : "",
      m.status_label,
    ]));
  });

  lines.push("");
  if (term) {
    lines.push(csvRow(["Totals below cover the whole contribution, not only the filtered rows."]));
  }
  lines.push(csvRow(["Members", s.members]));
  lines.push(csvRow(["Paid in full", s.fully_paid]));
  lines.push(csvRow(["Expected (KES)", plainNumber(s.expected)]));
  lines.push(csvRow(["Collected (KES)", plainNumber(s.collected)]));
  lines.push(csvRow(["Outstanding (KES)", plainNumber(s.outstanding)]));
  lines.push(csvRow(["Fines charged (KES)", plainNumber(s.fines_charged)]));
  lines.push(csvRow(["Fines collected (KES)", plainNumber(s.fines_collected)]));

  const safe = (levy.purpose || "levy").replace(/[^a-z0-9]+/gi, "_").toLowerCase().slice(0, 40);
  saveCsv(lines, "special_" + safe + ".csv");
}


// ----- Start ---------------------------------------------------------------

if (guardPage()) {
  setText("welcome", "Hello, " + (localStorage.getItem("username") || ""));

  document.getElementById("logout-btn").addEventListener("click", logout);

  // Tabs
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () { switchTab(tab.dataset.tab); });
  });

  // Monthly
  document.getElementById("year-select").addEventListener("change", function (e) {
    fillMonthSelect(e.target.value, null);
    loadMonth(document.getElementById("month-select").value);
  });
  document.getElementById("month-select").addEventListener("change", function (e) {
    loadMonth(e.target.value);
  });
  document.getElementById("search-input").addEventListener("input", applySearch);
  document.getElementById("print-btn").addEventListener("click", printList);
  document.getElementById("download-btn").addEventListener("click", downloadCsv);

  // Special contributions
  document.getElementById("levy-select").addEventListener("change", function (e) {
    loadLevy(e.target.value);
  });
  document.getElementById("levy-search-input").addEventListener("input", applyLevySearch);
  document.getElementById("levy-print-btn").addEventListener("click", printLevy);
  document.getElementById("levy-download-btn").addEventListener("click", downloadLevyCsv);

  // Print the tab that is open
  window.addEventListener("beforeprint", function () {
    if (!document.getElementById("tab-special").hidden) prepareLevyPrint();
    else preparePrint();
  });

  loadMonthChoices();
}