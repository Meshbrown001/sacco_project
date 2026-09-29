// ---------------------------------------------------------------------------
// member.js - member dashboard. Needs api.js loaded first.
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 4000;     // check the payment every 4 seconds
const POLL_LIMIT_MS = 150000;      // stop waiting after 2.5 minutes

const STAFF_PAGES = {
  secretary: "../staff/secretary/monthly_lists.html",
  treasurer: "../staff/treasurer/account_overview.html",
  chairperson: "../staff/chairperson/settings.html",
};

let dashboardData = null;


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

function dateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-KE", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// 254712345678 -> 0712345678, the way members write their numbers.
function localPhone(phone) {
  if (!phone) return "";
  return phone.startsWith("254") ? "0" + phone.slice(3) : phone;
}

// Builds an element with plain text, so server data can never inject HTML.
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function badge(text, kind) {
  return el("span", text, "badge badge-" + kind);
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

function showError(message) {
  setText("error-message", message || "");
}

function showNotice(message) {
  setText("notice-message", message || "");
}

function capitalise(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function fillTable(tableId, emptyId, rows, buildRow) {
  const body = document.querySelector("#" + tableId + " tbody");
  const emptyNote = document.getElementById(emptyId);
  body.innerHTML = "";
  if (!rows || rows.length === 0) {
    emptyNote.hidden = false;
    return;
  }
  emptyNote.hidden = true;
  rows.forEach(function (item) {
    const tr = document.createElement("tr");
    buildRow(tr, item);
    body.appendChild(tr);
  });
}


// ----- Page guard ----------------------------------------------------------

// Sends people who are not logged in, or not members, to the right place.
// The backend enforces this too; the guard only saves a wasted trip.
function guardPage() {
  if (!getAccessToken()) {
    goToLogin();
    return false;
  }
  const role = getRole();
  if (role && role !== "member") {
    window.location.href = STAFF_PAGES[role] || "../login.html";
    return false;
  }
  return true;
}


// ----- Loading and drawing the dashboard -----------------------------------

async function loadDashboard() {
  try {
    const data = await apiRequest("/contributions/dashboard/", "GET");
    dashboardData = data;
    showError("");
    render(data);
  } catch (err) {
    if (err.status === 401) {
      goToLogin();
      return;
    }
    if (err.status === 403 && err.data && err.data.role) {
      window.location.href = STAFF_PAGES[err.data.role] || "../login.html";
      return;
    }
    showError((err.data && err.data.detail) || "Could not load your dashboard. Please try again.");
  }
}

function render(data) {
  setText("welcome", "Hello, " + (data.full_name || data.username));
  renderCards(data);
  renderBreakdown(data.debt_breakdown, data.debt_summary);
  renderLevies(data.special_contributions || []);
  renderContributions(data.contributions);
  renderPenalties(data.penalties, data.penalty_rate);
  renderPayments(data.recent_payments);
}

function renderCards(data) {
  const summary = data.debt_summary;
  const owed = Number(summary.total_owed);
  const monthlyOwed = Number(summary.monthly_owed || 0);
  const specialOwed = Number(summary.special_contributions_debt || 0);
  const owedCard = document.getElementById("owed-card");

  setText("total-owed", money(owed));
  owedCard.classList.toggle("attention", owed > 0);
  owedCard.classList.toggle("clear", owed <= 0);

  if (owed > 0) {
    const parts = [];
    if (monthlyOwed > 0) parts.push(money(monthlyOwed) + " monthly");
    if (specialOwed > 0) parts.push(money(specialOwed) + " special contributions");

    const late = data.debt_breakdown.filter(function (row) { return !row.is_current; });
    if (late.length) {
      parts.push("oldest late month: " + late[0].month_label);
    } else if (monthlyOwed > 0 && data.current_month) {
      parts.push("month due by the end of " + data.current_month.month_label);
    }
    setText("owed-note", parts.length ? capitalise(parts.join(", ")) + "." : "");
  } else {
    setText("owed-note", "You are fully paid up.");
  }

  const current = data.current_month;
  if (current) {
    setText("month-title", current.month_label);
    setText("month-balance", money(current.balance));
    setText(
      "month-note",
      current.status_label + ": " + money(current.amount_paid) + " paid of " + money(current.amount_due) + "."
    );
  } else {
    setText("month-title", "This Month");
    setText("month-balance", money(0));
    setText("month-note", "");
  }

  setText("wallet-credit", money(summary.wallet_credit));
  setText("penalty-total", money(summary.penalty_debt));
  setText("penalty-rule", Number(data.penalty_rate) + "% of the contribution per late month.");
}

function renderBreakdown(rows, summary) {
  const foot = document.querySelector("#breakdown-table tfoot");
  foot.innerHTML = "";

  fillTable("breakdown-table", "no-debt", rows, function (tr, row) {
    const monthCell = cell(tr, row.month_label);
    if (row.is_current) {
      monthCell.appendChild(el("span", "This month, not yet late", "sub-note"));
    }
    cell(tr, money(row.contribution_balance), "num");
    cell(tr, Number(row.penalty_balance) > 0 ? money(row.penalty_balance) : "—", "num");
    cell(tr, money(row.total), "num");
  });

  if (rows && rows.length) {
    const tr = document.createElement("tr");
    cell(tr, "Total owed");
    cell(tr, money(summary.contribution_debt), "num");
    cell(tr, money(summary.penalty_debt), "num");
    cell(tr, money(summary.monthly_owed || summary.total_owed), "num owed");
    foot.appendChild(tr);
  }
}

const STATUS_BADGES = {
  paid: "green",
  partial: "orange",
  unpaid: "grey",
  overdue: "dark",
};

function renderLevies(rows) {
  fillTable("levies-table", "no-levies", rows, function (tr, row) {
    const reasonCell = cell(tr, row.purpose, "levy-reason");
    if (row.levy_status === "closed") {
      reasonCell.appendChild(el("span", "Closed", "tag-closed"));
    }
    if (row.description) {
      reasonCell.appendChild(el("span", row.description, "sub-note"));
    }

    cell(tr, shortDate(row.deadline));
    cell(tr, money(row.amount_due), "num");
    cell(tr, money(row.amount_paid), "num");

    // Fine: the rule before the deadline, then what was charged.
    const fineCell = document.createElement("span");
    if (row.fine_waived) {
      fineCell.appendChild(badge("Waived", "grey"));
      if (row.fine_waived_reason) fineCell.appendChild(el("span", row.fine_waived_reason, "sub-note"));
    } else if (Number(row.fine_amount) > 0) {
      fineCell.appendChild(document.createTextNode(money(row.fine_amount)));
      fineCell.appendChild(el("span", money(row.fine_amount_paid) + " paid", "sub-note"));
    } else {
      fineCell.appendChild(el("span", "If late: " + row.fine_label, "sub-note"));
    }
    cell(tr, fineCell);

    cell(tr, money(row.total_owed), "num");
    cell(tr, badge(row.status_label, STATUS_BADGES[row.status] || "grey"));

    const actionCell = cell(tr, "");
    if (Number(row.total_owed) > 0) {
      const button = el("button", "Pay", "btn btn-pay btn-small");
      button.type = "button";
      button.addEventListener("click", function () { openPaymentPanel(String(row.id)); });
      actionCell.appendChild(button);
    }
  });
}

function renderContributions(rows) {
  fillTable("contributions-table", "no-contributions", rows, function (tr, row) {
    cell(tr, row.month_label);
    cell(tr, money(row.amount_due), "num");
    cell(tr, money(row.amount_paid), "num");
    cell(tr, money(row.balance), "num");
    cell(tr, badge(row.status_label, STATUS_BADGES[row.status] || "grey"));
  });
}

const PENALTY_BADGES = {
  paid: ["Paid", "green"],
  "part-paid": ["Part paid", "orange"],
  unpaid: ["Unpaid", "dark"],
  waived: ["Waived", "grey"],
};

function renderPenalties(rows, rate) {
  setText(
    "penalty-explainer",
    "A month not fully paid by midnight on its last day gets one fine of " +
      Number(rate) + "% of that month's contribution."
  );

  fillTable("penalties-table", "no-penalties", rows, function (tr, row) {
    cell(tr, row.month_label);
    const reasonCell = cell(tr, row.reason);
    if (row.waived && row.waived_reason) {
      reasonCell.appendChild(el("span", row.waived_reason, "sub-note"));
    }
    cell(tr, money(row.amount), "num");
    cell(tr, money(row.amount_paid), "num");
    cell(tr, money(row.balance), "num");
    const [label, kind] = PENALTY_BADGES[row.state] || [row.state, "grey"];
    cell(tr, badge(label, kind));
  });
}

function renderPayments(rows) {
  fillTable("payments-table", "no-payments", rows, function (tr, row) {
    const ref = row.reference || "";
    cell(tr, dateTime(row.effective_at));
    cell(tr, money(row.amount), "num");
    // A payment confirmed by a status check waits for its receipt from the
    // callback. Members see a plain message, never the internal placeholder.
    cell(tr, ref.startsWith("CHK-") ? "Confirmed, receipt pending" : (ref || "—"));
    cell(tr, row.description || "");
  });
}


// ----- Payment panel -------------------------------------------------------

// "" means monthly contributions; otherwise the special contribution's id.
function fillPaymentTargets(selected) {
  const select = document.getElementById("pay-target");
  const summary = dashboardData.debt_summary;
  select.innerHTML = "";

  const monthlyOwed = Number(summary.monthly_owed || 0);
  select.appendChild(new Option(
    "Monthly contributions" + (monthlyOwed > 0 ? " (" + money(monthlyOwed) + " owing)" : ""),
    ""
  ));

  (dashboardData.special_contributions || []).forEach(function (levy) {
    if (Number(levy.total_owed) <= 0) return;
    select.appendChild(new Option(
      levy.purpose + " (" + money(levy.total_owed) + " owing)",
      String(levy.id)
    ));
  });

  const exists = Array.from(select.options).some(function (o) { return o.value === selected; });
  select.value = exists ? selected : "";
}

function selectedLevy() {
  const value = document.getElementById("pay-target").value;
  if (!value) return null;
  return (dashboardData.special_contributions || []).find(function (levy) {
    return String(levy.id) === value;
  }) || null;
}

function updateAmountForTarget() {
  const amountInput = document.getElementById("pay-amount");
  const levy = selectedLevy();

  if (levy) {
    amountInput.value = Math.ceil(Number(levy.total_owed));
    setText(
      "pay-amount-hint",
      "Prefilled with what you owe for " + levy.purpose + ". The fine, if any, is paid first. " +
        "Anything extra goes to your monthly contributions."
    );
    return;
  }

  const summary = dashboardData.debt_summary;
  const owed = Math.ceil(Number(summary.monthly_owed || 0));
  const monthly = Math.ceil(Number(dashboardData.current_monthly_amount || 0));
  amountInput.value = owed > 0 ? owed : (monthly || "");
  setText(
    "pay-amount-hint",
    owed > 0
      ? "Prefilled with your monthly debt of " + money(summary.monthly_owed) + ". You may pay less or more; extra becomes credit."
      : "You owe nothing on monthly contributions. Any amount becomes credit for coming months."
  );
}

function openPaymentPanel(target) {
  if (!dashboardData) return;

  fillPaymentTargets(typeof target === "string" ? target : "");
  updateAmountForTarget();

  document.getElementById("pay-phone").value = localPhone(dashboardData.phone_number);
  clearPaymentErrors();

  const status = document.getElementById("pay-status");
  if (!document.getElementById("pay-send").disabled) {
    status.hidden = true;
  }

  document.getElementById("pay-overlay").hidden = false;
  document.getElementById("pay-amount").focus();
}

function closePaymentPanel() {
  document.getElementById("pay-overlay").hidden = true;
}

function clearPaymentErrors() {
  ["amount", "phone_number"].forEach(function (field) {
    setText("error-" + field, "");
  });
  document.querySelectorAll("#pay-form input").forEach(function (input) {
    input.classList.remove("invalid");
  });
}

function setPayStatus(message, kind) {
  const status = document.getElementById("pay-status");
  status.textContent = message;
  status.className = "pay-status " + kind;
  status.hidden = false;
}

function setSending(isSending) {
  const button = document.getElementById("pay-send");
  button.disabled = isSending;
  button.textContent = isSending ? "Waiting for M-Pesa..." : "Send";
  document.getElementById("pay-target").disabled = isSending;
}

async function sendPayment(event) {
  event.preventDefault();
  clearPaymentErrors();

  const amountInput = document.getElementById("pay-amount");
  const phoneInput = document.getElementById("pay-phone");
  const amount = Number(amountInput.value);
  const levy = selectedLevy();

  if (!Number.isInteger(amount) || amount < 1) {
    setText("error-amount", "Enter a whole number of shillings, at least 1.");
    amountInput.classList.add("invalid");
    return;
  }
  if (amount > 250000) {
    setText("error-amount", "M-Pesa allows at most KES 250,000 per payment.");
    amountInput.classList.add("invalid");
    return;
  }
  if (!phoneInput.value.trim()) {
    setText("error-phone_number", "Enter the phone number to pay from.");
    phoneInput.classList.add("invalid");
    return;
  }

  const body = { amount: amount, phone_number: phoneInput.value.trim() };
  if (levy) body.levy_obligation_id = levy.id;

  setSending(true);
  setPayStatus("Sending the request to M-Pesa...", "waiting");

  try {
    const result = await apiRequest("/payments/mpesa/stk-push/", "POST", body);
    setPayStatus(
      "Check your phone and enter your M-Pesa PIN to pay " + money(amount) +
        (levy ? " toward " + levy.purpose : "") + ".",
      "waiting"
    );
    pollPayment(result.transaction.id, Date.now());
  } catch (err) {
    setSending(false);
    const data = (err && err.data) || {};
    let placed = false;
    ["amount", "phone_number"].forEach(function (field) {
      if (data[field]) {
        setText("error-" + field, [].concat(data[field]).join(" "));
        document.getElementById(field === "amount" ? "pay-amount" : "pay-phone").classList.add("invalid");
        placed = true;
      }
    });
    setPayStatus(
      data.detail || (placed ? "Please correct the fields above." : "The payment could not start. Please try again."),
      "error"
    );
  }
}

async function pollPayment(transactionId, startedAt) {
  if (Date.now() - startedAt > POLL_LIMIT_MS) {
    setSending(false);
    setPayStatus(
      "M-Pesa has not confirmed yet. If you entered your PIN, the payment will show here once it arrives.",
      "waiting"
    );
    return;
  }

  let tx;
  try {
    tx = await apiRequest("/payments/status/" + transactionId + "/", "GET");
  } catch (err) {
    if (err.status === 401) {
      goToLogin();
      return;
    }
    setTimeout(function () { pollPayment(transactionId, startedAt); }, POLL_INTERVAL_MS);
    return;
  }

  if (tx.status === "pending") {
    setTimeout(function () { pollPayment(transactionId, startedAt); }, POLL_INTERVAL_MS);
    return;
  }

  setSending(false);

  if (tx.status === "success") {
    const receipt = tx.mpesa_receipt ? " Receipt " + tx.mpesa_receipt + "." : "";
    setPayStatus(tx.message + receipt, "success");
    showNotice("Payment of " + money(tx.amount) + " for " + tx.paying_for + " received." + receipt);
    await loadDashboard();
  } else {
    setPayStatus(tx.message, "error");
  }
}


// ----- Start ---------------------------------------------------------------

if (guardPage()) {
  document.getElementById("logout-btn").addEventListener("click", logout);
  document.getElementById("pay-btn").addEventListener("click", function () { openPaymentPanel(""); });
  document.getElementById("pay-close").addEventListener("click", closePaymentPanel);
  document.getElementById("pay-form").addEventListener("submit", sendPayment);
  document.getElementById("pay-target").addEventListener("change", updateAmountForTarget);

  // Close the panel by clicking the dark background or pressing Escape.
  document.getElementById("pay-overlay").addEventListener("click", function (event) {
    if (event.target.id === "pay-overlay") closePaymentPanel();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closePaymentPanel();
  });

  document.querySelectorAll("#pay-form input").forEach(function (input) {
    input.addEventListener("input", function () {
      input.classList.remove("invalid");
    });
  });

  loadDashboard();
}