/* ============================================================
   网易云音乐合伙人 · Web UI 逻辑
   后端：Python sidecar（HTTP + SSE）
   ============================================================ */
'use strict';

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const VERSION_FALLBACK = '2.0.0';
const MAX_LOGS = 5000;

const state = {
  backend: { base: '', token: '' },
  mode: 'unknown',          // tauri | browser
  meta: null,
  busy: false,
  kind: '',
  cancelRequested: false,
  username: '',
  stats: { daily: { count: 0, completed: 0 }, extra: { max: 15, done: 0 } },
  lastResult: null,
  logs: [],
  config: {},
  configDirty: false,
  history: [],
  selectedHistory: null,
  filter: 'ALL',
  search: '',
  es: null,
};

/* ------------------------------------------------------------------
   后端适配：Tauri 外壳 / 浏览器直连
   ------------------------------------------------------------------ */
async function initBackend() {
  const tauri = window.__TAURI__;
  if (tauri && tauri.core && tauri.core.invoke) {
    state.mode = 'tauri';
    for (let i = 0; i < 80; i++) {
      try {
        const info = await tauri.core.invoke('server_info');
        if (info && info.port) {
          state.backend = { base: `http://127.0.0.1:${info.port}`, token: info.token || '' };
          if (tauri.event && tauri.event.listen) {
            tauri.event.listen('sidecar-exit', () => {
              setConn('err', 'Python 后端已退出');
              toast('Python 后端进程已退出，请重启应用', 'err', 8000);
            });
          }
          return;
        }
      } catch (e) { /* 外壳尚未就绪，继续等待 */ }
      await sleep(250);
    }
    throw new Error('无法连接 Python 后端（sidecar 启动超时）');
  }

  if (window.__NCMP_EMBEDDED__) {
    state.mode = 'browser';
    state.backend = { base: location.origin, token: window.__NCMP_TOKEN__ || '' };
    return;
  }

  const url = new URL(location.href);
  const port = url.searchParams.get('port');
  const token = url.searchParams.get('token');
  if (port && token) {
    state.mode = 'browser';
    state.backend = { base: `http://127.0.0.1:${port}`, token };
    return;
  }
  throw new Error('未检测到 Python 后端：请从 ncmp 应用启动，或运行 python -m src.server 后访问其输出的地址');
}

async function api(path, { method = 'GET', body = null } = {}) {
  const res = await fetch(state.backend.base + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-NCMP-Token': state.backend.token,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* 可能为空响应 */ }
  if (!res.ok) {
    const msg = (data && (data.error || data.message)) || `请求失败 (HTTP ${res.status})`;
    throw new Error(msg);
  }
  return data;
}

/* ------------------------------------------------------------------
   提示 / 连接状态
   ------------------------------------------------------------------ */
function toast(message, type = 'info', ttl = 3600) {
  const el = document.createElement('div');
  el.className = `toast is-${type}`;
  const icon = type === 'ok' ? '✅' : type === 'err' ? '❌' : type === 'warn' ? '⚠️' : 'ℹ️';
  el.innerHTML = `<span>${icon}</span><span></span>`;
  el.lastElementChild.textContent = message;
  $('toasts').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .25s, transform .25s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 260);
  }, ttl);
}

function setConn(kind, text) {
  const dot = $('connState').firstElementChild;
  dot.className = `dot dot-${kind}`;
  $('connText').textContent = text || (kind === 'ok' ? '后端已连接' : kind === 'err' ? '后端断开' : '连接中…');
}

function showBanner(text, action) {
  const banner = $('banner');
  $('bannerText').textContent = text;
  const btn = $('bannerAction');
  if (action) {
    btn.hidden = false;
    btn.textContent = action.label;
    btn.onclick = action.onClick;
  } else {
    btn.hidden = true;
  }
  banner.hidden = false;
}

function hideBanner() { $('banner').hidden = true; }

