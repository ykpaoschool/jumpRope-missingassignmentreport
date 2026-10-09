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
  renderEmailColumn(s);
}

// ---- 收件邮箱列 ----
function columnLabel(c) {
  const name = c.header ? ` · ${c.header}` : "";
  const count = c.email_count ? `${c.email_count} 条邮箱` : "无有效邮箱";
  return `${c.letter} 列${name}（${count}）`;
}

// 所选列可能不在候选里（例如表头没有邮箱关键词时回退到 N 列），必须把它补进选项，
// 否则下拉框上显示的和实际使用的不是同一列。
function emailColumnOptions(data) {
  const list = Array.isArray(data.email_columns) ? data.email_columns.slice() : [];
  const info = data.email_column_info;
  if (info && !list.some((c) => c.index === info.index)) list.push(info);
  return list.sort((a, b) => a.index - b.index);
}

// 表头「收件人」下方标注实际取自 Excel 的哪个字段，随收件列一起更新
let currentEmailColumn = null;

function renderEmailColumnHeader() {
  const info = currentEmailColumn;
  $("th-email-sub").textContent = !info ? "" : info.header || `${info.letter} 列（无表头）`;
}

function renderEmailColumn(data) {
  currentEmailColumn = data.uploaded ? data.email_column_info || null : null;
  renderEmailColumnHeader();

  const row = $("email-column-row");
  if (!data.uploaded) {
    row.classList.add("hidden");
    return;
  }
  row.classList.remove("hidden");

  const select = $("email-column-select");
  const staticEl = $("email-column-static");
  const options = emailColumnOptions(data);

  if (options.length <= 1) {
    // 只有一列可选时不放控件，但仍要说明用的是哪一列——这一步以前是看不见的黑盒
    staticEl.textContent = options.length
      ? columnLabel(options[0])
      : "未识别到邮箱列，无法发送（详见下方提示）";
    staticEl.classList.remove("hidden");
    select.classList.add("hidden");
    return;
  }

  select.innerHTML = "";
  for (const c of options) select.appendChild(el("option", { value: String(c.index), text: columnLabel(c) }));
  select.value = String(data.email_column);
  select.disabled = jobRunning;
  staticEl.classList.add("hidden");
  select.classList.remove("hidden");
}

async function changeEmailColumn() {
  const select = $("email-column-select");
  select.disabled = true;
  try {
    const summary = await api("/api/email-column", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ column: Number(select.value) }),
    });
    renderSummary(summary); // 摘要、警告、控件本身按新列一起刷新
    await loadStudents();
  } catch (e) {
    alert(e.message);
    select.disabled = jobRunning;
  }
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
  restoredView = false; // 接下来展示的是本次提交的任务，不再是历史结果
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
  // 发送中的任务已经对收件人做了快照，禁用选择器是为了不让待发送列表与正在发送的内容两说
  $("email-column-select").disabled = busy;
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
      const hadRun = jobRunning; // stopPolling() 会把它清掉，先留个记号
      stopPolling();
      setSendButton(false);
      // 刚刚跑完一批：第 4 节自动跟着刷新，省得用户还以为要手点一下
      if (hadRun) loadLogs();
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

// 页面打开时恢复的、已结束的历史任务：必须与本次会话刚发出的结果区分显示，
// 否则刚打开页面就看到一屏绿色对勾，会误以为邮件是自己刚发的。
let restoredView = false;

