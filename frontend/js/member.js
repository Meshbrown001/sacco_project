// Runs when the member dashboard loads.

async function loadDashboard() {
  const errorBox = document.getElementById("error-message");

  // No token means the person is not logged in. Send them to login.
  if (!getAccessToken()) {
    window.location.href = "../login.html";
    return;
  }

  try {
    const data = await apiRequest("/contributions/dashboard/", "GET");

    document.getElementById("welcome").textContent = "Hello, " + data.username;
    document.getElementById("wallet-balance").textContent =
      "KES " + data.wallet.balance;
    document.getElementById("monthly-amount").textContent =
      "KES " + data.current_monthly_amount;

    const debt = data.debt_summary;
    document.getElementById("total-owed").textContent =
      "KES " + debt.total_owed;
    document.getElementById("debt-detail").textContent =
      debt.overdue_months_count +
      " overdue month(s): KES " +
      debt.contribution_debt +
      " in contributions plus KES " +
      debt.penalty_debt +
      " in penalties.";

    fillContributions(data.contributions);
    fillPenalties(data.penalties);
  } catch (err) {
    // An expired or invalid token returns 401. Send them to log in again.
    if (err.status === 401) {
      window.location.href = "../login.html";
      return;
    }
    errorBox.textContent = "Could not load your dashboard. Please try again.";
  }
}

function fillContributions(rows) {
  const body = document.querySelector("#contributions-table tbody");
  const emptyNote = document.getElementById("no-contributions");
  body.innerHTML = "";

  if (!rows || rows.length === 0) {
    emptyNote.style.display = "block";
    return;
  }
  emptyNote.style.display = "none";

  rows.forEach(function (row) {
    const tr = document.createElement("tr");
    const datePaid = row.date_paid ? row.date_paid.substring(0, 10) : "—";
    tr.innerHTML =
      "<td>" + row.month_label + "</td>" +
      "<td>KES " + row.amount_paid + "</td>" +
      "<td>" + datePaid + "</td>" +
      "<td class='status-" + row.status + "'>" + row.status + "</td>";
    body.appendChild(tr);
  });
}

function fillPenalties(rows) {
  const body = document.querySelector("#penalties-table tbody");
  const emptyNote = document.getElementById("no-penalties");
  body.innerHTML = "";

  if (!rows || rows.length === 0) {
    emptyNote.style.display = "block";
    return;
  }
  emptyNote.style.display = "none";

  rows.forEach(function (row) {
    const tr = document.createElement("tr");
    const dateCharged = row.date_charged ? row.date_charged.substring(0, 10) : "—";
    const statusText = row.paid ? "paid" : "unpaid";
    tr.innerHTML =
      "<td>" + row.month_label + "</td>" +
      "<td>KES " + row.amount + "</td>" +
      "<td>" + dateCharged + "</td>" +
      "<td class='status-" + statusText + "'>" + statusText + "</td>";
    body.appendChild(tr);
  });
}

document.getElementById("logout-btn").addEventListener("click", logout);

loadDashboard();