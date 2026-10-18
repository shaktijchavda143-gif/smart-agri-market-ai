# -*- coding: utf-8 -*-
"""
Responsive Green + Gold Agricultural Theme Admin Panel Web UI for Smart Agri-Market AI.
Contains no hardcoded credentials or secrets; enforces XSS escaping, CSRF headers,
and role-aware controls backed by strict server-side RBAC.
"""

ADMIN_PANEL_HTML = r"""<!DOCTYPE html>
<html lang="gu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>સ્માર્ટ એગ્રી માર્કેટ AI — સુરક્ષિત એડમિન પેનલ</title>
<style>
  :root {
    --green-900: #064E3B;
    --green-800: #14532D;
    --green-700: #15803D;
    --green-600: #16A34A;
    --green-100: #DCFCE7;
    --green-50: #F2FBF5;
    --gold-600: #D97706;
    --gold-500: #F59E0B;
    --gold-300: #FDE047;
    --gold-100: #FEF3C7;
    --red-700: #B91C1C;
    --red-100: #FEE2E2;
    --blue-700: #1D4ED8;
    --blue-100: #DBEAFE;
    --slate-800: #1E293B;
    --slate-600: #475569;
    --slate-200: #E2E8F0;
    --white: #FFFFFF;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Noto Sans Gujarati", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--green-50);
    color: var(--slate-800);
    line-height: 1.5;
  }
  .hidden { display: none !important; }
  /* Top Header */
  .top-header {
    background: linear-gradient(135deg, var(--green-900), var(--green-800));
    color: var(--white);
    padding: 14px 22px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    border-bottom: 3px solid var(--gold-500);
    box-shadow: 0 4px 12px rgba(6, 78, 59, 0.18);
  }
  .brand-box { display: flex; align-items: center; gap: 12px; }
  .brand-logo {
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--white); display: flex; align-items: center; justify-content: center;
    font-size: 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.2);
  }
  .brand-title { font-size: 19px; font-weight: 800; color: var(--gold-300); }
  .brand-sub { font-size: 12.5px; color: #E2F7EB; }
  .header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .role-badge {
    background: rgba(253, 224, 71, 0.18);
    border: 1px solid var(--gold-300);
    color: var(--gold-300);
    padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700;
  }
  /* Buttons */
  .btn {
    border: none; border-radius: 10px; padding: 8px 14px;
    font-size: 13px; font-weight: 700; cursor: pointer;
    transition: all 0.15s ease; display: inline-flex; align-items: center; gap: 6px;
    font-family: inherit;
  }
  .btn:disabled { opacity: 0.55; cursor: not-allowed; }
  .btn-primary { background: var(--green-700); color: var(--white); }
  .btn-primary:hover:not(:disabled) { background: var(--green-800); }
  .btn-gold { background: var(--gold-600); color: var(--white); }
  .btn-gold:hover:not(:disabled) { background: #B45309; }
  .btn-danger { background: var(--red-700); color: var(--white); }
  .btn-danger:hover:not(:disabled) { background: #991B1B; }
  .btn-outline {
    background: var(--white); color: var(--green-800);
    border: 1.5px solid var(--green-700);
  }
  .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 8px; }
  /* Login Container */
  .login-wrap {
    max-width: 430px; margin: 56px auto; padding: 28px;
    background: var(--white); border-radius: 20px;
    border: 2px solid #86EFAC;
    box-shadow: 0 12px 30px rgba(6, 78, 59, 0.12);
  }
  .login-wrap h2 { color: var(--green-800); font-size: 21px; margin-bottom: 6px; }
  .form-group { margin-bottom: 14px; }
  .form-group label { display: block; font-size: 13px; font-weight: 700; color: var(--slate-800); margin-bottom: 5px; }
  .form-control {
    width: 100%; padding: 10px 12px; border-radius: 10px;
    border: 1.5px solid #CBD5E1; font-size: 14px; font-family: inherit;
  }
  .form-control:focus { outline: none; border-color: var(--green-700); }
  /* Main Container */
  .container { max-width: 1320px; margin: 0 auto; padding: 18px; }
  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
    gap: 12px; margin-bottom: 18px;
  }
  .kpi-card {
    background: var(--white); border-radius: 16px; padding: 14px 16px;
    border: 1.5px solid #BBF7D0; box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  }
  .kpi-label { font-size: 12.5px; color: var(--slate-600); font-weight: 700; }
  .kpi-val { font-size: 26px; font-weight: 800; color: var(--green-800); margin-top: 4px; }
  /* Tabs */
  .nav-tabs {
    display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;
    border-bottom: 2px solid #BBF7D0; padding-bottom: 10px;
  }
  .tab-btn {
    padding: 9px 16px; border-radius: 12px; border: 1.5px solid #86EFAC;
    background: var(--white); color: var(--green-800); font-weight: 700;
    cursor: pointer; font-size: 13.5px; font-family: inherit;
  }
  .tab-btn.active {
    background: var(--green-800); color: var(--gold-300); border-color: var(--green-900);
  }
  /* Panel Card & Filter Bar */
  .panel-card {
    background: var(--white); border-radius: 18px; padding: 16px;
    border: 1.5px solid #BBF7D0; box-shadow: 0 3px 10px rgba(0,0,0,0.04);
  }
  .filter-bar {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 10px; margin-bottom: 14px; align-items: end;
  }
  /* Table */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th {
    background: var(--green-800); color: var(--white); text-align: left;
    padding: 10px 12px; font-weight: 700; white-space: nowrap;
  }
  td { padding: 10px 12px; border-bottom: 1px solid var(--slate-200); vertical-align: middle; }
  tr:nth-child(even) { background: #F8FAFC; }
  /* Status Badges */
  .badge {
    display: inline-block; padding: 3px 9px; border-radius: 999px;
    font-size: 11.5px; font-weight: 700;
  }
  .badge-active { background: var(--green-100); color: var(--green-800); }
  .badge-blocked { background: var(--red-100); color: var(--red-700); }
  .badge-deleted { background: #F1F5F9; color: #475569; }
  .badge-pending { background: var(--gold-100); color: #92400E; }
  .badge-resolved { background: var(--blue-100); color: var(--blue-700); }
  /* Modal */
  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(15, 23, 42, 0.6);
    display: flex; align-items: center; justify-content: center;
    padding: 16px; z-index: 1000;
  }
  .modal-box {
    background: var(--white); border-radius: 18px; max-width: 640px; width: 100%;
    max-height: 90vh; overflow-y: auto; padding: 22px;
    border: 2px solid var(--gold-500); box-shadow: 0 20px 40px rgba(0,0,0,0.25);
  }
  .modal-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 14px; border-bottom: 1px solid var(--slate-200); padding-bottom: 10px;
  }
  .alert-msg {
    padding: 10px 14px; border-radius: 10px; margin-bottom: 12px;
    font-size: 13px; font-weight: 700;
  }
  .alert-error { background: var(--red-100); color: var(--red-700); border: 1px solid #FCA5A5; }
  .alert-ok { background: var(--green-100); color: var(--green-800); border: 1px solid #86EFAC; }
  .pagination-bar {
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 14px; flex-wrap: wrap; gap: 10px;
  }
</style>
</head>
<body>

<header class="top-header">
  <div class="brand-box">
    <div class="brand-logo">🌿</div>
    <div>
      <div class="brand-title">સ્માર્ટ એગ્રી માર્કેટ AI — સુરક્ષિત એડમિન પેનલ</div>
      <div class="brand-sub">મુકાદમ સંચાલન, ફરિયાદ ચકાસણી અને સુરક્ષા ઓડિટ ડેશબોર્ડ</div>
    </div>
  </div>
  <div id="headerAuthArea" class="header-actions hidden">
    <span id="adminUserLabel" style="font-size:13px;font-weight:700;"></span>
    <span id="adminRoleBadge" class="role-badge"></span>
    <button id="btnExportCsv" class="btn btn-gold btn-sm" onclick="downloadCsv()">📥 CSV નિકાસ</button>
    <button id="btnCreateBackup" class="btn btn-outline btn-sm hidden" onclick="triggerBackup()">💾 DB બેકઅપ</button>
    <button class="btn btn-danger btn-sm" onclick="logoutAdmin()">🚪 લોગઆઉટ</button>
  </div>
</header>

<!-- LOGIN VIEW -->
<main id="loginView" class="login-wrap">
  <h2>🔐 એડમિન લોગિન (Secure Admin Login)</h2>
  <p style="font-size:12.5px;color:#475569;margin-bottom:16px;">અધિકૃત એડમિન યુઝરનેમ અને પાસવર્ડ વડે લોગિન કરો.</p>
  <div id="loginAlert" class="alert-msg alert-error hidden"></div>
  <form onsubmit="handleLogin(event)">
    <div class="form-group">
      <label for="loginUsername">યુઝરનેમ (Username)</label>
      <input id="loginUsername" class="form-control" type="text" required autocomplete="username" />
    </div>
    <div class="form-group">
      <label for="loginPassword">પાસવર્ડ (Password)</label>
      <input id="loginPassword" class="form-control" type="password" required autocomplete="current-password" />
    </div>
    <button id="btnLoginSubmit" type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:11px;">🔐 સુરક્ષિત લોગિન કરો</button>
  </form>
  <div style="margin-top:14px;text-align:center;">
    <button type="button" class="btn btn-outline btn-sm" onclick="openResetModal()">🔑 પાસવર્ડ રીસેટ (Master Secret)</button>
  </div>
</main>

<!-- DASHBOARD VIEW -->
<main id="dashboardView" class="container hidden">
  <div id="globalToast" class="alert-msg alert-ok hidden"></div>

  <!-- Overview Cards -->
  <section class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">👥 કુલ મુકાદમ</div>
      <div id="kpiTotal" class="kpi-val">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">🟢 સક્રિય મુકાદમ (Active)</div>
      <div id="kpiActive" class="kpi-val" style="color:#15803D;">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">🚫 બ્લોક કરેલા (Blocked)</div>
      <div id="kpiBlocked" class="kpi-val" style="color:#B91C1C;">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">🗑️ Soft-Deleted</div>
      <div id="kpiDeleted" class="kpi-val" style="color:#475569;">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">⏳ બાકી ફરિયાદો</div>
      <div id="kpiPendingReports" class="kpi-val" style="color:#D97706;">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">✅ ઉકેલાયેલી ફરિયાદો</div>
      <div id="kpiResolvedReports" class="kpi-val" style="color:#1D4ED8;">0</div>
    </div>
  </section>

  <!-- Navigation Tabs -->
  <nav class="nav-tabs">
    <button id="tabBtnMukadams" class="tab-btn active" onclick="switchTab('mukadams')">👷 મુકાદમ ડિરેક્ટરી</button>
    <button id="tabBtnReports" class="tab-btn" onclick="switchTab('reports')">🚨 ફરિયાદ ચકાસણી (Reports)</button>
    <button id="tabBtnAudit" class="tab-btn hidden" onclick="switchTab('audit')">📜 ઓડિટ લોગ (Audit Logs)</button>
    <button id="tabBtnAdmins" class="tab-btn hidden" onclick="switchTab('admins')">🔐 એડમિન રોલ સંચાલન</button>
  </nav>

  <!-- TAB 1: MUKADAM DIRECTORY -->
  <section id="tabMukadams" class="panel-card">
    <div class="filter-bar">
      <div>
        <label style="font-size:12px;font-weight:700;">નામ / શોધ</label>
        <input id="fltQ" class="form-control" type="text" placeholder="નામ અથવા ગામ..." />
      </div>
      <div>
        <label style="font-size:12px;font-weight:700;">મોબાઇલ નંબર</label>
        <input id="fltMobile" class="form-control" type="text" placeholder="10 અંક..." />
      </div>
      <div>
        <label style="font-size:12px;font-weight:700;">જિલ્લો</label>
        <input id="fltDistrict" class="form-control" type="text" placeholder="દા.ત. ગીર સોમનાથ" />
      </div>
      <div>
        <label style="font-size:12px;font-weight:700;">ગામ / તાલુકો</label>
        <input id="fltVillage" class="form-control" type="text" placeholder="ગામ..." />
      </div>
      <div>
        <label style="font-size:12px;font-weight:700;">સ્થિતિ (Status)</label>
        <select id="fltStatus" class="form-control">
          <option value="ALL">બધા (All)</option>
          <option value="ACTIVE">સક્રિય (Active)</option>
          <option value="BLOCKED">બ્લોક (Blocked)</option>
          <option value="SOFT_DELETED">Soft-Deleted</option>
        </select>
      </div>
      <div>
        <label style="font-size:12px;font-weight:700;">ક્રમ (Sort)</label>
        <select id="fltSort" class="form-control">
          <option value="updated_at:desc">છેલ્લે અપડેટ થયેલ</option>
          <option value="created_at:desc">નવી નોંધણી પહેલાં</option>
          <option value="total_labors:desc">વધુ મજૂર સંખ્યા</option>
          <option value="name:asc">નામ (A-Z)</option>
        </select>
      </div>
      <div>
        <button class="btn btn-primary" style="width:100%;justify-content:center;" onclick="loadMukadams(1)">🔍 શોધો</button>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>મુકાદમનું નામ</th>
            <th>મોબાઇલ</th>
            <th>જિલ્લો / તાલુકો / ગામ</th>
            <th>મજૂર</th>
            <th>ઉપલબ્ધતા</th>
            <th>એકાઉન્ટ સ્થિતિ</th>
            <th>નોંધણી / અપડેટ</th>
            <th>કાર્યવાહી (Actions)</th>
          </tr>
        </thead>
        <tbody id="mukadamTableBody"></tbody>
      </table>
    </div>
    <div class="pagination-bar">
      <div id="mukadamPageInfo" style="font-size:13px;font-weight:700;"></div>
      <div style="display:flex;gap:8px;">
        <button id="btnPrevMuk" class="btn btn-outline btn-sm" onclick="changeMukPage(-1)">◀ પાછળ</button>
        <button id="btnNextMuk" class="btn btn-outline btn-sm" onclick="changeMukPage(1)">આગળ ▶</button>
      </div>
    </div>
  </section>

  <!-- TAB 2: REPORTS -->
  <section id="tabReports" class="panel-card hidden">
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap;">
      <label style="font-size:13px;font-weight:700;">ફરિયાદ સ્ટેટસ:</label>
      <select id="fltReportStatus" class="form-control" style="max-width:220px;" onchange="loadReports(1)">
        <option value="ALL">બધી ફરિયાદો (All)</option>
        <option value="PENDING">PENDING (બાકી)</option>
        <option value="UNDER_REVIEW">UNDER_REVIEW (તપાસ હેઠળ)</option>
        <option value="VERIFIED">VERIFIED (સાચી ઠરેલ)</option>
        <option value="RESOLVED">RESOLVED (ઉકેલાયેલ)</option>
        <option value="REJECTED">REJECTED (રદ કરેલ)</option>
      </select>
      <button class="btn btn-primary btn-sm" onclick="loadReports(1)">🔄 રીફ્રેશ</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Report ID</th>
            <th>મુકાદમ</th>
            <th>પ્રકાર</th>
            <th>વર્ણન</th>
            <th>તારીખ</th>
            <th>સ્ટેટસ</th>
            <th>તપાસનાર</th>
            <th>કાર્યવાહી</th>
          </tr>
        </thead>
        <tbody id="reportsTableBody"></tbody>
      </table>
    </div>
  </section>

  <!-- TAB 3: AUDIT LOGS -->
  <section id="tabAudit" class="panel-card hidden">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:10px;">
      <div>
        <span id="auditChainBadge" class="badge badge-active">🔒 Hash-Chain ચકાસણી...</span>
      </div>
      <div style="display:flex;gap:8px;">
        <input id="fltAuditAction" class="form-control" style="max-width:200px;" placeholder="Action ફિલ્ટર..." />
        <button class="btn btn-primary btn-sm" onclick="loadAuditLogs(1)">🔍 ફિલ્ટર</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Audit ID</th>
            <th>સમય (Timestamp)</th>
            <th>Admin (Role)</th>
            <th>Action</th>
            <th>Target</th>
            <th>Result</th>
            <th>Reason / Metadata</th>
            <th>Entry Hash</th>
          </tr>
        </thead>
        <tbody id="auditTableBody"></tbody>
      </table>
    </div>
  </section>

  <!-- TAB 4: ADMIN USERS (SUPER_ADMIN) -->
  <section id="tabAdmins" class="panel-card hidden">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <h3 style="color:var(--green-800);font-size:16px;">🔐 એડમિન અને રોલ સંચાલન (SUPER_ADMIN Only)</h3>
      <button class="btn btn-primary btn-sm" onclick="openAdminUserModal()">＋ નવા એડમિન ઉમેરો / રોલ બદલો</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>નામ</th>
            <th>Role</th>
            <th>સ્થિતિ</th>
            <th>છેલ્લું લોગિન</th>
          </tr>
        </thead>
        <tbody id="adminsTableBody"></tbody>
      </table>
    </div>
  </section>
</main>

<!-- DYNAMIC MODAL -->
<div id="modalBackdrop" class="modal-backdrop hidden">
  <div class="modal-box">
    <div class="modal-header">
      <h3 id="modalTitle" style="color:var(--green-800);font-size:17px;"></h3>
      <button class="btn btn-outline btn-sm" onclick="closeModal()">✕ બંધ</button>
    </div>
    <div id="modalBody"></div>
  </div>
</div>

<script>
  let sessionToken = sessionStorage.getItem("sam_admin_token") || "";
  let csrfToken = sessionStorage.getItem("sam_admin_csrf") || "";
  let currentAdmin = null;
  let mukPage = 1;

  function escHtml(str) {
    const d = document.createElement("div");
    d.textContent = str == null ? "" : String(str);
    return d.innerHTML;
  }

  function fmtDate(ts) {
    if (!ts || Number(ts) <= 0) return "-";
    try {
      return new Date(Number(ts) * 1000).toLocaleString("gu-IN");
    } catch (_) {
      return "-";
    }
  }

  function showToast(msg, isErr = false) {
    const el = document.getElementById("globalToast");
    el.textContent = msg;
    el.className = "alert-msg " + (isErr ? "alert-error" : "alert-ok");
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 5000);
  }

  async function apiFetch(path, options = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    if (sessionToken) headers["Authorization"] = "Bearer " + sessionToken;
    if (csrfToken && options.method && options.method !== "GET") {
      headers["X-CSRF-Token"] = csrfToken;
    }
    const resp = await fetch(path, Object.assign({}, options, { headers }));
    let data = {};
    try { data = await resp.json(); } catch (_) {}
    if (resp.status === 401 && !path.includes("/login") && !path.includes("/permanent")) {
      clearSession();
    }
    return { status: resp.status, data };
  }

  function clearSession() {
    sessionToken = "";
    csrfToken = "";
    currentAdmin = null;
    sessionStorage.removeItem("sam_admin_token");
    sessionStorage.removeItem("sam_admin_csrf");
    document.getElementById("loginView").classList.remove("hidden");
    document.getElementById("dashboardView").classList.add("hidden");
    document.getElementById("headerAuthArea").classList.add("hidden");
  }

  async function handleLogin(e) {
    e.preventDefault();
    const alertEl = document.getElementById("loginAlert");
    alertEl.classList.add("hidden");
    const username = document.getElementById("loginUsername").value.trim();
    const password = document.getElementById("loginPassword").value;
    const { status, data } = await apiFetch("/api/v1/admin/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
    if (!data.ok) {
      alertEl.textContent = data.detail || data.message_gu || "લોગિન નિષ્ફળ ગયું.";
      alertEl.classList.remove("hidden");
      return;
    }
    sessionToken = data.session_token;
    csrfToken = data.csrf_token;
    currentAdmin = data.admin;
    sessionStorage.setItem("sam_admin_token", sessionToken);
    sessionStorage.setItem("sam_admin_csrf", csrfToken);
    document.getElementById("loginPassword").value = "";
    enterDashboard();
  }

  async function logoutAdmin() {
    await apiFetch("/api/v1/admin/auth/logout", { method: "POST", body: "{}" });
    clearSession();
  }

  function enterDashboard() {
    document.getElementById("loginView").classList.add("hidden");
    document.getElementById("dashboardView").classList.remove("hidden");
    document.getElementById("headerAuthArea").classList.remove("hidden");
    document.getElementById("adminUserLabel").textContent = "👤 " + (currentAdmin.display_name || currentAdmin.username);
    document.getElementById("adminRoleBadge").textContent = currentAdmin.role;

    const isSuper = currentAdmin.role === "SUPER_ADMIN";
    const canViewReports = (currentAdmin.permissions || []).includes("reports:view");
    const canExport = (currentAdmin.permissions || []).includes("mukadam:export");

    document.getElementById("tabBtnAudit").classList.toggle("hidden", !isSuper);
    document.getElementById("tabBtnAdmins").classList.toggle("hidden", !isSuper);
    document.getElementById("btnCreateBackup").classList.toggle("hidden", !isSuper);
    document.getElementById("tabBtnReports").classList.toggle("hidden", !canViewReports);
    document.getElementById("btnExportCsv").classList.toggle("hidden", !canExport);

    loadOverview();
    loadMukadams(1);
  }

  async function loadOverview() {
    const { data } = await apiFetch("/api/v1/admin/dashboard");
    if (!data.ok) return;
    const o = data.overview;
    document.getElementById("kpiTotal").textContent = o.total_mukadams;
    document.getElementById("kpiActive").textContent = o.active_mukadams;
    document.getElementById("kpiBlocked").textContent = o.blocked_mukadams;
    document.getElementById("kpiDeleted").textContent = o.soft_deleted_mukadams;
    document.getElementById("kpiPendingReports").textContent = o.pending_reports;
    document.getElementById("kpiResolvedReports").textContent = o.resolved_reports;
  }

  function switchTab(tab) {
    ["mukadams", "reports", "audit", "admins"].forEach(t => {
      document.getElementById("tab" + t.charAt(0).toUpperCase() + t.slice(1)).classList.toggle("hidden", t !== tab);
      document.getElementById("tabBtn" + t.charAt(0).toUpperCase() + t.slice(1)).classList.toggle("active", t === tab);
    });
    if (tab === "mukadams") loadMukadams(mukPage);
    if (tab === "reports") loadReports(1);
    if (tab === "audit") loadAuditLogs(1);
    if (tab === "admins") loadAdminUsers();
  }

  async function loadMukadams(page = 1) {
    mukPage = page;
    const q = document.getElementById("fltQ").value.trim();
    const mobile = document.getElementById("fltMobile").value.trim();
    const district = document.getElementById("fltDistrict").value.trim();
    const village = document.getElementById("fltVillage").value.trim();
    const status = document.getElementById("fltStatus").value;
    const [sortBy, sortDir] = document.getElementById("fltSort").value.split(":");

    const params = new URLSearchParams({
      q, mobile, district, village, status_filter: status,
      sort_by: sortBy, sort_dir: sortDir, page, page_size: 15
    });
    const { data } = await apiFetch("/api/v1/admin/mukadams?" + params.toString());
    const tbody = document.getElementById("mukadamTableBody");
    tbody.innerHTML = "";
    if (!data.ok || !data.mukadams.length) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:24px;color:#64748B;">કોઈ મુકાદમ રેકોર્ડ મળ્યો નથી.</td></tr>';
      document.getElementById("mukadamPageInfo").textContent = "કુલ: 0";
      return;
    }
    const perms = currentAdmin.permissions || [];
    const canBlock = perms.includes("mukadam:block");
    const canUnblock = perms.includes("mukadam:unblock");
    const canSoftDel = perms.includes("mukadam:soft_delete");
    const canRestore = perms.includes("mukadam:restore");
    const canPermDel = perms.includes("mukadam:permanent_delete");

    data.mukadams.forEach(m => {
      const tr = document.createElement("tr");
      const accSt = m.account_status || (m.is_blocked ? "BLOCKED" : "ACTIVE");
      let stBadge = '<span class="badge badge-active">🟢 ACTIVE</span>';
      if (accSt === "BLOCKED") stBadge = '<span class="badge badge-blocked">🚫 BLOCKED</span>';
      if (accSt === "SOFT_DELETED") stBadge = '<span class="badge badge-deleted">🗑️ SOFT-DELETED</span>';

      let actionsHtml = `<button class="btn btn-outline btn-sm" onclick="viewMukadamProfile(${Number(m.id)})">👁️ વિગત</button> `;
      if (accSt === "ACTIVE" && canBlock) {
        actionsHtml += `<button class="btn btn-gold btn-sm" onclick="openBlockModal(${Number(m.id)}, '${escHtml(m.name)}')">🚫 બ્લોક</button> `;
      }
      if (accSt === "BLOCKED" && canUnblock) {
        actionsHtml += `<button class="btn btn-primary btn-sm" onclick="openUnblockModal(${Number(m.id)}, '${escHtml(m.name)}')">✅ અનબ્લોક</button> `;
      }
      if (accSt !== "SOFT_DELETED" && canSoftDel) {
        actionsHtml += `<button class="btn btn-danger btn-sm" onclick="openSoftDeleteModal(${Number(m.id)}, '${escHtml(m.name)}')">🗑️ Soft Delete</button> `;
      }
      if (accSt === "SOFT_DELETED" && canRestore) {
        actionsHtml += `<button class="btn btn-primary btn-sm" onclick="restoreMukadamAction(${Number(m.id)})">♻️ Restore</button> `;
      }
      if (accSt === "SOFT_DELETED" && canPermDel) {
        actionsHtml += `<button class="btn btn-danger btn-sm" onclick="openPermDeleteModal(${Number(m.id)}, '${escHtml(m.name)}', '${escHtml(m.mobile)}')">⚠️ કાયમી ડિલીટ</button>`;
      }

      tr.innerHTML = `
        <td>#${Number(m.id)}</td>
        <td><strong>${escHtml(m.name)}</strong></td>
        <td>${escHtml(m.mobile)}</td>
        <td>${escHtml(m.district)} / ${escHtml(m.taluka)} / ${escHtml(m.village)}</td>
        <td>${Number(m.total_labors)}</td>
        <td>${escHtml(m.available_status)}</td>
        <td>${stBadge}</td>
        <td style="font-size:11.5px;">${fmtDate(m.updated_at)}</td>
        <td style="white-space:nowrap;">${actionsHtml}</td>
      `;
      tbody.appendChild(tr);
    });
    document.getElementById("mukadamPageInfo").textContent = `કુલ ${data.total} મુકાદમ • પેજ ${data.page} / ${data.total_pages}`;
    document.getElementById("btnPrevMuk").disabled = data.page <= 1;
    document.getElementById("btnNextMuk").disabled = data.page >= data.total_pages;
  }

  function changeMukPage(delta) {
    loadMukadams(Math.max(1, mukPage + delta));
  }

  async function viewMukadamProfile(id) {
    const { data } = await apiFetch(`/api/v1/admin/mukadams/${id}`);
    if (!data.ok) return showToast(data.detail || data.message_gu || "લોડ નિષ્ફળ", true);
    const p = data.profile;
    const reports = data.reports || [];
    const history = data.admin_action_history || [];

    let repHtml = reports.length ? reports.map(r =>
      `<div style="padding:8px;border:1px solid #E2E8F0;border-radius:8px;margin-bottom:6px;font-size:12.5px;">
        <strong>#${r.id} [${escHtml(r.status)}]</strong> — ${escHtml(r.report_type)}: ${escHtml(r.description)} (${fmtDate(r.created_at)})
      </div>`
    ).join("") : "<p style='font-size:12.5px;color:#64748B;'>કોઈ ફરિયાદ નોંધાયેલ નથી.</p>";

    let histHtml = history.length ? history.map(h =>
      `<div style="padding:6px 8px;border-left:3px solid #15803D;background:#F8FAFC;margin-bottom:6px;font-size:12px;">
        <strong>${escHtml(h.action)}</strong> (${escHtml(h.result)}) by ${escHtml(h.admin_username)} [${escHtml(h.admin_role)}] — ${escHtml(h.reason)} (${fmtDate(h.timestamp)})
      </div>`
    ).join("") : "<p style='font-size:12.5px;color:#64748B;'>કોઈ એડમિન કાર્યવાહી થયેલ નથી.</p>";

    openModal(`👷 મુકાદમ પ્રોફાઇલ #${p.id}: ${escHtml(p.name)}`, `
      <div style="font-size:13.5px;display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
        <div><strong>મોબાઇલ:</strong> ${escHtml(p.mobile)}</div>
        <div><strong>એકાઉન્ટ સ્ટેટસ:</strong> ${escHtml(p.account_status)}</div>
        <div><strong>લોકેશન:</strong> ${escHtml(p.district)} ➔ ${escHtml(p.taluka)} ➔ ${escHtml(p.village)}</div>
        <div><strong>કુલ મજૂર:</strong> ${Number(p.total_labors)} (પુરુષ: ${Number(p.male_labors)}, સ્ત્રી: ${Number(p.female_labors)})</div>
        <div><strong>રોજિંદો ભાવ:</strong> ₹${Number(p.daily_wage_rate)} (${escHtml(p.wage_type)})</div>
        <div><strong>રીક્ષા / મુકાદમી:</strong> ₹${Number(p.rickshaw_fare_rate)} / ₹${Number(p.mukadami_rate)}</div>
        <div><strong>નોંધણી સમય:</strong> ${fmtDate(p.created_at)}</div>
        <div><strong>છેલ્લો સુધારો:</strong> ${fmtDate(p.updated_at)}</div>
      </div>
      ${p.block_reason ? `<div class="alert-msg alert-error"><strong>બ્લોક કારણ:</strong> ${escHtml(p.block_reason)} (By: ${escHtml(p.blocked_by)})</div>` : ""}
      <h4 style="margin:10px 0 6px;color:#14532D;">🚨 ફરિયાદ ઇતિહાસ (${reports.length})</h4>
      ${repHtml}
      <h4 style="margin:12px 0 6px;color:#14532D;">📜 એડમિન કાર્યવાહી ઇતિહાસ (${history.length})</h4>
      ${histHtml}
    `);
  }

  function openBlockModal(id, name) {
    openModal(`🚫 મુકાદમ બ્લોક કરો: ${escHtml(name)} (#${id})`, `
      <p style="font-size:13px;color:#B91C1C;margin-bottom:10px;font-weight:700;">
        ચેતવણી: બ્લોક કર્યા પછી આ મુકાદમ Public Search માં દેખાશે નહીં અને પોતાનું સ્ટેટસ બદલી શકશે નહીં.
      </p>
      <div class="form-group">
        <label>બ્લોક કરવાનું કારણ (Reason) *</label>
        <input id="blkReason" class="form-control" type="text" placeholder="દા.ત. ખેડૂતની ફરિયાદ ચકાસણી બાદ બ્લોક" required />
      </div>
      <div class="form-group">
        <label>એડમિન નોંધ (Admin Note)</label>
        <input id="blkNote" class="form-control" type="text" placeholder="આંતરિક નોંધ..." />
      </div>
      <div class="form-group">
        <label>બ્લોક અવધિ કલાકમાં (વૈકલ્પિક - કાયમી બ્લોક માટે ખાલી રાખો)</label>
        <input id="blkHours" class="form-control" type="number" min="1" placeholder="દા.ત. 48" />
      </div>
      <button class="btn btn-danger" style="width:100%;justify-content:center;" onclick="submitBlock(${id})">🚫 પુષ્ટિ કરો અને બ્લોક કરો</button>
    `);
  }

  async function submitBlock(id) {
    const reason = document.getElementById("blkReason").value.trim();
    const admin_note = document.getElementById("blkNote").value.trim();
    const hours = Number(document.getElementById("blkHours").value || 0);
    const expires_at = hours > 0 ? (Date.now() / 1000 + hours * 3600) : null;
    const { data } = await apiFetch(`/api/v1/admin/mukadams/${id}/block`, {
      method: "POST",
      body: JSON.stringify({ reason, admin_note, expires_at })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    showToast(data.message_gu);
    loadOverview();
    loadMukadams(mukPage);
  }

  function openUnblockModal(id, name) {
    openModal(`✅ મુકાદમ અનબ્લોક કરો: ${escHtml(name)} (#${id})`, `
      <div class="form-group">
        <label>અનબ્લોક કરવાનું કારણ *</label>
        <input id="unblkReason" class="form-control" type="text" value="ચકાસણી પૂર્ણ થતાં ફરી સક્રિય કર્યા" />
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center;" onclick="submitUnblock(${id})">✅ અનબ્લોક કરો</button>
    `);
  }

  async function submitUnblock(id) {
    const reason = document.getElementById("unblkReason").value.trim();
    const { data } = await apiFetch(`/api/v1/admin/mukadams/${id}/unblock`, {
      method: "POST",
      body: JSON.stringify({ reason })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    showToast(data.message_gu);
    loadOverview();
    loadMukadams(mukPage);
  }

  function openSoftDeleteModal(id, name) {
    openModal(`🗑️ Soft Delete કરો: ${escHtml(name)} (#${id})`, `
      <p style="font-size:13px;margin-bottom:10px;">Soft Delete કરવાથી પ્રોફાઇલ Public Search માંથી દૂર થશે પરંતુ રેકોર્ડ અને ફરિયાદ ઇતિહાસ સુરક્ષિત રહેશે.</p>
      <div class="form-group">
        <label>Soft Delete કરવાનું કારણ *</label>
        <input id="sdReason" class="form-control" type="text" placeholder="કારણ લખો..." />
      </div>
      <button class="btn btn-danger" style="width:100%;justify-content:center;" onclick="submitSoftDelete(${id})">🗑️ Soft Delete કરો</button>
    `);
  }

  async function submitSoftDelete(id) {
    const reason = document.getElementById("sdReason").value.trim();
    const { data } = await apiFetch(`/api/v1/admin/mukadams/${id}/soft-delete`, {
      method: "POST",
      body: JSON.stringify({ reason })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    showToast(data.message_gu);
    loadOverview();
    loadMukadams(mukPage);
  }

  async function restoreMukadamAction(id) {
    const { data } = await apiFetch(`/api/v1/admin/mukadams/${id}/restore`, {
      method: "POST",
      body: JSON.stringify({ reason: "Admin panel restore" })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    showToast(data.message_gu);
    loadOverview();
    loadMukadams(mukPage);
  }

  function openPermDeleteModal(id, name, mobile) {
    openModal(`⚠️ કાયમી ડિલીટ (Permanent Delete): #${id}`, `
      <div class="alert-msg alert-error">
        આ પ્રક્રિયા ઉલટાવી શકાશે નહીં! કાયમી ડિલીટ માટે તમારો Admin પાસવર્ડ અને મુકાદમનો મોબાઇલ નંબર (${escHtml(mobile)}) અથવા નામ લખવું ફરજિયાત છે.
      </div>
      <div class="form-group">
        <label>૧. મુકાદમનો મોબાઇલ નંબર અથવા નામ લખી ઓળખ ચકાસો *</label>
        <input id="pdConfirmId" class="form-control" type="text" placeholder="${escHtml(mobile)}" />
      </div>
      <div class="form-group">
        <label>૨. કાયમી ડિલીટ કરવાનું કારણ (ઓછામાં ઓછા ૫ અક્ષર) *</label>
        <input id="pdReason" class="form-control" type="text" placeholder="સ્પષ્ટ કારણ..." />
      </div>
      <div class="form-group">
        <label>૩. તમારો Admin પાસવર્ડ (Re-authentication) *</label>
        <input id="pdPassword" class="form-control" type="password" placeholder="તમારો પાસવર્ડ..." />
      </div>
      <button class="btn btn-danger" style="width:100%;justify-content:center;" onclick="submitPermDelete(${id})">⚠️ કાયમી ડિલીટ કરો</button>
    `);
  }

  async function submitPermDelete(id) {
    const confirm_mobile_or_name = document.getElementById("pdConfirmId").value.trim();
    const reason = document.getElementById("pdReason").value.trim();
    const admin_password = document.getElementById("pdPassword").value;
    const { data } = await apiFetch(`/api/v1/admin/mukadams/${id}/permanent`, {
      method: "DELETE",
      body: JSON.stringify({ confirm_mobile_or_name, reason, admin_password })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    showToast(data.message_gu);
    loadOverview();
    loadMukadams(mukPage);
  }

  async function loadReports(page = 1) {
    const st = document.getElementById("fltReportStatus").value;
    const { data } = await apiFetch(`/api/v1/admin/reports?status_filter=${encodeURIComponent(st)}&page=${page}`);
    const tbody = document.getElementById("reportsTableBody");
    tbody.innerHTML = "";
    if (!data.ok || !data.reports.length) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:#64748B;">કોઈ ફરિયાદ મળી નથી.</td></tr>';
      return;
    }
    data.reports.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${Number(r.id)}</td>
        <td><strong>${escHtml(r.mukadam_name || ("ID #" + r.mukadam_id))}</strong><br><small>${escHtml(r.mukadam_mobile_masked)}</small></td>
        <td>${escHtml(r.report_type)}</td>
        <td>${escHtml(r.description)}</td>
        <td style="font-size:11.5px;">${fmtDate(r.created_at)}</td>
        <td><span class="badge ${r.status === 'PENDING' ? 'badge-pending' : 'badge-resolved'}">${escHtml(r.status)}</span></td>
        <td>${escHtml(r.reviewed_by || r.assigned_moderator || "-")}</td>
        <td><button class="btn btn-primary btn-sm" onclick="openReviewReportModal(${Number(r.id)}, '${escHtml(r.status)}')">⚖️ સમીક્ષા</button></td>
      `;
      tbody.appendChild(tr);
    });
  }

  function openReviewReportModal(reportId, currentStatus) {
    openModal(`⚖️ ફરિયાદ #${reportId} ની સમીક્ષા અને નિર્ણય`, `
      <div class="form-group">
        <label>નવું સ્ટેટસ પસંદ કરો *</label>
        <select id="revStatus" class="form-control">
          <option value="UNDER_REVIEW" ${currentStatus==='UNDER_REVIEW'?'selected':''}>UNDER_REVIEW (તપાસ હેઠળ)</option>
          <option value="VERIFIED" ${currentStatus==='VERIFIED'?'selected':''}>VERIFIED (ફરિયાદ સાચી છે)</option>
          <option value="RESOLVED" ${currentStatus==='RESOLVED'?'selected':''}>RESOLVED (ઉકેલાઈ ગઈ)</option>
          <option value="REJECTED" ${currentStatus==='REJECTED'?'selected':''}>REJECTED (ખોટી ફરિયાદ / રદ)</option>
        </select>
      </div>
      <div class="form-group">
        <label>એડમિન નોંધ (Admin Notes)</label>
        <input id="revNotes" class="form-control" type="text" placeholder="તપાસની નોંધ..." />
      </div>
      <div class="form-group">
        <label>નિરાકરણ વિગત (Resolution Details)</label>
        <input id="revResolution" class="form-control" type="text" placeholder="શું પગલાં લેવાયા..." />
      </div>
      <div class="form-group" style="display:flex;align-items:center;gap:8px;">
        <input id="revAlsoBlock" type="checkbox" />
        <label for="revAlsoBlock" style="margin:0;color:#B91C1C;">આ મુકાદમને તાત્કાલિક બ્લોક પણ કરો</label>
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center;" onclick="submitReportReview(${reportId})">✅ નિર્ણય સેવ કરો</button>
    `);
  }

  async function submitReportReview(reportId) {
    const new_status = document.getElementById("revStatus").value;
    const admin_notes = document.getElementById("revNotes").value.trim();
    const resolution_details = document.getElementById("revResolution").value.trim();
    const also_block_mukadam = document.getElementById("revAlsoBlock").checked;
    const { data } = await apiFetch(`/api/v1/admin/reports/${reportId}/review`, {
      method: "POST",
      body: JSON.stringify({ new_status, admin_notes, resolution_details, also_block_mukadam })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    showToast(data.message_gu);
    loadOverview();
    loadReports(1);
  }

  async function loadAuditLogs(page = 1) {
    const act = document.getElementById("fltAuditAction").value.trim();
    const { data } = await apiFetch(`/api/v1/admin/audit-logs?action_filter=${encodeURIComponent(act)}&page=${page}`);
    const tbody = document.getElementById("auditTableBody");
    tbody.innerHTML = "";
    if (!data.ok) return;
    const badge = document.getElementById("auditChainBadge");
    if (data.chain_verified) {
      badge.className = "badge badge-active";
      badge.textContent = "🔒 Immutable Hash-Chain Verified (Tamper-Evident OK)";
    } else {
      badge.className = "badge badge-blocked";
      badge.textContent = "⚠️ Chain Integrity Alert!";
    }
    data.logs.forEach(l => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${Number(l.id)}</td>
        <td style="font-size:11.5px;">${fmtDate(l.timestamp)}</td>
        <td><strong>${escHtml(l.admin_username)}</strong><br><small>${escHtml(l.admin_role)}</small></td>
        <td><strong>${escHtml(l.action)}</strong></td>
        <td>${escHtml(l.target_type)} #${escHtml(l.target_id)}</td>
        <td><span class="badge ${l.result==='SUCCESS'?'badge-active':'badge-blocked'}">${escHtml(l.result)}</span></td>
        <td style="font-size:12px;">${escHtml(l.reason)}</td>
        <td style="font-family:monospace;font-size:11px;">${escHtml((l.entry_hash || "").slice(0, 14))}...</td>
      `;
      tbody.appendChild(tr);
    });
  }

  async function loadAdminUsers() {
    const { data } = await apiFetch("/api/v1/admin/users");
    const tbody = document.getElementById("adminsTableBody");
    tbody.innerHTML = "";
    if (!data.ok) return;
    data.admins.forEach(a => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${Number(a.id)}</td>
        <td><strong>${escHtml(a.username)}</strong></td>
        <td>${escHtml(a.display_name)}</td>
        <td><span class="badge badge-resolved">${escHtml(a.role)}</span></td>
        <td>${a.is_active ? "🟢 Active" : "🔴 Disabled"}</td>
        <td>${fmtDate(a.last_login_at)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function openAdminUserModal() {
    openModal("🔐 એડમિન યુઝર ઉમેરો / રોલ અપડેટ કરો", `
      <div class="form-group">
        <label>Username *</label>
        <input id="auUser" class="form-control" type="text" placeholder="e.g. moderator_gir" />
      </div>
      <div class="form-group">
        <label>Display Name *</label>
        <input id="auName" class="form-control" type="text" placeholder="દા.ત. ગીર સોમનાથ મોડરેટર" />
      </div>
      <div class="form-group">
        <label>Role *</label>
        <select id="auRole" class="form-control">
          <option value="MODERATOR">MODERATOR (ફરિયાદ તપાસ અને બ્લોક/અનબ્લોક)</option>
          <option value="VIEWER">VIEWER (ફક્ત યાદી જોવી)</option>
          <option value="SUPER_ADMIN">SUPER_ADMIN (તમામ અધિકાર)</option>
        </select>
      </div>
      <div class="form-group">
        <label>પાસવર્ડ (ઓછામાં ઓછા ૧૦ અક્ષર)</label>
        <input id="auPass" class="form-control" type="password" placeholder="નવા એડમિન માટે ફરજિયાત..." />
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center;" onclick="submitAdminUser()">💾 સેવ કરો</button>
    `);
  }

  async function submitAdminUser() {
    const username = document.getElementById("auUser").value.trim();
    const display_name = document.getElementById("auName").value.trim();
    const role = document.getElementById("auRole").value;
    const password = document.getElementById("auPass").value;
    const { data } = await apiFetch("/api/v1/admin/users", {
      method: "POST",
      body: JSON.stringify({ username, display_name, role, password: password || null, is_active: true })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    showToast(data.message_gu);
    loadAdminUsers();
  }

  function openResetModal() {
    openModal("🔑 Admin પાસવર્ડ રીસેટ (Master Secret વડે)", `
      <div class="form-group">
        <label>Admin Username *</label>
        <input id="rstUser" class="form-control" type="text" />
      </div>
      <div class="form-group">
        <label>Render ADMIN_RESET_MASTER_SECRET *</label>
        <input id="rstSecret" class="form-control" type="password" />
      </div>
      <div class="form-group">
        <label>નવો પાસવર્ડ (ઓછામાં ઓછા ૧૦ અક્ષર) *</label>
        <input id="rstNewPass" class="form-control" type="password" />
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center;" onclick="submitPasswordReset()">🔑 પાસવર્ડ બદલો</button>
    `);
  }

  async function submitPasswordReset() {
    const username = document.getElementById("rstUser").value.trim();
    const master_secret = document.getElementById("rstSecret").value;
    const new_password = document.getElementById("rstNewPass").value;
    const { data } = await apiFetch("/api/v1/admin/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ username, master_secret, new_password })
    });
    if (!data.ok) return alert(data.detail || data.message_gu);
    closeModal();
    alert(data.message_gu);
  }

  async function downloadCsv() {
    const resp = await fetch("/api/mukadam/export_csv", {
      headers: { "Authorization": "Bearer " + sessionToken }
    });
    if (!resp.ok) return showToast("CSV ડાઉનલોડ માટે પરવાનગી નથી.", true);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "gujarat_mukadam_list.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function triggerBackup() {
    const { data } = await apiFetch("/api/v1/admin/backup", { method: "POST", body: "{}" });
    if (!data.ok) return showToast(data.detail || data.message_gu || "બેકઅપ નિષ્ફળ", true);
    showToast("SQLite બેકઅપ સફળતાપૂર્વક બની ગયો (" + data.size_bytes + " bytes)");
  }

  function openModal(title, html) {
    document.getElementById("modalTitle").textContent = title;
    document.getElementById("modalBody").innerHTML = html;
    document.getElementById("modalBackdrop").classList.remove("hidden");
  }

  function closeModal() {
    document.getElementById("modalBackdrop").classList.add("hidden");
  }

  // Restore session if active
  (async function init() {
    if (sessionToken) {
      const { data } = await apiFetch("/api/v1/admin/auth/me");
      if (data && data.ok) {
        currentAdmin = data.admin;
        csrfToken = data.csrf_token || csrfToken;
        enterDashboard();
      } else {
        clearSession();
      }
    }
  })();
</script>
</body>
</html>
"""
