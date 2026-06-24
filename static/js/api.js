/**
 * api.js — Central API helper for OSEDu
 */
const API_BASE = "/api";

const Auth = {
  // NOTE: the JWT itself is NEVER stored here. Login responses set an
  // httpOnly access_token_cookie (read by the browser automatically on
  // every same-origin request) plus a JS-readable csrf_access_token
  // cookie (echoed back as X-CSRF-TOKEN on mutations, see _getCsrfToken).
  //
  // localStorage only holds non-sensitive UI hints (role/name/student_id)
  // used for client-side routing decisions (requireAdmin etc.) and
  // greetings. An XSS payload reading these gets a role/display name —
  // not a bearer credential that could be replayed elsewhere. The real
  // credential (the JWT cookie) is inaccessible to JavaScript.
  getRole     : ()   => localStorage.getItem("osec_role"),
  setRole     : (r)  => localStorage.setItem("osec_role", r),
  getName     : ()   => localStorage.getItem("osec_name"),
  setName     : (n)  => localStorage.setItem("osec_name", n),
  getStudentId: ()   => localStorage.getItem("osec_student_id"),
  setStudentId: (id) => localStorage.setItem("osec_student_id", id),
  clear       : ()   => ["osec_role","osec_name","osec_student_id","osec_teacher_id"].forEach(k => localStorage.removeItem(k)),
  // isLoggedIn() is a client-side UX hint only (avoids flashing protected
  // UI before redirecting to login). It is NOT a security boundary — the
  // server independently verifies the JWT cookie on every API call and
  // returns 401 if it's missing/invalid/expired, which apiFetch handles
  // by clearing this and redirecting. A stale "logged in" hint just means
  // one extra failed request before the redirect, not unauthorized access.
  isLoggedIn  : ()   => !!localStorage.getItem("osec_role"),
};

/**
 * Read the csrf_access_token cookie set by flask-jwt-extended.
 * Sent as X-CSRF-TOKEN on every mutation (POST/PUT/DELETE/PATCH).
 * Only needed when JWT_COOKIE_CSRF_PROTECT=True (production).
 */
function _getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_access_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function apiFetch(path, options = {}) {
  const method   = (options.method || "GET").toUpperCase();
  const isMutate = ["POST", "PUT", "DELETE", "PATCH"].includes(method);
  const csrfToken = isMutate ? _getCsrfToken() : null;

  const headers = {
    "Content-Type": "application/json",
    ...(csrfToken ? { "X-CSRF-TOKEN": csrfToken } : {}),
    ...(options.headers || {}),
  };
  try {
    const res = await fetch(API_BASE + path, {
      ...options,
      headers,
      // Always send the httpOnly access_token_cookie (and csrf_access_token)
      // with same-origin requests — this is what authenticates the request
      // now that no token is stored in localStorage.
      credentials: "same-origin",
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    if (res.status === 401) {
      Auth.clear();
      const path = window.location.pathname;
      if (path.startsWith("/student")) { window.location.href = "/student/login"; }
      else if (path.startsWith("/teacher")) { window.location.href = "/teacher/login"; }
      else { window.location.href = "/admin/login"; }
      return null;
    }
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: { error: "Network error. Check your connection." } };
  }
}

const api = {
  get   : (p)       => apiFetch(p, { method: "GET" }),
  post  : (p, body) => apiFetch(p, { method: "POST",   body }),
  put   : (p, body) => apiFetch(p, { method: "PUT",    body }),
  delete: (p, body) => apiFetch(p, { method: "DELETE", body }),
};

/* ── Auth ── */
async function adminLogin(username, password) {
  const res = await api.post("/auth/admin/login", { username, password });
  if (res?.ok) {
    // The access_token_cookie (httpOnly) + csrf_access_token cookies are
    // set by the server response itself — nothing to store here except
    // UI hints.
    Auth.setRole("admin");
    Auth.setName(res.data.name || "Admin");
  }
  return res;
}

async function teacherLogin(identifier, password) {
  const res = await api.post("/auth/teacher/login", { identifier, password });
  if (res?.ok) {
    const t = res.data;
    Auth.setRole("teacher");
    Auth.setName(t.name || "Teacher");
    localStorage.setItem("osec_teacher_id", t.teacher_id || "");
  }
  return res;
}

async function studentLogin(identifier, password) {
  // /auth/student/login expects { identifier, password } and returns
  // { role, name, student_id, token } — flat fields, no "student" object.
  const res = await api.post("/auth/student/login", { identifier, password });
  if (res?.ok) {
    Auth.setRole("student");
    Auth.setName(res.data.name || "Student");
    Auth.setStudentId(res.data.student_id || "");
  }
  return res;
}

async function logout() {
  Auth.clear();
  await fetch(API_BASE + "/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin" }).catch(() => {});
  window.location.href = "/admin/login";
}

