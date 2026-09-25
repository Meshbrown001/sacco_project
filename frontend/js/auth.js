// ---------------------------------------------------------------------------
// auth.js - login and registration pages. Needs api.js loaded first.
// ---------------------------------------------------------------------------

// Redirect helper based on role
function redirectByRole(role) {
  switch (role) {
    case "member":
      window.location.href = "member/dashboard.html";
      break;
    case "secretary":
      window.location.href = "staff/secretary/monthly_lists.html";
      break;
    case "treasurer":
      window.location.href = "staff/treasurer/account_overview.html";
      break;
    case "chairperson":
      window.location.href = "staff/chairperson/settings.html";
      break;
    default:
      window.location.href = "login.html";
  }
}


// ----- Form helpers --------------------------------------------------------

// Blocks a second submission while the first is still running.
// This also stops double-clicks and duplicate event listeners.
function beginSubmit(form) {
  if (form.dataset.busy === "true") {
    return false;
  }
  form.dataset.busy = "true";
  const button = form.querySelector('button[type="submit"]');
  if (button) {
    button.disabled = true;
    button.dataset.label = button.textContent;
    button.textContent = "Please wait...";
  }
  return true;
}

function endSubmit(form) {
  form.dataset.busy = "false";
  const button = form.querySelector('button[type="submit"]');
  if (button) {
    button.disabled = false;
    button.textContent = button.dataset.label || button.textContent;
  }
}

function clearErrors(form) {
  const errorBox = document.getElementById("error-message");
  if (errorBox) {
    errorBox.textContent = "";
  }
  form.querySelectorAll(".field-error").forEach(function (slot) {
    slot.textContent = "";
  });
  form.querySelectorAll("input.invalid").forEach(function (input) {
    input.classList.remove("invalid");
  });
}

// Puts each Django error under its own field. Errors with no matching
// field, such as "detail", go in the box at the top of the form.
function showErrors(data, fallbackMessage) {
  const errorBox = document.getElementById("error-message");
  const unplaced = [];

  Object.entries(data || {}).forEach(function ([field, messages]) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    const slot = document.getElementById("error-" + field);
    const input = document.getElementById(field);

    if (slot) {
      slot.textContent = text;
      if (input) {
        input.classList.add("invalid");
      }
    } else {
      unplaced.push(text);
    }
  });

  if (errorBox) {
    const hasFieldErrors = document.querySelector(".field-error:not(:empty)");
    errorBox.textContent =
      unplaced.join(" ") || (hasFieldErrors ? "" : fallbackMessage);
  }
}

function valueOf(id) {
  const input = document.getElementById(id);
  return input ? input.value.trim() : "";
}


// ----- Login ---------------------------------------------------------------

async function handleLogin(event) {
  event.preventDefault();
  const form = event.target;
  if (!beginSubmit(form)) {
    return;
  }
  clearErrors(form);

  const username = valueOf("username");
  const password = document.getElementById("password").value;

  try {
    const data = await apiRequest("/accounts/login/", "POST", { username, password }, false);
    saveTokens(data.access, data.refresh);
    saveUserInfo(data.role, data.username, data.user_id);
    redirectByRole(data.role);
  } catch (err) {
    const detail = err && err.data && err.data.detail;
    showErrors(detail ? { detail } : {}, "Login failed. Check your username and password.");
    endSubmit(form);
  }
}


// ----- Registration --------------------------------------------------------

async function handleRegister(event) {
  event.preventDefault();
  const form = event.target;
  if (!beginSubmit(form)) {
    return;
  }
  clearErrors(form);

  // Passwords are sent exactly as typed. Everything else is trimmed.
  const payload = {
    first_name: valueOf("first_name"),
    last_name: valueOf("last_name"),
    username: valueOf("username"),
    email: valueOf("email").toLowerCase(),
    phone_number: valueOf("phone_number"),
    national_id: valueOf("national_id"),
    password: document.getElementById("password").value,
    password2: document.getElementById("password2").value,
  };

  try {
    const data = await apiRequest("/accounts/register/", "POST", payload, false);

    if (data.access && data.refresh) {
      // The backend logged the new member in. Go straight to the dashboard.
      const user = data.user || {};
      saveTokens(data.access, data.refresh);
      saveUserInfo("member", user.username || payload.username, user.id || "");
      redirectByRole("member");
    } else {
      // Older backend without tokens: send the member to log in.
      alert("Registration successful! Please log in.");
      window.location.href = "login.html";
    }
  } catch (err) {
    showErrors(err && err.data, "Registration failed. Please try again.");
    endSubmit(form);
  }
}


// ----- Wiring --------------------------------------------------------------

document.addEventListener("DOMContentLoaded", function () {
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", handleLogin);
  }

  const registerForm = document.getElementById("register-form");
  if (registerForm) {
    registerForm.addEventListener("submit", handleRegister);
  }

  // Clear a field's error as soon as the member starts correcting it.
  document.querySelectorAll("form input").forEach(function (input) {
    input.addEventListener("input", function () {
      input.classList.remove("invalid");
      const slot = document.getElementById("error-" + input.id);
      if (slot) {
        slot.textContent = "";
      }
    });
  });
});