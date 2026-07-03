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

// Handles the login form submission
async function handleLogin(event) {
  event.preventDefault();
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  const errorBox = document.getElementById("error-message");
  errorBox.textContent = "";

  try {
    const data = await apiRequest("/accounts/login/", "POST", { username, password }, false);
    saveTokens(data.access, data.refresh);
    saveUserInfo(data.role, data.username, data.user_id);
    redirectByRole(data.role);
  } catch (err) {
    errorBox.textContent = err.data.detail || "Login failed. Check your credentials.";
  }
}

// Handles the registration form submission
async function handleRegister(event) {
  event.preventDefault();
  const errorBox = document.getElementById("error-message");
  errorBox.textContent = "";

  const payload = {
    username: document.getElementById("username").value,
    email: document.getElementById("email").value,
    phone_number: document.getElementById("phone_number").value,
    national_id: document.getElementById("national_id").value,
    password: document.getElementById("password").value,
    password2: document.getElementById("password2").value,
  };

  try {
    await apiRequest("/accounts/register/", "POST", payload, false);
    alert("Registration successful! Please log in.");
    window.location.href = "login.html";
  } catch (err) {
    const messages = Object.values(err.data).flat().join(" ");
    errorBox.textContent = messages || "Registration failed.";
  }
}