function renderJob(job) {
  if (!job) return;
  // 结果列表可能来自旧版本或被截断，永远按数组处理，避免整页脚本被打断
  const results = Array.isArray(job.results) ? job.results : [];
  const running = job.status === "running";
  const historical = restoredView && !running;
  const done = job.sent + job.failed;
  const pct = job.total ? Math.round((done / job.total) * 100) : 0;

  $("progress-bar").style.width = `${pct}%`;
  $("progress-count").textContent = `已发送 ${job.sent} / ${job.total} · 失败 ${job.failed}`;

  const label = $("progress-label");
  if (running) {
    label.textContent = job.current ? `正在发送：${job.current}` : "正在发送…";
  } else if (historical) {
    label.textContent = `上次发送 · ${job.finished_at || ""} 结束`;
  } else if (job.status === "failed") {
    label.textContent = "发送中断";
  } else {
    label.textContent = "发送完成";
  }

  const prog = $("send-progress");
  prog.classList.remove("hidden");
  prog.classList.toggle("done", job.status === "done" && !historical);
  prog.classList.toggle("failed", job.status === "failed" && !historical);
  prog.classList.toggle("history", historical);

  const box = $("send-result");
  box.classList.remove("hidden");
  box.classList.toggle("history", historical);
  box.innerHTML = "";

  let head;
  if (running) {
    head = `<div>发送中：成功 <span class="ok">${job.sent}</span> 封，失败 <span class="fail">${job.failed}</span> 封（共 ${job.total} 封）。</div>`;
  } else if (job.status === "failed") {
    head = `<div class="fail">${historical ? `上次发送（${esc(job.started_at || "")}）未开始` : "整批发送未开始"}：${esc(job.error || "未知错误")}</div>`;
  } else if (historical) {
    head = `<div>上次发送结果（${esc(job.finished_at || "")} 完成）：成功 <span class="ok">${job.sent}</span> 封，失败 <span class="fail">${job.failed}</span> 封。</div>`;
  } else {
    head = `<div>发送完成：成功 <span class="ok">${job.sent}</span> 封，失败 <span class="fail">${job.failed}</span> 封。</div>`;
  }
  const headNode = el("div", { class: "result-head", html: head });
  box.appendChild(headNode);

  if (!results.length) return;

  const detail = el("div", { class: "result-detail" });
  detail.innerHTML = results
    .map(
      (x) =>
        `<div>${x.ok ? '<span class="ok">✓</span>' : '<span class="fail">✗</span>'} 学生 ${esc(x.student_id)} → ${esc(x.to)}${x.ok ? "" : `　<span class="fail">${esc(x.error)}</span>`}</div>`
    )
    .join("");

  const toggle = el("button", { class: "btn btn-ghost btn-small" });
  const syncToggle = () => {
    toggle.textContent = detail.classList.contains("hidden") ? `展开明细（${results.length} 条）` : "收起明细";
  };
  toggle.addEventListener("click", () => {
    detail.classList.toggle("hidden");
    syncToggle();
  });
  headNode.appendChild(toggle);
  detail.classList.toggle("hidden", historical); // 历史结果默认折叠
  syncToggle();
  box.appendChild(detail);
}

// ---- 发送日志（SQLite，跨重启保留）----
const LOG_LIMIT = 200;

// 日志行只需要时分秒：日期由上面的下拉框决定了
function logTime(ts) {
  return String(ts || "").slice(11) || String(ts || "");
}

function logModeChannel(e) {
  return `${e.mode === "live" ? "正式" : "测试"} · ${e.channel === "smtp" ? "SMTP" : "Graph"}`;
}

// job_start / job_end 是整批级别的事件，跨列成一行灰底小字，与逐封记录区分
function logEventRow(e) {
  const parts = [];
  if (e.event === "job_start") {
    parts.push(`任务开始 · 共 ${e.total == null ? "?" : e.total} 封 · ${logModeChannel(e)}`);
    if (e.filename) parts.push(`文件 ${e.filename}`);
    if (e.email_column_header) parts.push(`收件列 ${e.email_column_header}`);
    else if (e.email_column != null) parts.push(`收件列第 ${Number(e.email_column) + 1} 列`);
  } else if (e.status === "failed") {
    // 整批在连接阶段就失败：一封都没发出去，这条行就是它在日志里的唯一痕迹
    parts.push(`任务未开始（整批发送失败）· ${logModeChannel(e)}`, e.error || "未知错误");
  } else {
    parts.push(`任务结束 · ${logModeChannel(e)} · 成功 ${e.sent || 0} 封 / 失败 ${e.failed || 0} 封`);
    if (e.duration_ms != null) parts.push(`用时 ${(e.duration_ms / 1000).toFixed(1)} 秒`);
  }
  return el("tr", { class: "log-event" }, [
    el("td", { colspan: "7", text: `${logTime(e.ts)}　${parts.join("　|　")}` }),
  ]);
}

