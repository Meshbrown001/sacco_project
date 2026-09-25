// Secretary monthly lists page.

async function init() {
  if (!getAccessToken()) {
    window.location.href = "../../login.html";
    return;
  }

  const welcome = document.getElementById("welcome");
  welcome.textContent = "Hello, " + (localStorage.getItem("username") || "");

  await loadMonths();
}

async function loadMonths() {
  const picker = document.getElementById("month-picker");
  const noMonths = document.getElementById("no-months");
  const errorBox = document.getElementById("error-message");

  try {
    const data = await apiRequest("/contributions/secretary/months/", "GET");
    const months = data.months || [];

    if (months.length === 0) {
      noMonths.style.display = "block";
      return;
    }

    months.forEach(function (m) {
      const opt = document.createElement("option");
      opt.value = m.month;
      opt.textContent = m.label;
      picker.appendChild(opt);
    });
  } catch (err) {
    if (err.status === 401) {
      window.location.href = "../../login.html";
      return;
    }
    if (err.status === 403) {
      errorBox.textContent = "This page is for the secretary only.";
      return;
    }
    errorBox.textContent = "Could not load months. Please try again.";
  }
}

async function loadMonthDetail(month) {
  const errorBox = document.getElementById("error-message");
  const listSection = document.getElementById("list-section");
  const penaltySection = document.getElementById("penalty-section");

  if (!month) {
    listSection.style.display = "none";
    penaltySection.style.display = "none";
    return;
  }

  try {
    const data = await apiRequest(
      "/contributions/secretary/month/?month=" + encodeURIComponent(month),
      "GET"
    );

    document.getElementById("month-title").textContent =
      "Contributions for " + data.label;
    document.getElementById("month-total").textContent = data.month_total;

    fillMembers(data.members);
    fillPenalties(data.penalties);

    listSection.style.display = "block";
    penaltySection.style.display = "block";
  } catch (err) {
    if (err.status === 401) {
      window.location.href = "../../login.html";
      return;
    }
    errorBox.textContent = "Could not load that month. Please try again.";
  }
}

function fillMembers(rows) {
  const body = document.querySelector("#members-table tbody");
  body.innerHTML = "";
  rows.forEach(function (row) {
    const tr = document.createElement("tr");
    const datePaid = row.date_paid ? row.date_paid.substring(0, 10) : "—";
    tr.innerHTML =
      "<td>" + row.member + "</td>" +
      "<td>KES " + row.amount_paid + "</td>" +
      "<td>" + datePaid + "</td>" +
      "<td class='status-" + row.status + "'>" + row.status + "</td>";
    body.appendChild(tr);
  });
}

function fillPenalties(rows) {
  const body = document.querySelector("#penalties-table tbody");
  const noPenalties = document.getElementById("no-penalties");
  body.innerHTML = "";

  if (!rows || rows.length === 0) {
    noPenalties.style.display = "block";
    return;
  }
  noPenalties.style.display = "none";

  rows.forEach(function (row) {
    const tr = document.createElement("tr");
    const dateCharged = row.date_charged ? row.date_charged.substring(0, 10) : "—";
    const statusText = row.paid ? "paid" : "unpaid";
    tr.innerHTML =
      "<td>" + row.member + "</td>" +
      "<td>KES " + row.amount + "</td>" +
      "<td>" + dateCharged + "</td>" +
      "<td class='status-" + statusText + "'>" + statusText + "</td>";
    body.appendChild(tr);
  });
}

document.getElementById("logout-btn").addEventListener("click", logout);
document.getElementById("month-picker").addEventListener("change", function (e) {
  loadMonthDetail(e.target.value);
});

init();