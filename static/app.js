"use strict";

let students = [];

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.appendChild(c);
  return node;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || data.error || `请求失败 (${resp.status})`);
  return data;
}

// ---- 连接状态 ----
async function refreshStatus() {
  const badge = $("conn-status");
  try {
    const s = await api("/api/status");
    const parts = [];
    if (s.configured) parts.push(`Graph: ${s.shared_mailbox}`);
    if (s.smtp_configured) parts.push(`SMTP: ${s.smtp_host}`);
    if (parts.length) {
      badge.textContent = parts.join(" ｜ ");
      badge.className = "badge ok";
    } else {
      badge.textContent = "未配置发信渠道";
      badge.className = "badge err";
    }
  } catch (e) {
    badge.textContent = "状态获取失败";
    badge.className = "badge err";
  }
}

async function testConnection() {
  const badge = $("conn-status");
  badge.textContent = "测试中…";
  badge.className = "badge";
  try {
    const r = await api("/api/test-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: currentChannel() }),
    });
    if (r.ok) {
      badge.textContent = `连接成功 · ${r.mailbox}`;
      badge.className = "badge ok";
    } else {
      badge.textContent = `连接失败：${r.error || r.status}`;
      badge.className = "badge err";
      alert(`连接失败：\n${r.error || r.status}`);
    }
  } catch (e) {
    badge.textContent = "连接失败";
    badge.className = "badge err";
    alert(e.message);
  }
}

// ---- 上传 ----
async function upload() {
  const input = $("file-input");
  if (!input.files.length) return alert("请先选择 Excel 文件");
  const fd = new FormData();
  fd.append("file", input.files[0]);
  $("btn-upload").disabled = true;
  try {
    const summary = await api("/api/upload", { method: "POST", body: fd });
    renderSummary(summary);
    await loadStudents();
  } catch (e) {
    alert(e.message);
  } finally {
    $("btn-upload").disabled = false;
  }
}

function renderSummary(s) {
  const box = $("summary");
  box.classList.remove("hidden");
  box.innerHTML =
    `共 <span class="num">${s.total_students}</span> 名学生，` +
    `<span class="num">${s.with_email}</span> 名有家长邮箱，` +
    `<span class="num">${s.no_email.length}</span> 名缺邮箱，` +
    `共 <span class="num">${s.total_items}</span> 条缺交记录`;
  const w = $("warnings");
  w.innerHTML = "";
  for (const msg of s.warnings || []) w.appendChild(el("li", { text: msg }));
}

// ---- 学生列表 ----
async function loadStudents() {
  students = await api("/api/students");
  renderTable();
}

function renderTable() {
  const tbody = $("student-tbody");
  tbody.innerHTML = "";
  if (!students.length) {
    tbody.appendChild(el("tr", {}, [el("td", { colspan: "7", class: "empty", text: "尚未上传文件" })]));
    return;
  }
  for (const s of students) {
    const cb = el("input", { type: "checkbox", "data-id": s.student_id, class: "row-check" });
    cb.checked = !s.parent_email ? false : true;
    cb.disabled = !s.parent_email;
    const btn = el("button", { class: "btn btn-ghost", text: "预览" });
    btn.addEventListener("click", () => preview(s.student_id));
    const tr = el("tr", s.parent_email ? {} : { class: "no-email" }, [
      el("td", {}, [cb]),
      el("td", { text: s.student_id }),
      el("td", { text: s.grade }),
      el("td", { text: s["class"] }),
      el("td", { text: s.parent_email || "（缺邮箱）" }),
      el("td", { text: s.item_count }),
      el("td", {}, [btn]),
    ]);
    tbody.appendChild(tr);
  }
  syncCheckAll();
}

function selectedIds() {
  return [...document.querySelectorAll(".row-check:checked")].map((c) => c.dataset.id);
}

function syncCheckAll() {
  const all = [...document.querySelectorAll(".row-check:not(:disabled)")];
  const checked = all.filter((c) => c.checked);
  $("check-all").checked = all.length > 0 && checked.length === all.length;
}

// ---- 预览 ----
async function preview(id) {
  const r = await api(`/api/preview/${encodeURIComponent(id)}`);
  $("preview-title").textContent = `预览 · 学生 ${r.student_id}`;
  $("preview-subject").textContent = `主题：${r.subject}　|　收件人：${r.parent_email}`;
  const frame = $("preview-frame");
  frame.srcdoc = r.html;
  $("preview-modal").classList.remove("hidden");
}

// ---- 发送 ----
function currentMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function currentChannel() {
  return document.querySelector('input[name="channel"]:checked').value;
}

function syncTestEmailRow() {
  $("test-email-row").style.display = currentMode() === "test" ? "flex" : "none";
}

async function send() {
  const mode = currentMode();
  const ids = selectedIds();
  const testEmail = $("test-email").value.trim();

  if (mode === "test" && !testEmail) return alert("测试模式需填写测试邮箱");

  let confirmMsg;
  if (mode === "test") {
    confirmMsg = `测试模式：将把${ids.length ? `选中的 ${ids.length} 名学生` : "1 名样例学生"}的邮件发送到测试邮箱 ${testEmail}。继续？`;
  } else {
    confirmMsg = `正式发送：将向${ids.length ? `选中的 ${ids.length} 名` : `全部 ${students.filter((s) => s.parent_email).length} 名`}学生的家长邮箱发送邮件。此操作不可撤销，确认继续？`;
  }
  if (!confirm(confirmMsg)) return;

  const body = { mode, channel: currentChannel(), test_email: testEmail || null };
  if (ids.length) body.student_ids = ids;

  const btn = $("btn-send");
  btn.disabled = true;
  btn.textContent = "发送中…";
  const box = $("send-result");
  box.classList.add("hidden");
  try {
    const r = await api("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    box.classList.remove("hidden");
    box.innerHTML =
      `<div>发送完成：成功 <span class="ok">${r.sent}</span> 封，失败 <span class="fail">${r.failed}</span> 封。</div>` +
      r.results
        .map(
          (x) =>
            `<div>${x.ok ? '<span class="ok">✓</span>' : '<span class="fail">✗</span>'} 学生 ${esc(x.student_id)} → ${esc(x.to)}${x.ok ? "" : `　<span class="fail">${esc(x.error)}</span>`}</div>`
        )
        .join("");
  } catch (e) {
    box.classList.remove("hidden");
    box.innerHTML = `<div class="fail">发送失败：${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "发送";
  }
}

// ---- 绑定事件 ----
$("btn-upload").addEventListener("click", upload);
$("btn-test-conn").addEventListener("click", testConnection);
$("btn-send").addEventListener("click", send);
$("btn-close-preview").addEventListener("click", () => $("preview-modal").classList.add("hidden"));
$("preview-modal").addEventListener("click", (e) => {
  if (e.target === $("preview-modal")) $("preview-modal").classList.add("hidden");
});
$("check-all").addEventListener("change", (e) => {
  document.querySelectorAll(".row-check:not(:disabled)").forEach((c) => (c.checked = e.target.checked));
});
$("student-tbody").addEventListener("change", (e) => {
  if (e.target.classList.contains("row-check")) syncCheckAll();
});
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", syncTestEmailRow));

refreshStatus();
syncTestEmailRow();