function logSendRow(e) {
  const ok = Number(e.ok) === 1;
  const who = e.student_name ? `${e.student_name}（${e.student_id}）` : e.student_id || "—";
  const klass = [e.grade, e.class_name].filter(Boolean).join(" / ") || "—";
  return el("tr", {}, [
    el("td", { class: "log-nowrap", text: logTime(e.ts) }),
    el("td", { class: ok ? "log-ok log-nowrap" : "log-fail log-nowrap", text: ok ? "✓ 成功" : "✗ 失败" }),
    el("td", { text: who }),
    el("td", { class: "log-nowrap", text: klass }),
    el("td", { text: e.recipient || "" }),
    el("td", { class: "log-nowrap", text: logModeChannel(e) }),
    // 成功看主题、失败看原因：同一列里放「这封是什么/为什么没发出去」
    el("td", { class: ok ? "" : "log-fail", text: ok ? e.subject || "" : e.error || "未知错误" }),
  ]);
}

function renderLogs(data) {
  const dbInfo = data.db || {};
  const errBox = $("log-error");
  errBox.innerHTML = "";
  if (!dbInfo.ready) {
    // 日志写不进去不影响发信，但必须说出来——否则会以为记录只是「还没刷新出来」
    errBox.appendChild(
      el("li", {
        text:
          `发送日志不可用：${dbInfo.error || "未知原因"}（库文件：${dbInfo.path || "未知"}）。` +
          "写入失败不会影响发信，但这些记录不会留存。",
      })
    );
  }

  const current = data.date || "";
  const options = Array.isArray(data.dates) ? data.dates.slice() : [];
  if (current && options.indexOf(current) === -1) options.unshift(current); // 指定的日期即使当天无记录也要能显示
  const sel = $("log-date");
  sel.innerHTML = "";
  for (const d of options) sel.appendChild(el("option", { value: d, text: d }));
  if (current) sel.value = current;
  sel.classList.toggle("hidden", options.length === 0);

  const c = data.counts || {};
  let hint = `当日：投递 ${c.send || 0} 封（成功 ${c.ok || 0}，失败 ${c.failed || 0}）· 整批 ${c.jobs || 0} 次`;
  if (data.truncated) hint += `　|　仅显示最近 ${data.entries.length} 条`;
  $("log-hint").textContent = hint;

  const tbody = $("log-tbody");
  tbody.innerHTML = "";
  const entries = Array.isArray(data.entries) ? data.entries : [];
  if (!entries.length) {
    tbody.appendChild(el("tr", {}, [el("td", { colspan: "7", class: "empty", text: "当日无发送记录" })]));
    return;
  }
  for (const e of entries) tbody.appendChild(e.event === "send" ? logSendRow(e) : logEventRow(e));
}

async function loadLogs() {
  // 日期留空 = 让服务端给最近有记录的一天（初次打开页面时用）
  const params = new URLSearchParams({ ok: $("log-ok").value, limit: String(LOG_LIMIT) });
  if ($("log-date").value) params.set("date", $("log-date").value);
  try {
    renderLogs(await api(`/api/logs?${params.toString()}`));
  } catch (e) {
    const tbody = $("log-tbody");
    tbody.innerHTML = "";
    tbody.appendChild(
      el("tr", {}, [el("td", { colspan: "7", class: "empty", text: `发送日志读取失败：${e.message}` })])
    );
  }
}

// 页面打开时先查一次：任务还在跑就接着轮询，已结束就作为「上次发送」展示
async function restoreSendState() {
  try {
    const data = await api("/api/send/status");
    const job = data.job;
    if (!job) return;
    restoredView = job.status !== "running";
    renderJob(job);
    if (!restoredView) startPolling();
  } catch (e) {
    // 恢复失败不影响其他功能，静默忽略
  }
}

// 解析结果同样存在服务端内存里，刷新页面不该要求重新上传一遍文件
async function restoreParsed() {
  try {
    const s = await api("/api/summary");
    if (!s.uploaded) return;
    renderSummary(s);
    await loadStudents();
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
$("email-column-select").addEventListener("change", changeEmailColumn);
$("log-date").addEventListener("change", loadLogs);
$("log-ok").addEventListener("change", loadLogs);
$("btn-log-refresh").addEventListener("click", loadLogs);
$("student-tbody").addEventListener("change", (e) => {
  if (e.target.classList.contains("row-check")) syncCheckAll();
});
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", syncTestEmailRow));

refreshStatus();
syncTestEmailRow();
restoreSendState();
restoreParsed();
loadLogs();
