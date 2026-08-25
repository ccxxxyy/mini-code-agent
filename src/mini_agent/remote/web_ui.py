"""Embedded HTML/JS/CSS browser frontend for remote mode (P57).
远程模式的嵌入式 HTML/JS/CSS 浏览器前端。"""

from __future__ import annotations


def build_html(
    port: int = 8765,
    version: str = "",
    model: str = "",
) -> str:
    """Return a self-contained HTML page that connects to the WS server.
    返回连接到 WS 服务器的自包含 HTML 页面。"""
    return (
        """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Mini-Code-Agent</title>
<style>
:root, [data-theme="dark"] {
  --bg-base: #1e1e2e;
  --bg-surface: #313244;
  --bg-overlay: #45475a;
  --text-primary: #cdd6f4;
  --text-secondary: #a6adc8;
  --text-muted: #6c7086;
  --text-faint: #585b70;
  --accent-blue: #89b4fa;
  --accent-blue-hover: #74c7ec;
  --accent-green: #a6e3a1;
  --accent-red: #f38ba8;
  --accent-red-hover: #eba0ac;
  --accent-purple: #cba6f7;
  --accent-yellow: #f9e2af;
  --accent-teal: #94e2d5;
  --border: #45475a;
  --scrollbar: rgba(166,173,200,0.3);
}
[data-theme="light"] {
  --bg-base: #eff1f5;
  --bg-surface: #dce0e8;
  --bg-overlay: #ccd0da;
  --text-primary: #4c4f69;
  --text-secondary: #6c6f85;
  --text-muted: #8c8fa1;
  --text-faint: #9ca0b0;
  --accent-blue: #1e66f5;
  --accent-blue-hover: #2a6ef6;
  --accent-green: #40a02b;
  --accent-red: #d20f39;
  --accent-red-hover: #e33e5a;
  --accent-purple: #8839ef;
  --accent-yellow: #df8e1d;
  --accent-teal: #179299;
  --border: #bcc0cc;
  --scrollbar: rgba(76,79,105,0.2);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg-base); color: var(--text-primary); height: 100vh;
       display: flex; flex-direction: column; }
#header { background: var(--bg-surface); padding: 12px 20px; font-size: 14px;
           border-bottom: 1px solid var(--border); }
#header span { color: var(--accent-blue); font-weight: 600; }
#status { float: right; font-size: 12px; }
#theme-toggle { float: right; margin-right: 12px; background: none;
            border: none; color: var(--text-primary); cursor: pointer;
            font-size: 16px; padding: 0 4px; line-height: 1; }
#theme-toggle:hover { opacity: 0.7; }
.connected { color: var(--accent-green); }
.disconnected { color: var(--accent-red); }
.reconnecting { color: var(--accent-yellow); }
#messages { flex: 1; overflow-y: auto; padding: 16px 20px;
            scrollbar-width: thin; scrollbar-color: transparent transparent; }
#messages:hover { scrollbar-color: var(--scrollbar) transparent; }
#messages::-webkit-scrollbar { width: 6px; }
#messages::-webkit-scrollbar-track { background: transparent; }
#messages::-webkit-scrollbar-thumb { background: transparent; border-radius: 3px; }
#messages:hover::-webkit-scrollbar-thumb { background: var(--scrollbar); }
.msg { margin-bottom: 4px; line-height: 1.5; word-wrap: break-word;
       font-size: 14px; }
.msg.user { color: var(--accent-blue); background: var(--bg-surface);
            padding: 10px 16px; border-radius: 8px; margin: 20px 0 16px;
            border-left: 3px solid var(--accent-blue); }
.msg.assistant { color: var(--text-primary); margin-bottom: 2px;
                white-space: pre-line; }
.msg.assistant .pg { display: block; height: 12px; }
.msg.assistant h1 { font-size: 1.3em; margin: 16px 0 8px; color: var(--accent-purple); }
.msg.assistant h2 { font-size: 1.15em; margin: 14px 0 6px; color: var(--accent-purple); }
.msg.assistant h3 { font-size: 1.05em; margin: 12px 0 4px; color: var(--accent-purple); }
.msg.assistant h4 { font-size: 1em; margin: 10px 0 4px; color: var(--accent-purple); }
.msg.assistant h1:first-child, .msg.assistant h2:first-child,
.msg.assistant h3:first-child, .msg.assistant h4:first-child { margin-top: 0; }
.msg.assistant code { background: var(--bg-surface); padding: 2px 6px;
                      border-radius: 3px; font-size: 13px; }
.msg.assistant pre { background: var(--bg-surface); padding: 10px 14px;
                     border-radius: 6px; overflow-x: auto;
                     margin: 4px 0; font-size: 13px; }
.msg.assistant pre code { background: none; padding: 0; }
.msg.assistant ul, .msg.assistant ol { margin: 1px 0 1px 0;
            padding: 0; list-style: none; }
.msg.assistant li { margin: 0; padding: 0; }
.msg.assistant ul li::before { content: "\\2022  "; color: var(--text-secondary); }
.msg.assistant ol { counter-reset: li; }
.msg.assistant ol li::before { counter-increment: li;
            content: counter(li) ". "; color: var(--accent-purple); }
.msg.assistant table { border-collapse: collapse; margin: 4px 0;
            font-size: 13px; }
.msg.assistant th, .msg.assistant td { border: 1px solid var(--border);
            padding: 3px 8px; text-align: left; }
.msg.assistant th { background: var(--bg-surface); color: var(--accent-purple); }
.msg.assistant strong { color: var(--accent-yellow); }
.msg.assistant a { color: var(--accent-blue); text-decoration: none; }
.msg.assistant a:hover { text-decoration: underline; }
.msg.assistant hr { display: none; }
.msg.tool { color: var(--text-faint); font-size: 12px; padding: 1px 0;
            margin-bottom: 2px; line-height: 1.4; }
.msg.tool-group { margin-bottom: 4px; }
.msg.tool-group summary { cursor: pointer; color: var(--text-faint);
            font-size: 12px; list-style: none; padding: 2px 0; }
.msg.tool-group summary::-webkit-details-marker { display: none; }
.msg.tool-group summary::before { content: '\\25b6  '; font-size: 10px; }
.msg.tool-group[open] summary::before { content: '\\25bc  '; }
.msg.tool-group .tool-body { color: var(--text-faint); font-size: 12px;
            padding: 2px 0 2px 16px; white-space: pre-wrap;
            word-break: break-all; max-height: 300px; overflow-y: auto; }
.msg.info { color: var(--accent-teal); font-style: italic;
            white-space: pre-wrap;
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 13px; }
.msg.error { color: var(--accent-red); }
.msg.turn-summary { color: var(--text-muted); font-size: 11px; padding: 2px 0 8px;
            border-bottom: 1px solid var(--bg-surface); margin-bottom: 8px; }
.msg.permission { background: var(--bg-overlay); padding: 10px 14px;
                  border-radius: 6px; }
.msg.permission button { margin: 4px 6px 0 0; padding: 4px 16px;
                          border: none; border-radius: 4px;
                          cursor: pointer; font-size: 13px; }
.btn-y { background: var(--accent-green); color: var(--bg-base); }
.btn-a { background: var(--accent-blue); color: var(--bg-base); }
.btn-n { background: var(--accent-red); color: var(--bg-base); }
#input-area { display: flex; padding: 12px 20px; background: var(--bg-surface);
              border-top: 1px solid var(--border); }
#input { flex: 1; background: var(--bg-base); border: 1px solid var(--text-faint);
         color: var(--text-primary); padding: 10px 14px; border-radius: 6px;
         font-size: 14px; font-family: inherit; outline: none;
         resize: none; min-height: 40px; max-height: 200px;
         overflow-y: auto; line-height: 1.4;
         scrollbar-width: thin; scrollbar-color: transparent transparent; }
#input:hover { scrollbar-color: var(--scrollbar) transparent; }
#input::-webkit-scrollbar { width: 4px; }
#input::-webkit-scrollbar-track { background: transparent; }
#input::-webkit-scrollbar-thumb { background: transparent; border-radius: 2px; }
#input:hover::-webkit-scrollbar-thumb { background: var(--scrollbar); }
#input:focus { border-color: var(--accent-blue); }
#send { background: var(--accent-blue); color: var(--bg-base); border: none;
        padding: 10px 20px; margin-left: 8px; border-radius: 6px;
        cursor: pointer; font-weight: 600; }
#send:hover { background: var(--accent-blue-hover); }
#stop { background: var(--accent-red); color: var(--bg-base); border: none;
        padding: 10px 16px; margin-left: 6px; border-radius: 6px;
        cursor: pointer; font-weight: 600; display: none; }
#stop:hover { background: var(--accent-red-hover); }
#cmd-list { position: absolute; bottom: 60px; left: 20px;
            background: var(--bg-surface); border: 1px solid var(--text-faint);
            border-radius: 6px; max-height: 240px; overflow-y: auto;
            display: none; z-index: 10; min-width: 320px;
            scrollbar-width: thin;
            scrollbar-color: var(--scrollbar) transparent; }
#cmd-list div { padding: 6px 14px; cursor: pointer; font-size: 13px; }
#cmd-list div:hover, #cmd-list div.selected {
  background: var(--bg-overlay); }
#cmd-list div span { color: var(--text-secondary); margin-left: 8px;
                     font-size: 12px; }
.msg.thinking-indicator { font-size: 20px; font-weight: 600;
            color: var(--accent-yellow); padding: 6px 0;
            animation: pulse-text 1.5s ease-in-out infinite; }
.msg.thinking-indicator .spinner { display: inline-block;
            width: 18px; height: 18px;
            border: 2px solid var(--text-faint);
            border-top-color: var(--accent-yellow);
            border-radius: 50%; animation: spin 0.8s linear infinite;
            vertical-align: middle; margin-right: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse-text { 0%,100% { opacity: 0.5; } 50% { opacity: 1; } }
.msg.thinking { color: var(--text-muted); font-size: 12px;
                padding: 2px 0; margin-bottom: 4px; }
.msg.thinking summary { cursor: pointer; color: var(--text-muted); }
.msg.thinking pre { white-space: pre-wrap; margin: 2px 0 0;
                    font-size: 11px; color: var(--text-faint);
                    max-height: 200px; overflow-y: auto; }
</style>
</head>
<body>
<div id="header">
  <span>Mini-Code-Agent</span> v"""
        + (version or "dev")
        + """
  <div id="status" class="disconnected">Disconnected</div>
  <button id="theme-toggle"></button>
</div>
<div id="messages"></div>
<div id="cmd-list"></div>
<div id="input-area">
  <textarea id="input" placeholder="Type a message... (/ for commands)"
            autocomplete="off" rows="1"></textarea>
  <button id="send">Send</button>
  <button id="stop">Stop</button>
</div>
<script>
const themeBtn = document.getElementById('theme-toggle');
function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  themeBtn.textContent = t === 'dark' ? '\\u2600' : '\\u263d';
  localStorage.setItem('theme', t);
}
setTheme(localStorage.getItem('theme') || 'dark');
themeBtn.onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  setTheme(cur === 'dark' ? 'light' : 'dark');
};

const msgs = document.getElementById('messages');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const stopBtn = document.getElementById('stop');
const cmdList = document.getElementById('cmd-list');
const status = document.getElementById('status');
let ws = null;
let streamEl = null;
let streamBuf = '';
let thinkingEl = null;
let thinkingBuf = '';
let spinnerEl = null;
let isRunning = false;
let cmdIdx = -1;
let userScrolled = false;

function showSpinner() {
  removeSpinner();
  spinnerEl = document.createElement('div');
  spinnerEl.className = 'msg thinking-indicator';
  spinnerEl.innerHTML = '<span class="spinner"></span>Thinking...';
  msgs.appendChild(spinnerEl);
  autoScroll();
}
function removeSpinner() {
  if (spinnerEl) { spinnerEl.remove(); spinnerEl = null; }
}

let CMDS = [
  ['/help', 'List all commands'],
  ['/exit', 'Exit'],
];
let pendingSend = null;

function renderMd(text) {
  text = text.replace(/<think>([\s\S]*?)<\/think>/g, (_, inner) =>
    '```think\\n' + inner.trim() + '\\n```think');
  let h = text.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  h = h.replace(/```think([\\s\\S]*?)```think/g,
    '<details class="msg thinking"><summary>Thinking...</summary><pre>$1</pre></details>');
  h = h.replace(/```([\\s\\S]*?)```/g, '<pre><code>$1</code></pre>');
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  h = h.replace(/!\\[([^\\]]*)\\]\\(([^)]+)\\)/g,
    '<img src="$2" alt="$1" style="max-width:100%;border-radius:6px">');
  h = h.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  h = h.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  h = h.replace(/(https?:\\/\\/[^\\s<)]+)/g, (m) =>
    m.startsWith('<a') ? m :
    '<a href="' + m + '" target="_blank" rel="noopener">' + m + '</a>');
  h = h.replace(/^---$/gm, '<hr>');
  h = h.replace(/^\\d+\\.\\s+(.+)$/gm, '<oli>$1</oli>');
  h = h.replace(/(<oli>.*<\\/oli>)/gs, (m) =>
    '<ol>' + m.replace(/<\\/?oli>/g, (t) =>
      t === '<oli>' ? '<li>' : '</li>') + '</ol>');
  h = h.replace(/<\\/ol>\\s*<ol>/g, '');
  h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>.*<\\/li>)/gs, '<ul>$1</ul>');
  h = h.replace(/<\\/ul>\\s*<ul>/g, '');
  // tables
  h = h.replace(/(^\\|.+\\|\\n?)+/gm, (block) => {
    const rows = block.trim().split('\\n').filter(r => r.trim());
    if (rows.length < 2) return block;
    const sep = rows[1];
    if (!/^[\\s|:-]+$/.test(sep)) return block;
    const parse = r => r.split('|').slice(1, -1).map(c => c.trim());
    const hdr = parse(rows[0]);
    let t = '<table><tr>' +
      hdr.map(c => '<th>' + c + '</th>').join('') + '</tr>';
    for (let i = 2; i < rows.length; i++) {
      const cells = parse(rows[i]);
      t += '<tr>' + cells.map(c => '<td>' + c + '</td>').join('') + '</tr>';
    }
    return t + '</table>';
  });
  h = h.replace(/\\n{2,}/g, '<div class="pg"></div>');
  h = h.replace(/(<\/(?:h[1234]|ul|ol|pre|table|li|details)>)\\n/g, '$1');
  h = h.replace(/\\n(<(?:h[1234]|ul|ol|pre|table|li|details)>)/g, '$1');
  return h;
}

function nearBottom() {
  return msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 300;
}
function autoScroll() {
  if (!userScrolled && nearBottom()) msgs.scrollTop = msgs.scrollHeight;
}
msgs.addEventListener('scroll', () => {
  userScrolled = !nearBottom();
});

function addMsg(cls, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  if (cls === 'assistant') {
    el.innerHTML = renderMd(text);
  } else {
    el.textContent = text;
  }
  msgs.appendChild(el);
  autoScroll();
  return el;
}

const urlToken = new URLSearchParams(location.search).get('token') || '';

function connect() {
  ws = new WebSocket('ws://' + location.hostname + ':' + location.port + '/ws');
  ws.onopen = () => {
    if (urlToken) {
      ws.send(JSON.stringify({type: 'auth', token: urlToken}));
    }
    msgs.innerHTML = '';
    streamEl = null; streamBuf = '';
    thinkingEl = null; thinkingBuf = '';
    spinnerEl = null;
    status.textContent = 'Connected';
    status.className = 'connected';
  };
  ws.onclose = () => {
    status.textContent = 'Reconnecting...';
    status.className = 'reconnecting';
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => { try {
    const msg = JSON.parse(e.data);
    switch (msg.type) {
      case 'user_message':
        if (pendingSend === msg.text) { pendingSend = null; }
        else { addMsg('user', msg.text); }
        break;
      case 'turn_start':
        setRunning(true);
        showSpinner();
        break;
      case 'turn_end':
        removeSpinner();
        thinkingEl = null;
        thinkingBuf = '';
        streamEl = null;
        streamBuf = '';
        setRunning(false);
        userScrolled = false;
        { let summary = [];
          if (msg.tokens) summary.push(msg.tokens.toLocaleString() + ' tokens');
          if (msg.iterations) summary.push(
            msg.iterations + (msg.iterations > 1 ? ' iterations' : ' iteration'));
          if (msg.elapsed) summary.push(msg.elapsed.toFixed(1) + 's');
          if (summary.length) {
            const el = document.createElement('div');
            el.className = 'msg turn-summary';
            el.textContent = summary.join('  \\u00b7  ');
            msgs.appendChild(el);
            autoScroll();
          }
        }
        break;
      case 'thinking_delta':
        removeSpinner();
        if (!thinkingEl) {
          thinkingEl = document.createElement('div');
          thinkingEl.className = 'msg thinking';
          const det = document.createElement('details');
          const sum = document.createElement('summary');
          sum.textContent = 'Thinking...';
          const pre = document.createElement('pre');
          det.appendChild(sum);
          det.appendChild(pre);
          thinkingEl.appendChild(det);
          thinkingEl._pre = pre;
          msgs.appendChild(thinkingEl);
        }
        thinkingBuf += msg.delta;
        thinkingEl._pre.textContent = thinkingBuf;
        autoScroll();
        break;
      case 'stream_start':
        removeSpinner();
        streamBuf = '';
        streamEl = addMsg('assistant', '');
        break;
      case 'stream_text':
        if (streamEl) {
          streamBuf += msg.delta;
          streamEl.innerHTML = renderMd(streamBuf);
        }
        autoScroll();
        break;
      case 'stream_end':
        if (msg.full_text && streamEl) {
          streamEl.innerHTML = renderMd(msg.full_text);
        }
        streamEl = null;
        streamBuf = '';
        showSpinner();
        break;
      case 'tool_call':
        removeSpinner();
        { const det = document.createElement('details');
          det.className = 'msg tool-group';
          det.open = true;
          det.dataset.toolName = msg.name;
          const sum = document.createElement('summary');
          sum.textContent = '\\u2699 ' + msg.name;
          det.appendChild(sum);
          const body = document.createElement('div');
          body.className = 'tool-body';
          body.textContent = msg.args || '';
          det.appendChild(body);
          msgs.appendChild(det);
          autoScroll(); }
        showSpinner();
        break;
      case 'tool_result':
        removeSpinner();
        { const icon = msg.is_error ? '\\u2718 ' : '\\u2714 ';
          const groups = msgs.querySelectorAll('.tool-group');
          const last = groups.length ? groups[groups.length - 1] : null;
          if (last && !last.dataset.hasResult) {
            last.dataset.hasResult = '1';
            const sum = last.querySelector('summary');
            const elapsed = msg.elapsed ? ' (' + msg.elapsed + ')' : '';
            sum.textContent = icon + msg.name + elapsed;
            const body = last.querySelector('.tool-body');
            body.textContent = msg.output;
            if (msg.is_error) sum.style.color = 'var(--accent-red)';
          } else {
            addMsg('tool', icon + msg.name + ': ' + msg.output);
          }
          autoScroll(); }
        showSpinner();
        break;
      case 'info':
        addMsg('info', msg.message);
        break;
      case 'error':
        addMsg('error', msg.message);
        break;
      case 'file_changes':
        addMsg('info', 'Files changed:\\n' + (msg.items || []).join('\\n'));
        break;
      case 'history_reset':
        msgs.innerHTML = '';
        streamEl = null; streamBuf = '';
        thinkingEl = null; thinkingBuf = '';
        spinnerEl = null;
        break;
      case 'history_user':
        addMsg('user', msg.text);
        break;
      case 'history_assistant':
        addMsg('assistant', msg.text);
        break;
      case 'history_tool_call':
        { const det = document.createElement('details');
          det.className = 'msg tool-group';
          det.open = true;
          det.dataset.toolName = msg.name;
          const sum = document.createElement('summary');
          sum.textContent = '\\u2699 ' + msg.name;
          det.appendChild(sum);
          const body = document.createElement('div');
          body.className = 'tool-body';
          body.textContent = msg.args || '';
          det.appendChild(body);
          msgs.appendChild(det);
          autoScroll(); }
        break;
      case 'history_tool_result':
        { const hi = msg.is_error ? '\\u2718 ' : '\\u2714 ';
          const hg = msgs.querySelectorAll('.tool-group');
          const hl = hg.length ? hg[hg.length - 1] : null;
          if (hl && !hl.dataset.hasResult) {
            hl.dataset.hasResult = '1';
            const hs = hl.querySelector('summary');
            hs.textContent = hi + msg.name;
            const hb = hl.querySelector('.tool-body');
            hb.textContent = msg.output;
            if (msg.is_error) hs.style.color = 'var(--accent-red)';
          } else {
            addMsg('tool', hi + msg.name + ': ' + msg.output);
          }
          autoScroll(); }
        break;
      case 'commands':
        if (msg.commands && msg.commands.length) CMDS = msg.commands;
        break;
      case 'ping':
        if (ws && ws.readyState === 1)
          ws.send(JSON.stringify({type: 'pong'}));
        break;
      case 'theme':
        if (msg.theme) setTheme(msg.theme);
        break;
      case 'permission_request':
        const pel = document.createElement('div');
        pel.className = 'msg permission';
        pel.setAttribute('data-perm-id', msg.id);
        pel.innerHTML = msg.prompt + '<br>' +
          '<button class="btn-y" onclick="respond(\\'' +
          msg.id + '\\',\\'y\\',this)">Allow</button>' +
          '<button class="btn-a" onclick="respond(\\'' +
          msg.id + '\\',\\'a\\',this)">Always</button>' +
          '<button class="btn-n" onclick="respond(\\'' +
          msg.id + '\\',\\'n\\',this)">Deny</button>';
        if (spinnerEl && spinnerEl.parentNode === msgs) {
          msgs.insertBefore(pel, spinnerEl);
        } else { msgs.appendChild(pel); }
        autoScroll();
        break;
    }
  } catch(err) { addMsg('error', 'JS ERROR: ' + err.message); } };
}

function respond(id, decision, btn) {
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({type:'permission',id:id,decision:decision}));
  const perm = document.querySelector('[data-perm-id="' + id + '"]');
  if (perm) {
    perm.querySelectorAll('button').forEach(b => {
      b.disabled = true;
      b.style.opacity = '0.3';
      b.style.cursor = 'default';
    });
    if (btn) {
      btn.style.opacity = '1';
      btn.style.fontWeight = 'bold';
      btn.style.boxShadow = '0 0 4px currentColor';
    }
    perm.style.borderLeft = '3px solid ' +
      (decision === 'y' || decision === 'a' ? 'var(--accent-green)' : 'var(--accent-red)');
  }
}

function setRunning(v) {
  isRunning = v;
  stopBtn.style.display = v ? 'inline-block' : 'none';
  sendBtn.style.display = v ? 'none' : 'inline-block';
}

function autoGrow() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
}

function send() {
  const text = input.value.trim();
  if (!text || !ws) return;
  hideCmds();
  pendingSend = text;
  addMsg('user', text);
  ws.send(JSON.stringify({type: 'user_input', text}));
  input.value = '';
  input.style.height = 'auto';
  if (!text.startsWith('/')) setRunning(true);
}

function cancelRun() {
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({type: 'cancel'}));
  setRunning(false);
}

function showCmds(filter) {
  const f = filter.toLowerCase();
  const matches = CMDS.filter(c => c[0].startsWith(f));
  if (!matches.length) { hideCmds(); return; }
  cmdList.innerHTML = '';
  cmdIdx = -1;
  matches.forEach(c => {
    const d = document.createElement('div');
    d.innerHTML = c[0] + '<span>' + c[1] + '</span>';
    d.onclick = () => { input.value = c[0] + ' '; hideCmds(); input.focus(); };
    cmdList.appendChild(d);
  });
  cmdList.style.display = 'block';
}

function hideCmds() { cmdList.style.display = 'none'; cmdIdx = -1; }

function navCmds(dir) {
  const items = cmdList.children;
  if (!items.length) return;
  if (cmdIdx >= 0) items[cmdIdx].classList.remove('selected');
  cmdIdx = (cmdIdx + dir + items.length) % items.length;
  items[cmdIdx].classList.add('selected');
  items[cmdIdx].scrollIntoView({block: 'nearest'});
}

stopBtn.onclick = cancelRun;
sendBtn.onclick = send;
input.onkeydown = (e) => {
  if (e.key === 'Escape') { hideCmds(); return; }
  if (cmdList.style.display === 'block') {
    if (e.key === 'ArrowDown') { e.preventDefault(); navCmds(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); navCmds(-1); return; }
    if (e.key === 'Tab' || e.key === 'Enter') {
      if (cmdIdx >= 0) {
        e.preventDefault();
        const cmd = CMDS.filter(c =>
          c[0].startsWith(input.value.toLowerCase()))[cmdIdx];
        if (cmd) { input.value = cmd[0] + ' '; hideCmds(); }
        return;
      }
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
};
input.oninput = () => {
  autoGrow();
  const v = input.value;
  if (v.startsWith('/') && !v.includes(' ')) { showCmds(v); }
  else { hideCmds(); }
};
connect();
</script>
</body>
</html>"""
    )