function confirmDialog(title, body, okText = '确定') {
  return new Promise((resolve) => {
    $('modalTitle').textContent = title;
    $('modalBody').textContent = body;
    $('modalOk').textContent = okText;
    $('modalMask').hidden = false;
    const cleanup = () => {
      $('modalMask').hidden = true;
      $('modalOk').onclick = null;
      $('modalCancel').onclick = null;
      document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => { if (e.key === 'Escape') { cleanup(); resolve(false); } };
    document.addEventListener('keydown', onKey);
    $('modalOk').onclick = () => { cleanup(); resolve(true); };
    $('modalCancel').onclick = () => { cleanup(); resolve(false); };
  });
}

/* ------------------------------------------------------------------
   页面切换
   ------------------------------------------------------------------ */
const PAGE_TITLES = { run: '运行控制', config: '配置', history: '运行历史', about: '关于' };

function switchPage(page) {
  if (!PAGE_TITLES[page]) page = 'run';
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('is-active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('is-active', p.id === `page-${page}`));
  $('pageTitle').textContent = PAGE_TITLES[page];
  if (location.hash !== `#${page}`) {
    // 支持通过 #config / #history 直达对应页面
    window.history.replaceState(null, '', `#${page}`);
  }
  if (page === 'history') loadHistory();
}

/* ------------------------------------------------------------------
   状态渲染
   ------------------------------------------------------------------ */
function applyState(s) {
  if (!s) return;
  state.busy = !!s.busy;
  state.kind = s.kind || '';
  state.cancelRequested = !!s.cancel_requested;
  if (s.username) state.username = s.username;
  if (s.stats) state.stats = s.stats;
  if (s.last_result) state.lastResult = s.last_result;
  render();
}

function pct(done, total) {
  if (!total) return 0;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

function render() {
  const { daily, extra } = state.stats;
  const dailyTotal = daily.count || 5;
  const extraTotal = extra.max || 15;
  const dailyDone = Math.min(daily.completed || 0, dailyTotal);
  const extraDone = Math.min(extra.done || 0, extraTotal);

  $('dailyDone').textContent = dailyDone;
  $('dailyTotal').textContent = dailyTotal;
  $('extraDone').textContent = extraDone;
  $('extraTotal').textContent = extraTotal;
  $('dailyBar').style.width = `${pct(dailyDone, dailyTotal)}%`;
  $('extraBar').style.width = `${pct(extraDone, extraTotal)}%`;

  $('nickname').textContent = state.username || '-';

  // 顶部状态徽标 / 按钮
  const badge = $('runBadge');
  if (state.busy && state.cancelRequested) {
    badge.textContent = `终止中 · ${state.kind}`;
    badge.className = 'run-badge is-stop';
  } else if (state.busy) {
    badge.textContent = `运行中 · ${state.kind}`;
    badge.className = 'run-badge is-busy';
  } else {
    badge.textContent = '空闲';
    badge.className = 'run-badge';
  }
  $('btnRun').disabled = state.busy;
  $('btnValidate').disabled = state.busy;
  $('btnStop').disabled = !state.busy || state.cancelRequested;
  $('btnRefreshCookie').disabled = state.busy;
  $('btnRun').innerHTML = state.busy ? '<span class="loading"></span>运行中…' : '▶ 开始任务';

  // 进度
  const totalUnits = dailyTotal + extraTotal;
  const doneUnits = dailyDone + extraDone;
  let percent = pct(doneUnits, totalUnits);
  const bar = $('progressBar');
  const wrap = bar.parentElement;

  if (state.busy && doneUnits === 0) {
    wrap.classList.add('is-unknown');
    $('progressPct').textContent = '进行中';
  } else {
    wrap.classList.remove('is-unknown');
    if (!state.busy && state.lastResult && state.lastResult.success) percent = 100;
    bar.style.width = `${percent}%`;
    $('progressPct').textContent = `${percent}%`;
  }

  if (state.lastResult) {
    const r = state.lastResult;
    const icon = r.cancelled ? '⏹' : r.success ? '✅' : '❌';
    $('lastResult').textContent = `${icon} 上次${r.kind || '运行'}：${r.summary}（${r.time || ''}）`;
  }
}

function setStage(text) { $('stageText').textContent = text; }

/* ------------------------------------------------------------------
   日志
   ------------------------------------------------------------------ */
const LOG_RE = /^(\d{2}:\d{2}:\d{2})\s+\[([A-Z]+)\]\s*([\s\S]*)$/;

function parseLog(entry) {
  const m = LOG_RE.exec(entry.line || '');
  if (m) return { time: m[1], level: m[2], msg: m[3], raw: entry.line };
  return { time: '', level: entry.level || 'INFO', msg: entry.line || '', raw: entry.line };
}

function levelVisible(level) {
  switch (state.filter) {
    case 'INFO': return level !== 'DEBUG';
    case 'WARNING': return level === 'WARNING' || level === 'ERROR';
    case 'ERROR': return level === 'ERROR';
    default: return true;
  }
}

function matchesSearch(entry) {
  if (!state.search) return true;
  const raw = String(entry.raw || entry.line || '').toLowerCase();
  return raw.includes(state.search);
}

function logNode(entry) {
  const p = parseLog(entry);
  const div = document.createElement('div');
  div.className = `log-line lv-${p.level}`;
  const t = document.createElement('span'); t.className = 'log-time'; t.textContent = p.time;
  const l = document.createElement('span'); l.className = 'log-level'; l.textContent = p.level;
  const m = document.createElement('span'); m.className = 'log-msg'; m.textContent = p.msg;
  div.append(t, l, m);
  div.dataset.raw = (entry.raw || '').toLowerCase();
  div.dataset.level = p.level;
  return div;
}

function appendLog(entry) {
  state.logs.push(entry);
  if (state.logs.length > MAX_LOGS) state.logs.splice(0, state.logs.length - MAX_LOGS);

  const box = $('logBox');
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
  if (levelVisible(entry.level || 'INFO') && matchesSearch(entry)) {
    box.appendChild(logNode(entry));
    if ($('autoScroll').checked && nearBottom) box.scrollTop = box.scrollHeight;
  }
  $('logCount').textContent = `${state.logs.length} 行`;
}

function addSystemLog(text) {
  appendLog({ level: 'SYS', line: text, ts: Date.now() / 1000 });
}

function renderLogs() {
  const box = $('logBox');
  box.innerHTML = '';
  const frag = document.createDocumentFragment();
  for (const entry of state.logs) {
    if (levelVisible(entry.level || 'INFO') && matchesSearch(entry)) frag.appendChild(logNode(entry));
  }
  box.appendChild(frag);
  box.scrollTop = box.scrollHeight;
}

function logsToText() {
  return state.logs.map((e) => e.line).join('\n');
}

/* ------------------------------------------------------------------
   SSE 事件
   ------------------------------------------------------------------ */
function handleEvent(ev) {
  switch (ev.type) {
    case 'log':
      appendLog(ev);
      break;
    case 'state':
      applyState(ev.state);
      break;
    case 'stats':
      if (ev.stage === 'daily') state.stats.daily = { count: ev.payload.count || 0, completed: ev.payload.completed || 0 };
      if (ev.stage === 'extra_meta') state.stats.extra = { max: ev.payload.max || 15, done: ev.payload.completed || 0 };
      if (ev.stage === 'extra_progress') state.stats.extra = { max: ev.payload.max || 15, done: ev.payload.done || 0 };
      render();
      break;
    case 'account':
      state.username = ev.username || state.username;
      render();
      break;
    case 'progress':
      setStage(ev.text || '');
      break;
    case 'done': {
      const rec = ev.record || {};
      const cancelled = !rec.success && rec.summary === '任务已被用户终止';
      state.lastResult = {
        success: !!rec.success, summary: rec.summary, kind: rec.kind,
        time: rec.time, run_id: rec.id, cancelled,
      };
      render();
      addSystemLog(`—— 运行结束：${cancelled ? '⏹ ' : rec.success ? '✅ ' : '❌ '}${rec.summary} ——`);
      loadHistory();
      break;
    }
    default:
      break;
  }
}

function connectEvents() {
  const url = `${state.backend.base}/api/events?token=${encodeURIComponent(state.backend.token)}`;
  const es = new EventSource(url);
  state.es = es;
  es.addEventListener('open', () => setConn('ok'));
  es.addEventListener('state', (e) => applyState(JSON.parse(e.data)));
  es.addEventListener('message', (e) => {
    try { handleEvent(JSON.parse(e.data)); } catch (err) { console.error(err); }
  });
  es.addEventListener('error', () => setConn('warn', '连接中断，重连中…'));
}

/* ------------------------------------------------------------------
   配置
   ------------------------------------------------------------------ */
const TEXT_FIELDS = [
  'Cookie_MUSIC_U', 'Cookie___csrf', 'notify_email', 'email_password', 'smtp_server',
  'smtp_port', 'wait_time_min', 'wait_time_max', 'score',
  'netease_phone', 'netease_password', 'netease_md5_password', 'gh_token', 'gh_repo',
];

function collectConfig() {
  const cfg = { ...state.config };
  for (const key of TEXT_FIELDS) {
    const el = $(key);
    if (!el) continue;
    cfg[key] = el.value.trim();
  }
  cfg.wait_time_min = Number(cfg.wait_time_min);
  cfg.wait_time_max = Number(cfg.wait_time_max);
  cfg.score = Number(cfg.score);
  cfg.smtp_port = Number(cfg.smtp_port);
  return cfg;
}

function isCookieConfigured(cfg) {
  const raw = String((cfg || {}).Cookie_MUSIC_U || '').trim();
  return raw.length > 0 && !/^(YOUR_|您的)/.test(raw);
}

function fillConfig(cfg) {
  state.config = cfg || {};
  for (const key of TEXT_FIELDS) {
    const el = $(key);
    if (!el) continue;
    const v = state.config[key];
    el.value = v === undefined || v === null ? '' : String(v);
    el.classList.remove('invalid');
  }
  state.configDirty = false;
  if (!isCookieConfigured(state.config)) {
    $('accountState').textContent = '未配置';
    showBanner('尚未配置网易云 Cookie，配置后才能开始任务。', {
      label: '去配置',
      onClick: () => { switchPage('config'); hideBanner(); },
    });
  } else {
    hideBanner();
  }
}

async function loadConfig() {
  const data = await api('/api/config');
  fillConfig(data.config);
}

function markDirty() {
  state.configDirty = true;
  $('saveHint').textContent = '有未保存的修改';
  $('saveHint').style.color = 'var(--warn)';
}

async function saveConfig(silent = false) {
  const cfg = collectConfig();
  const data = await api('/api/config', { method: 'POST', body: cfg });
  if (!data.ok) throw new Error(data.error || '保存失败');
  state.config = data.config;
  state.configDirty = false;
  $('saveHint').textContent = `✅ 已保存 · ${state.meta ? state.meta.config_path : ''}`;
  $('saveHint').style.color = 'var(--green)';
  if (!silent) toast('配置已保存', 'ok');
  if (isCookieConfigured(state.config)) hideBanner();
  return data.config;
}

/* ------------------------------------------------------------------
   历史
   ------------------------------------------------------------------ */
async function loadHistory() {
  try {
    const data = await api('/api/history');
    state.history = data.records || [];
    renderHistory();
  } catch (e) { /* 历史加载失败不阻塞主流程 */ }
}

function renderHistory() {
  const body = $('historyBody');
  body.innerHTML = '';
  $('historyEmpty').hidden = state.history.length > 0;
  for (const rec of state.history) {
    const tr = document.createElement('tr');
    tr.dataset.id = rec.id;
    if (state.selectedHistory === rec.id) tr.classList.add('is-selected');
    const cancelled = !rec.success && rec.summary === '任务已被用户终止';
    tr.innerHTML = `
      <td>${rec.time || ''}</td>
      <td>${rec.kind || ''}</td>
      <td><span class="tag ${rec.success ? 'tag-ok' : 'tag-err'}">${cancelled ? '已终止' : rec.success ? '成功' : '失败'}</span></td>
      <td>${(rec.summary || '').replace(/</g, '&lt;')}</td>`;
    tr.onclick = () => selectHistory(rec.id, tr);
    body.appendChild(tr);
  }
  $('btnHistoryDelete').disabled = !state.selectedHistory;
}

async function selectHistory(id, tr) {
  state.selectedHistory = id;
  document.querySelectorAll('#historyBody tr').forEach((r) => r.classList.toggle('is-selected', r.dataset.id === id));
  $('btnHistoryDelete').disabled = false;
  $('historyTitle').textContent = `日志详情 · ${id}`;
  $('historyLog').innerHTML = '<div class="empty">加载中…</div>';
  try {
    const data = await api(`/api/history/${encodeURIComponent(id)}`);
    const box = $('historyLog');
    box.innerHTML = '';
    const frag = document.createDocumentFragment();
    String(data.log || '（该记录没有日志文件）').split('\n').forEach((line) => {
      if (!line) return;
      frag.appendChild(logNode({ line, level: 'INFO' }));
    });
    box.appendChild(frag);
  } catch (e) {
    $('historyLog').innerHTML = `<div class="empty">加载失败：${e.message}</div>`;
  }
}

/* ------------------------------------------------------------------
   动作
   ------------------------------------------------------------------ */
async function doValidate() {
  const cfg = collectConfig();
  const btn = $('btnValidate');
  btn.disabled = true;
  const original = btn.textContent;
  btn.innerHTML = '<span class="loading"></span>验证中…';
  setStage('正在验证 Cookie…');
  try {
    const r = await api('/api/validate', {
      method: 'POST',
      body: { Cookie_MUSIC_U: cfg.Cookie_MUSIC_U, Cookie___csrf: cfg.Cookie___csrf },
    });
    if (r.valid) {
      $('accountState').textContent = '✅ Cookie 有效';
      $('accountState').style.color = 'var(--green)';
      $('accountHint').textContent = r.message || '';
      if (r.nickname) $('nickname').textContent = r.nickname;
      setStage('Cookie 验证通过');
      toast('Cookie 验证通过', 'ok');
    } else {
      $('accountState').textContent = '❌ Cookie 无效';
      $('accountState').style.color = 'var(--err)';
      $('accountHint').textContent = r.message || '';
      setStage('Cookie 验证失败');
      toast(`Cookie 验证失败：${r.message}`, 'err', 6000);
    }
  } catch (e) {
    toast(`验证失败：${e.message}`, 'err');
  } finally {
    btn.disabled = state.busy;
    btn.textContent = original;
  }
}

async function doRun() {
  try {
    if (state.configDirty) await saveConfig(true);
    await api('/api/run', { method: 'POST' });
    addSystemLog('—— 开始执行每日任务 ——');
    setStage('任务已启动');
    toast('任务已启动', 'ok');
    switchPage('run');
  } catch (e) {
    toast(`启动失败：${e.message}`, 'err');
  }
}

async function doStop() {
  const ok = await confirmDialog('终止运行', '确定要终止当前任务吗？正在进行的评分操作会在当前请求完成后停止。', '终止');
  if (!ok) return;
  try {
    await api('/api/cancel', { method: 'POST' });
    toast('已发送终止请求', 'warn');
  } catch (e) {
    toast(`终止失败：${e.message}`, 'err');
  }
}

async function doRefreshCookie() {
  const ok = await confirmDialog('刷新 Cookie',
    '将通过手机号 + 密码登录并更新 GitHub Secrets 中的 Cookie。\n请确认已在「配置」页填写登录信息与 GitHub Token。', '开始刷新');
  if (!ok) return;
  try {
    if (state.configDirty) await saveConfig(true);
    await api('/api/refresh-cookie', { method: 'POST' });
    addSystemLog('—— 开始刷新 Cookie ——');
    toast('已开始刷新 Cookie', 'ok');
  } catch (e) {
    toast(`刷新失败：${e.message}`, 'err');
  }
}

async function doDeleteHistory() {
  if (!state.selectedHistory) return;
  const ok = await confirmDialog('删除记录', '确定删除这条运行记录及其日志吗？', '删除');
  if (!ok) return;
  await api(`/api/history/${encodeURIComponent(state.selectedHistory)}`, { method: 'DELETE' });
  state.selectedHistory = null;
  $('historyLog').innerHTML = '<div class="empty">选择左侧记录查看完整日志</div>';
  $('historyTitle').textContent = '日志详情';
  await loadHistory();
  toast('已删除', 'ok');
}

async function openPath(target) {
  try { await api('/api/open-path', { method: 'POST', body: { target } }); }
  catch (e) { toast(`打开失败：${e.message}`, 'err'); }
}

/* ------------------------------------------------------------------
   事件绑定
   ------------------------------------------------------------------ */
function bindUI() {
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.onclick = () => switchPage(btn.dataset.page);
  });

  $('btnValidate').onclick = doValidate;
  $('btnRun').onclick = doRun;
  $('btnStop').onclick = doStop;
  $('btnRefreshCookie').onclick = doRefreshCookie;

  $('btnSave').onclick = async () => {
    try { await saveConfig(); } catch (e) { toast(`保存失败：${e.message}`, 'err'); }
  };
  $('btnSaveVerify').onclick = async () => {
    try { await saveConfig(true); toast('配置已保存，开始验证…', 'ok'); await doValidate(); }
    catch (e) { toast(`保存失败：${e.message}`, 'err'); }
  };
  $('btnReload').onclick = async () => {
    try {
      await loadConfig();
      toast('已重新加载配置文件', 'ok');
      $('saveHint').textContent = '';
    } catch (e) { toast(`加载失败：${e.message}`, 'err'); }
  };
  $('btnOpenConfig').onclick = () => openPath('config_file');

  // 敏感字段显示切换
  const toggles = [
    ['showCookie', ['Cookie_MUSIC_U', 'Cookie___csrf']],
    ['showMail', ['email_password']],
    ['showSecret', ['netease_password', 'netease_md5_password', 'gh_token']],
  ];
  for (const [toggleId, fields] of toggles) {
    $(toggleId).onchange = (e) => {
      for (const f of fields) $(f).type = e.target.checked ? 'text' : 'password';
    };
  }

  // 表单改动标记
  document.querySelectorAll('#configForm input, #configForm select').forEach((el) => {
    el.addEventListener('input', () => {
      el.classList.remove('invalid');
      markDirty();
    });
  });

  // 日志工具
  $('logFilter').onchange = (e) => { state.filter = e.target.value; renderLogs(); };
  $('logSearch').oninput = (e) => { state.search = e.target.value.trim().toLowerCase(); renderLogs(); };
  $('btnClearLog').onclick = () => {
    state.logs = [];
    $('logBox').innerHTML = '';
    $('logCount').textContent = '0 行';
  };
  $('btnCopyLog').onclick = async () => {
    try { await navigator.clipboard.writeText(logsToText()); toast('日志已复制到剪贴板', 'ok'); }
    catch (e) { toast('复制失败，请手动选择日志文本', 'err'); }
  };

  // 历史
  $('btnHistoryRefresh').onclick = loadHistory;
  $('btnOpenLogs').onclick = () => openPath('logs');
  $('btnHistoryDelete').onclick = doDeleteHistory;
  $('btnCopyHistory').onclick = async () => {
    const text = $('historyLog').innerText.trim();
    if (!text) { toast('没有可复制的内容', 'warn'); return; }
    try { await navigator.clipboard.writeText(text); toast('已复制', 'ok'); }
    catch (e) { toast('复制失败', 'err'); }
  };

  // 快捷键
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); if (!state.busy) doRun(); }
    if (e.ctrlKey && e.key.toLowerCase() === 's') { e.preventDefault(); $('btnSave').click(); }
  });

  window.addEventListener('beforeunload', () => { if (state.es) state.es.close(); });
}

