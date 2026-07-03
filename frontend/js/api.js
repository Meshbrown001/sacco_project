const API_BASE_URL = "http://127.0.0.1:8000/api";

function saveTokens(access, refresh) {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
}

function getAccessToken() {
  return localStorage.getItem("access_token");
}

function saveUserInfo(role, username, userId) {
  localStorage.setItem("role", role);
  localStorage.setItem("username", username);
  localStorage.setItem("user_id", userId);
}

function getRole() {
  return localStorage.getItem("role");
}

function logout() {
  localStorage.clear();
  window.location.href = "../login.html";
}

async function apiRequest(endpoint, method = "GET", body = null, useAuth = true) {
  const headers = { "Content-Type": "application/json" };

  if (useAuth) {
    const token = getAccessToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const config = { method, headers };
  if (body) config.body = JSON.stringify(body);

  const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw { status: response.status, data };
  }

  return data;
}