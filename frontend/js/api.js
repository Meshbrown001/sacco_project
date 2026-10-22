// ---------------------------------------------------------------------------
// api.js - shared by every page. Load it before any other script.
// ---------------------------------------------------------------------------

// Local backend during development, live backend once hosted.
const LOCAL_HOSTS = ["127.0.0.1", "localhost"];
const API_BASE_URL = LOCAL_HOSTS.includes(location.hostname)
  ? "http://127.0.0.1:8000/api"
  : "https://nyikwa-backend.onrender.com/api";

// Storage keys used across the frontend.
const STORAGE_KEYS = ["access_token", "refresh_token", "role", "username", "user_id"];


// ----- Tokens and user info ------------------------------------------------

function saveTokens(access, refresh) {
  localStorage.setItem("access_token", access);
  if (refresh) {
    localStorage.setItem("refresh_token", refresh);
  }
}

function getAccessToken() {
  return localStorage.getItem("access_token");
}

function getRefreshToken() {
  return localStorage.getItem("refresh_token");
}

function saveUserInfo(role, username, userId) {
  localStorage.setItem("role", role);
  localStorage.setItem("username", username);
  localStorage.setItem("user_id", userId);
}

function getRole() {
  return localStorage.getItem("role");
}

// Removes only this app's keys, so other sites served by Live Server keep theirs.
function clearSession() {
  STORAGE_KEYS.forEach(function (key) {
    localStorage.removeItem(key);
  });
}

// Finds login.html from any folder depth.
function goToLogin() {
  const path = window.location.pathname;
  if (path.includes("/staff/")) {
    window.location.href = "../../login.html";
  } else if (path.includes("/member/")) {
    window.location.href = "../login.html";
  } else {
    window.location.href = "login.html";
  }
}


// ----- Token refresh -------------------------------------------------------

// If several requests expire at once, they all share one refresh call.
let refreshPromise = null;

async function refreshAccessToken() {
  const refresh = getRefreshToken();
  if (!refresh) {
    return false;
  }

  if (!refreshPromise) {
    refreshPromise = (async function () {
      try {
        const response = await fetch(`${API_BASE_URL}/accounts/login/refresh/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh }),
        });
        if (!response.ok) {
          return false;
        }
        const data = await response.json();
        // The backend rotates refresh tokens, so save the new pair.
        saveTokens(data.access, data.refresh);
        return true;
      } catch (error) {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }

  return refreshPromise;
}


// ----- Requests ------------------------------------------------------------

function sendRequest(endpoint, method, body, useAuth) {
  const headers = { "Content-Type": "application/json" };

  if (useAuth) {
    const token = getAccessToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const config = { method, headers };
  if (body) {
    config.body = JSON.stringify(body);
  }

  return fetch(`${API_BASE_URL}${endpoint}`, config);
}

const SERVER_UNREACHABLE = {
  status: 0,
  data: { detail: "Cannot reach the server. Check your connection and try again." },
};

/**
 * Sends a request to the Django API.
 * endpoint: path after /api, for example "/accounts/login/"
 * useAuth:  false for login and register, true for everything else
 * Returns the response data. On failure, throws { status, data }.
 * An expired access token is refreshed once, then the request retries.
 */
async function apiRequest(endpoint, method = "GET", body = null, useAuth = true) {
  let response;

  try {
    response = await sendRequest(endpoint, method, body, useAuth);
  } catch (error) {
    throw SERVER_UNREACHABLE;
  }

  if (response.status === 401 && useAuth && getRefreshToken()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      try {
        response = await sendRequest(endpoint, method, body, useAuth);
      } catch (error) {
        throw SERVER_UNREACHABLE;
      }
    } else {
      clearSession();
    }
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw { status: response.status, data };
  }

  return data;
}


// ----- Logout --------------------------------------------------------------

/**
 * Tells Django to blacklist the refresh token, then clears the browser
 * and returns to the login page. The page still logs out locally if the
 * server cannot be reached.
 */
async function logout() {
  const refresh = getRefreshToken();

  if (refresh) {
    try {
      let response = await sendRequest("/accounts/logout/", "POST", { refresh }, true);

      // Access token expired: refresh it, then log out with the new refresh token.
      if (response.status === 401 && (await refreshAccessToken())) {
        await sendRequest("/accounts/logout/", "POST", { refresh: getRefreshToken() }, true);
      }
    } catch (error) {
      // Server unreachable. Fall through and log out locally.
    }
  }

  clearSession();
  goToLogin();
}