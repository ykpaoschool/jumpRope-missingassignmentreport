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
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const err = new Error((data && (data.detail || data.error)) || `请求失败 (${resp.status})`);
    err.status = resp.status;
    throw err;
  }
  if (data === null) {
    // 反代错误页之类的非 JSON 响应：报清楚，别让调用方读出不存在的字段
    throw new Error(`服务返回了非 JSON 响应 (${resp.status})，请强制刷新页面后重试`);
  }
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
    tbody.appendChild(el("tr", {}, [el("td", { colspan: "8", class: "empty", text: "尚未上传文件" })]));
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
      el("td", { text: s.student_name || "—" }),
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
  $("preview-title").textContent = `预览 · 学生 ${r.student_id}${r.student_name ? ` ${r.student_name}` : ""}`;
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

  setSendButton(true);
  $("send-progress").classList.add("hidden");
  $("send-result").classList.add("hidden");
  try {
    // 202：任务已在后台启动，真正的进度靠轮询拿
    const r = await api("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.job_id) {
      // 接口返回了 2xx 却没有任务信息：多半是前端已更新、后端还是旧版本
      const box = $("send-result");
      box.classList.remove("hidden");
      box.innerHTML =
        '<div class="fail">服务端未返回发送任务信息。可能是服务端仍是旧版本，' +
        "请重启服务后强制刷新页面（Cmd/Ctrl+Shift+R）再试。</div>";
      setSendButton(false);
      return;
    }
    startPolling();
  } catch (e) {
    setSendButton(false);
    if (e.status === 409) {
      // 已有任务在跑：把它的进度接过来显示，而不是干瞪眼
      startPolling();
      return;
    }
    const box = $("send-result");
    box.classList.remove("hidden");
    box.innerHTML = `<div class="fail">发送失败：${esc(e.message)}</div>`;
  }
}

// ---- 发送进度 ----
const POLL_INTERVAL_MS = 1000;
const MAX_POLL_FAILURES = 5;

let pollTimer = null;
let pollInFlight = false;
let pollFailures = 0;
let jobRunning = false;

function setSendButton(busy) {
  const btn = $("btn-send");
  btn.disabled = busy;
  btn.textContent = busy ? "发送中…" : "发送";
}

function startPolling() {
  jobRunning = true;
  setSendButton(true);
  if (pollTimer) return;
  pollStatus();
  pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  jobRunning = false;
}

async function pollStatus() {
  if (pollInFlight) return; // 上一次请求还没回来，跳过这一轮
  pollInFlight = true;
  try {
    const data = await api("/api/send/status");
    pollFailures = 0;
    renderJob(data.job);
    if (!data.job || data.job.status !== "running") {
      stopPolling();
      setSendButton(false);
    }
  } catch (e) {
    // 偶发失败（例如网络抖动）继续轮询；连续失败说明服务不可用，停下来别刷屏
    if (++pollFailures >= MAX_POLL_FAILURES) {
      stopPolling();
      setSendButton(false);
      const box = $("send-result");
      box.classList.remove("hidden");
      box.innerHTML = `<div class="fail">无法获取发送进度：${esc(e.message)}</div>`;
    }
  } finally {
    pollInFlight = false;
  }
}

function renderJob(job) {
  if (!job) return;
  // 结果列表可能来自旧版本或被截断，永远按数组处理，避免整页脚本被打断
  const results = Array.isArray(job.results) ? job.results : [];
  const done = job.sent + job.failed;
  const pct = job.total ? Math.round((done / job.total) * 100) : 0;

  $("progress-bar").style.width = `${pct}%`;
  $("progress-count").textContent = `已发送 ${job.sent} / ${job.total} · 失败 ${job.failed}`;

  const label = $("progress-label");
  if (job.status === "running") {
    label.textContent = job.current ? `正在发送：${job.current}` : "正在发送…";
  } else if (job.status === "failed") {
    label.textContent = "发送中断";
  } else {
    label.textContent = "发送完成";
  }

  const prog = $("send-progress");
  prog.classList.remove("hidden");
  prog.classList.toggle("done", job.status === "done");
  prog.classList.toggle("failed", job.status === "failed");

  const box = $("send-result");
  box.classList.remove("hidden");
  let head;
  if (job.status === "running") {
    head = `<div>发送中：成功 <span class="ok">${job.sent}</span> 封，失败 <span class="fail">${job.failed}</span> 封（共 ${job.total} 封）。</div>`;
  } else if (job.status === "failed") {
    head = `<div class="fail">整批发送未开始：${esc(job.error || "未知错误")}</div>`;
  } else {
    head = `<div>发送完成：成功 <span class="ok">${job.sent}</span> 封，失败 <span class="fail">${job.failed}</span> 封。</div>`;
  }
  box.innerHTML =
    head +
    results
      .map(
        (x) =>
          `<div>${x.ok ? '<span class="ok">✓</span>' : '<span class="fail">✗</span>'} 学生 ${esc(x.student_id)} → ${esc(x.to)}${x.ok ? "" : `　<span class="fail">${esc(x.error)}</span>`}</div>`
      )
      .join("");
}

// 页面打开时先查一次：任务还在跑就接着轮询，已结束就展示最近一次结果
async function restoreSendState() {
  try {
    const data = await api("/api/send/status");
    const job = data.job;
    if (!job) return;
    renderJob(job);
    if (job.status === "running") startPolling();
  } catch (e) {
    // 恢复失败不影响其他功能，静默忽略
  }
}

window.addEventListener("beforeunload", (e) => {
  if (!jobRunning) return;
  e.preventDefault();
  e.returnValue = "发送任务正在进行中。关闭页面不会中断发送，但将无法实时查看进度，可重新打开页面继续查看。";
  return e.returnValue;
});

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
restoreSendState();
