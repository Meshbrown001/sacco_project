// ---------------------------------------------------------------------------
// forgot.js - forgot password. Needs api.js loaded first.
//
// Screen 1: the username is looked up as the user types; the registered
//           phone and email appear with checkboxes; Send code, then the
//           code box with Verify code and Resend code.
// Screen 2: the new password.
// Screen 3: after a successful change, a Go to login button, plus a
//           notice at the top of the window with an x to close it.
// ---------------------------------------------------------------------------

const LOOKUP_DELAY_MS = 700;   // wait this long after typing stops
const MIN_USERNAME = 3;

const state = {
  username: "",        // the account found, spelled as stored
  channels: [],        // [{channel: "sms"|"email", destination: "+2547*****040"}]
  channel: "",         // the ticked contact
  expiresAt: 0,
  resetToken: "",
};

let lookupTimer = null;
let lookupCounter = 0;
let lastLookup = "";
let countdownTimer = null;


// ----- Helpers -------------------------------------------------------------

function byId(id) {
  return document.getElementById(id);
}

function setError(message) {
  byId("error-message").textContent = message || "";
}

function setInfo(message) {
  byId("info-message").textContent = message || "";
}

function setLookupStatus(message, isError) {
  const box = byId("lookup-status");
  box.textContent = message || "";
  box.classList.toggle("is-error", Boolean(isError));
}

function setCodeMessage(message) {
  byId("code-message").textContent = message || "";
}

