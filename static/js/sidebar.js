/**
 * sidebar.js — B&W sidebar renderer for OSEC
 */
const ADMIN_NAV = [
  { id:"dashboard", label:"Dashboard", href:"/admin/dashboard",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>` },
  { id:"students",  label:"Students",  href:"/admin/students",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>` },
  { id:"courses",   label:"Courses",   href:"/admin/courses",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>` },
  { id:"batches",   label:"Batches",   href:"/admin/batches",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>` },
  { id:"fees",      label:"Fees",      href:"/admin/fees",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z"/>` },
  { id:"exams",     label:"Exams",     href:"/admin/exams",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>` },
  { id:"questions", label:"Questions", href:"/admin/questions",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>` },
  { id:"results",   label:"Results",   href:"/admin/results",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>` },
  { id:"teachers",  label:"Teachers",  href:"/admin/teachers",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>` },
];

const STUDENT_NAV = [
  { id:"dashboard",    label:"Dashboard",    href:"/student/dashboard",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>` },
  { id:"assignments",  label:"Assignments",  href:"/student/assignments",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>` },
  { id:"resources",    label:"Resources",    href:"/student/resources",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/>` },
  { id:"results",      label:"My Results",   href:"/student/results",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>` },
  { id:"certificates", label:"Certificates", href:"/student/certificates",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z"/>` },
];

const TEACHER_NAV = [
  { id:"dashboard",   label:"Dashboard",   href:"/teacher/dashboard",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>` },
  { id:"resources",   label:"Resources",   href:"/teacher/resources",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/>` },
  { id:"assignments", label:"Assignments", href:"/teacher/assignments",
    icon:`<path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>` },
];

function renderSidebar(activeId, role = "admin") {
  const nav      = role === "admin" ? ADMIN_NAV : role === "teacher" ? TEACHER_NAV : STUDENT_NAV;
  const logoutFn = role === "admin" ? "logout()" : role === "teacher" ? "teacherLogout()" : "studentLogout()";
  const name     = Auth.getName() || (role === "admin" ? "Admin" : role === "teacher" ? "Teacher" : "Student");
  const parts    = name.trim().split(" ").filter(Boolean);
  const initials = parts.length >= 2 ? (parts[0][0] + parts[parts.length-1][0]).toUpperCase() : (parts[0]?.[0] || "?").toUpperCase();

  const links = nav.map(item => {
    const active = item.id === activeId;
    return `<a href="${item.href}" class="nav-link${active ? " active" : ""}">
      <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">${item.icon}</svg>
      ${item.label}
    </a>`;
  }).join("");

  const portalLinks = role === "admin" ? `
    <div class="sb-section" style="margin-top:8px">Portals</div>
    <a href="/teacher/login" class="nav-link" target="_blank" style="font-size:12.5px;opacity:.8">
      <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
      Teacher Portal ↗
    </a>
    <a href="/student/login" class="nav-link" target="_blank" style="font-size:12.5px;opacity:.8">
      <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M12 14l9-5-9-5-9 5 9 5z"/><path stroke-linecap="round" stroke-linejoin="round" d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z"/></svg>
      Student Portal ↗
    </a>` : "";

  document.getElementById("sidebarContainer").innerHTML = `
  <div class="sb-overlay" id="sbOverlay" onclick="closeSidebar()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:45"></div>
  <aside class="sidebar" id="sidebar">
    <div class="sb-logo">
      <div class="sb-mark">OS</div>
      <div><div class="sb-name">OSEDu</div><div class="sb-sub">${role === "admin" ? "Admin Panel" : role === "teacher" ? "Teacher Portal" : "Student Portal"}</div></div>
    </div>
    <nav class="sb-nav">
      <div class="sb-section">Menu</div>
      ${links}
      ${portalLinks}
    </nav>
    <div class="sb-footer">
      <div class="sb-user">
        <div class="sb-avatar">${initials}</div>
        <div><div class="sb-uname">${escHtml(name)}</div><div class="sb-urole">${role}</div></div>
      </div>
      <button class="btn-logout" onclick="${logoutFn}">
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
        Sign out
      </button>
    </div>
  </aside>`;
}

function openSidebar() {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sbOverlay").style.display = "block";
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sbOverlay").style.display = "none";
}