async function studentLogout() {
  Auth.clear();
  await fetch(API_BASE + "/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin" }).catch(() => {});
  window.location.href = "/student/login";
}

async function teacherLogout() {
  Auth.clear();
  await fetch(API_BASE + "/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin" }).catch(() => {});
  window.location.href = "/teacher/login";
}

function requireAdmin() {
  if (!Auth.isLoggedIn() || Auth.getRole() !== "admin") { window.location.href = "/admin/login"; return false; }
  return true;
}
function requireStudent() {
  if (!Auth.isLoggedIn() || Auth.getRole() !== "student") { window.location.href = "/student/login"; return false; }
  return true;
}
function requireTeacher() {
  if (!Auth.isLoggedIn() || (Auth.getRole() !== "teacher" && Auth.getRole() !== "admin")) {
    window.location.href = "/teacher/login"; return false;
  }
  return true;
}

/* ── Toast ── */
let _toastContainer = null;
function _getToastContainer() {
  if (!_toastContainer) {
    _toastContainer = document.createElement("div");
    _toastContainer.className = "toast-container";
    document.body.appendChild(_toastContainer);
  }
  return _toastContainer;
}

const _toastIcons = {
  success: `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  error  : `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  info   : `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  warning: `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>`,
};

function showToast(msg, type = "info") {
  const c = _getToastContainer();
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.innerHTML = (_toastIcons[type] || _toastIcons.info) + `<span>${escHtml(msg)}</span>`;
  c.appendChild(t);
  setTimeout(() => {
    t.style.animation = "tIn .2s ease reverse forwards";
    setTimeout(() => t.remove(), 200);
  }, 3400);
}

/* ── Button loading ── */
function showLoading(el, text = "Loading…") {
  el.disabled = true;
  el.dataset.orig = el.innerHTML;
  el.innerHTML = `<span class="spinner"></span> ${text}`;
}
function stopLoading(el) {
  el.disabled = false;
  if (el.dataset.orig !== undefined) el.innerHTML = el.dataset.orig;
  delete el.dataset.orig;
}

/* ── Grade helper ── */
function gradeClass(grade) {
  const map = { "A+":"grade-ap","A":"grade-a","B+":"grade-bp","B":"grade-b","C":"grade-c","D":"grade-d","F":"grade-f" };
  return map[grade] || "";
}

/* ── Misc helpers ── */
function formatDate(str) {
  if (!str) return "—";
  return new Date(str).toLocaleDateString("en-IN", { day:"2-digit", month:"short", year:"numeric" });
}
function formatDateTime(str) {
  if (!str) return "—";
  return new Date(str).toLocaleString("en-IN", { day:"2-digit", month:"short", year:"numeric", hour:"2-digit", minute:"2-digit" });
}
function escHtml(str = "") {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function statusBadge(status) {
  const map = {
    active:"badge-success",inactive:"badge-outline",pending:"badge-warning",
    paid:"badge-success",partial:"badge-warning",unpaid:"badge-danger",
    submitted:"badge-info",graded:"badge-success",late:"badge-warning",
    passed:"badge-success",failed:"badge-danger",
  };
  return `<span class="badge ${map[status]||"badge-outline"}">${escHtml(status)}</span>`;
}