/* ------------------------------------------------------------------
   启动
   ------------------------------------------------------------------ */
async function bootstrap() {
  try {
    await initBackend();
  } catch (e) {
    setConn('err', '后端未连接');
    showBanner(e.message);
    $('btnRun').disabled = true;
    $('btnValidate').disabled = true;
    $('btnRefreshCookie').disabled = true;
    return;
  }

  setConn('ok');
  bindUI();

  try {
    state.meta = await api('/api/meta');
    $('verText').textContent = `v${state.meta.version}`;
    $('aboutVersion').textContent = `v${state.meta.version}`;
    $('aboutApi').textContent = state.backend.base;
    $('aboutRoot').textContent = state.meta.project_root;
    $('aboutMode').textContent = state.mode === 'tauri' ? 'Tauri 桌面应用' : '浏览器 + Python 后端';
    document.title = '网易云音乐合伙人';
  } catch (e) {
    toast(`读取应用信息失败：${e.message}`, 'err');
  }

  await loadConfig().catch((e) => toast(`读取配置失败：${e.message}`, 'err'));
  render();
  connectEvents();
  addSystemLog(`网易云音乐合伙人 v${(state.meta && state.meta.version) || VERSION_FALLBACK} 界面已启动（${state.mode === 'tauri' ? 'Tauri 桌面应用' : '浏览器模式'}）`);
  loadHistory();

  // 启动时按 URL hash 定位页面（如 #config）
  switchPage((location.hash || '#run').slice(1));

  // 启动后自动检测一次 Cookie
  if (isCookieConfigured(state.config)) {
    setTimeout(() => doValidate(), 400);
  }
}

document.addEventListener('DOMContentLoaded', bootstrap);