function setBusy(button, isBusy, busyText) {
  if (isBusy) {
    button.dataset.label = button.textContent;
    button.textContent = busyText || "Please wait...";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function detailOf(err, fallback) {
  return (err && err.data && err.data.detail) || fallback;
}


// ----- Looking up the username ---------------------------------------------

function resetFoundAccount() {
  state.username = "";
  state.channels = [];
  state.channel = "";
  stopCountdown();
  byId("contact-list").hidden = true;
  byId("contact-list").innerHTML = "";
  byId("send-btn").hidden = true;
  byId("send-btn").disabled = true;
  byId("code-box").hidden = true;
  setCodeMessage("");
  setInfo("");
}

function onUsernameInput() {
  const value = byId("reset-username").value.trim();
  setError("");
  if (value.toLowerCase() !== lastLookup.toLowerCase()) {
    resetFoundAccount();
    setLookupStatus("");
  }
  clearTimeout(lookupTimer);
  if (value.length >= MIN_USERNAME) {
    lookupTimer = setTimeout(function () { lookup(value); }, LOOKUP_DELAY_MS);
  }
}

function lookupNow() {
  clearTimeout(lookupTimer);
  const value = byId("reset-username").value.trim();
  if (value.length >= MIN_USERNAME) lookup(value);
}

async function lookup(username) {
  if (username.toLowerCase() === lastLookup.toLowerCase() && state.channels.length) return;

  const requestId = ++lookupCounter;
  lastLookup = username;
  setLookupStatus("Looking up your account...");

  let data;
  try {
    data = await apiRequest("/accounts/password-reset/start/", "POST", { username }, false);
  } catch (err) {
    if (requestId !== lookupCounter) return;
    lastLookup = "";
    setLookupStatus(detailOf(err, "We could not look up that username. Please try again."), true);
    return;
  }
  if (requestId !== lookupCounter) return;  // the user kept typing

  state.username = data.username;
  state.channels = data.channels;
  setLookupStatus("");
  renderContacts();
}


// ----- The registered contacts, with checkboxes ----------------------------

function renderContacts() {
  const list = byId("contact-list");
  list.innerHTML = "";

  state.channels.forEach(function (option) {
    const label = document.createElement("label");
    label.className = "contact-option";

    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = option.channel;

    const kind = document.createElement("span");
    kind.className = "contact-kind";
    kind.textContent = option.channel === "sms" ? "Phone" : "Email";

    const destination = document.createElement("span");
    destination.textContent = option.destination;

    box.addEventListener("change", function () {
      // Only one contact can be ticked at a time.
      list.querySelectorAll("input[type=checkbox]").forEach(function (other) {
        if (other !== box) other.checked = false;
      });
      state.channel = box.checked ? box.value : "";
      byId("send-btn").disabled = !state.channel;
      setError("");
    });

    label.appendChild(box);
    label.appendChild(kind);
    label.appendChild(destination);
    list.appendChild(label);
  });

  list.hidden = false;
  byId("send-btn").hidden = false;
  byId("send-btn").disabled = true;
}


// ----- Sending and resending the code --------------------------------------

async function sendCode(isResend) {
  setError("");
  setCodeMessage("");

  if (!state.channel) {
    setError("Tick the phone number or the email to receive the code.");
    return;
  }

  const button = isResend ? byId("resend-btn") : byId("send-btn");
  setBusy(button, true, "Sending...");
  try {
    const data = await apiRequest(
      "/accounts/password-reset/send/",
      "POST",
      { username: state.username, channel: state.channel },
      false
    );

    byId("code-box").hidden = false;
    byId("code-sent-to").textContent = "We sent a 6-digit code to " + data.sent_to + ".";
    byId("reset-code").value = "";
    byId("reset-code").disabled = false;
    byId("verify-btn").disabled = false;
    byId("reset-code").focus();

    startCountdown(data.expires_in);
    setInfo(isResend ? "A new code has been sent to " + data.sent_to + "." : "");
  } catch (err) {
    setError(detailOf(err, "We could not send the code. Please try again."));
  } finally {
    setBusy(button, false);
  }
}


// ----- The 5-minute countdown ----------------------------------------------

function startCountdown(seconds) {
  state.expiresAt = Date.now() + seconds * 1000;
  stopCountdown();
  tick();
  countdownTimer = setInterval(tick, 1000);
}

function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  byId("countdown").textContent = "";
}

function tick() {
  const remaining = Math.ceil((state.expiresAt - Date.now()) / 1000);
  if (remaining > 0) {
    const minutes = Math.floor(remaining / 60);
    const seconds = String(remaining % 60).padStart(2, "0");
    byId("countdown").textContent = "Code expires in " + minutes + ":" + seconds;
    return;
  }
  stopCountdown();
  byId("verify-btn").disabled = true;
  setCodeMessage("The code has expired. Click Resend code to get a new one.");
}


// ----- Verifying the code --------------------------------------------------

function explainCodeError(message) {
  const text = (message || "").toLowerCase();
  if (text.includes("expired")) {
    return "The code has expired. Click Resend code to get a new one.";
  }
  if (text.includes("too many")) {
    return "The code is incorrect, and too many wrong attempts were made. Click Resend code to get a new one.";
  }
  if (text.includes("incorrect")) {
    const left = message.match(/(\d+) attempt/);
    return "The code is incorrect." + (left ? " " + left[1] + " attempt(s) left." : "");
  }
  if (text.includes("no active code")) {
    return "This code is no longer valid. Click Resend code to get a new one.";
  }
  return message || "The code could not be checked. Please try again.";
}

async function verifyCode(event) {
  event.preventDefault();
  setError("");
  setInfo("");
  setCodeMessage("");

  const code = byId("reset-code").value.trim();
  if (!/^\d{6}$/.test(code)) {
    setCodeMessage("Enter the 6-digit code.");
    return;
  }
  if (Date.now() >= state.expiresAt) {
    setCodeMessage("The code has expired. Click Resend code to get a new one.");
    return;
  }

  const button = byId("verify-btn");
  setBusy(button, true, "Checking...");
  try {
    const data = await apiRequest(
      "/accounts/password-reset/verify/",
      "POST",
      { username: state.username, code: code },
      false
    );
    state.resetToken = data.reset_token;
    stopCountdown();
    showPasswordScreen();
  } catch (err) {
    const message = explainCodeError(detailOf(err, ""));
    setCodeMessage(message);
    setBusy(button, false);
    if (message.includes("Resend code")) {
      stopCountdown();
      button.disabled = true;
    }
  }
}


// ----- The new password ----------------------------------------------------

function showPasswordScreen() {
  byId("request-screen").hidden = true;
  byId("password-screen").hidden = false;
  byId("page-title").textContent = "Choose a New Password";
  setError("");
  setInfo("");
  byId("new-password").focus();
}

async function changePassword(event) {
  event.preventDefault();
  setError("");
  byId("error-new_password").textContent = "";
  byId("error-new_password2").textContent = "";

  const password = byId("new-password").value;
  const password2 = byId("new-password2").value;

  if (!password) {
    byId("error-new_password").textContent = "Enter a new password.";
    return;
  }
  if (password !== password2) {
    byId("error-new_password2").textContent = "Passwords do not match.";
    return;
  }

  const button = byId("password-btn");
  setBusy(button, true, "Changing...");
  try {
    await apiRequest(
      "/accounts/password-reset/complete/",
      "POST",
      {
        username: state.username,
        reset_token: state.resetToken,
        new_password: password,
        new_password2: password2,
      },
      false
    );
    clearSession();  // any login saved in this browser is now invalid
    showSuccess();
  } catch (err) {
    const data = (err && err.data) || {};
    let placed = false;
    ["new_password", "new_password2"].forEach(function (field) {
      if (data[field]) {
        byId("error-" + field).textContent = [].concat(data[field]).join(" ");
        placed = true;
      }
    });
    if (!placed) setError(detailOf(err, "Your password could not be changed. Please try again."));
  } finally {
    setBusy(button, false);
  }
}

function showSuccess() {
  // Only reached after the server confirms the new password.
  byId("password-screen").hidden = true;
  byId("done-screen").hidden = false;
  byId("page-title").textContent = "Password Changed";
  setError("");
  setInfo("");
  byId("success-toast").hidden = false;
}


// ----- Start ---------------------------------------------------------------

const usernameInput = byId("reset-username");
usernameInput.addEventListener("input", onUsernameInput);
usernameInput.addEventListener("blur", lookupNow);
usernameInput.addEventListener("keydown", function (event) {
  if (event.key === "Enter") {
    event.preventDefault();
    lookupNow();
  }
});

byId("send-btn").addEventListener("click", function () { sendCode(false); });
byId("resend-btn").addEventListener("click", function () { sendCode(true); });
byId("request-screen").addEventListener("submit", verifyCode);
byId("password-screen").addEventListener("submit", changePassword);

// The x on the success notice closes it. The Go to login button stays on the page.
byId("toast-close").addEventListener("click", function () {
  byId("success-toast").hidden = true;
});

// Keep only digits in the code box.
byId("reset-code").addEventListener("input", function (event) {
  event.target.value = event.target.value.replace(/\D/g, "").slice(0, 6);
});

usernameInput.focus();