"""Embedded HTML/JS/CSS browser frontend for remote mode (P57).
远程模式的嵌入式 HTML/JS/CSS 浏览器前端。"""

from __future__ import annotations


def build_html(port: int = 8765) -> str:
    """Return a self-contained HTML page that connects to the WS server.
    返回连接到 WS 服务器的自包含 HTML 页面。"""
    return """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mini-Code-Agent</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #1e1e2e; color: #cdd6f4; height: 100vh; display: flex;
       flex-direction: column; }
#header { background: #313244; padding: 12px 20px; font-size: 14px;
           border-bottom: 1px solid #45475a; }
#header span { color: #89b4fa; font-weight: 600; }
#status { float: right; font-size: 12px; }
.connected { color: #a6e3a1; }
.disconnected { color: #f38ba8; }
#messages { flex: 1; overflow-y: auto; padding: 16px 20px;
            scrollbar-width: thin; scrollbar-color: transparent transparent; }
#messages:hover { scrollbar-color: rgba(166,173,200,0.3) transparent; }
#messages::-webkit-scrollbar { width: 6px; }
#messages::-webkit-scrollbar-track { background: transparent; }
#messages::-webkit-scrollbar-thumb { background: transparent; border-radius: 3px; }
#messages:hover::-webkit-scrollbar-thumb { background: rgba(166,173,200,0.3); }
.msg { margin-bottom: 16px; line-height: 1.6; word-wrap: break-word;
       font-size: 14px; }
.msg.user { color: #89b4fa; border-top: 1px solid #45475a;
            border-bottom: 1px solid #45475a;
            padding: 10px 0; margin-top: 8px; }
.msg.assistant { color: #cdd6f4; }
.msg.assistant h1 { font-size: 1.4em; margin: 12px 0 6px; color: #cba6f7; }
.msg.assistant h2 { font-size: 1.2em; margin: 10px 0 4px; color: #cba6f7; }
.msg.assistant h3 { font-size: 1.05em; margin: 8px 0 4px; color: #cba6f7; }
.msg.assistant code { background: #313244; padding: 2px 6px;
                      border-radius: 3px; font-size: 13px; }
.msg.assistant pre { background: #313244; padding: 10px 14px;
                     border-radius: 6px; overflow-x: auto;
                     margin: 8px 0; font-size: 13px; }
.msg.assistant pre code { background: none; padding: 0; }
.msg.assistant ul, .msg.assistant ol { margin: 6px 0 6px 20px; }
.msg.assistant strong { color: #f9e2af; }
.msg.assistant hr { border: none; border-top: 1px solid #45475a;
                    margin: 12px 0; }
.msg.tool { color: #a6adc8; font-size: 13px; background: #313244;
            padding: 8px 12px; border-radius: 6px; }
.msg.info { color: #94e2d5; font-style: italic; }
.msg.error { color: #f38ba8; }
.msg.permission { background: #45475a; padding: 10px 14px;
                  border-radius: 6px; }
.msg.permission button { margin: 4px 6px 0 0; padding: 4px 16px;
                          border: none; border-radius: 4px;
                          cursor: pointer; font-size: 13px; }
.btn-y { background: #a6e3a1; color: #1e1e2e; }
.btn-a { background: #89b4fa; color: #1e1e2e; }
.btn-n { background: #f38ba8; color: #1e1e2e; }
#input-area { display: flex; padding: 12px 20px; background: #313244;
              border-top: 1px solid #45475a; }
#input { flex: 1; background: #1e1e2e; border: 1px solid #585b70;
         color: #cdd6f4; padding: 10px 14px; border-radius: 6px;
         font-size: 14px; font-family: inherit; outline: none; }
#input:focus { border-color: #89b4fa; }
#send { background: #89b4fa; color: #1e1e2e; border: none;
        padding: 10px 20px; margin-left: 8px; border-radius: 6px;
        cursor: pointer; font-weight: 600; }
#send:hover { background: #74c7ec; }
#stop { background: #f38ba8; color: #1e1e2e; border: none;
        padding: 10px 16px; margin-left: 6px; border-radius: 6px;
        cursor: pointer; font-weight: 600; display: none; }
#stop:hover { background: #eba0ac; }
#cmd-list { position: absolute; bottom: 60px; left: 20px;
            background: #313244; border: 1px solid #585b70;
            border-radius: 6px; max-height: 240px; overflow-y: auto;
            display: none; z-index: 10; min-width: 320px;
            scrollbar-width: thin;
            scrollbar-color: rgba(166,173,200,0.3) transparent; }
#cmd-list div { padding: 6px 14px; cursor: pointer; font-size: 13px; }
#cmd-list div:hover, #cmd-list div.selected {
  background: #45475a; }
#cmd-list div span { color: #a6adc8; margin-left: 8px;
                     font-size: 12px; }
</style>
</head>
<body>
<div id="header">
  <span>Mini-Code-Agent</span> Remote Mode
  <div id="status" class="disconnected">Disconnected</div>
</div>
<div id="messages"></div>
<div id="cmd-list"></div>
<div id="input-area">
  <input id="input" placeholder="Type a message... (/ for commands)"
         autocomplete="off" />
  <button id="send">Send</button>
  <button id="stop">Stop</button>
</div>
<script>
const msgs = document.getElementById('messages');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const stopBtn = document.getElementById('stop');
const cmdList = document.getElementById('cmd-list');
const status = document.getElementById('status');
let ws = null;
let streamEl = null;
let streamBuf = '';
let isRunning = false;
let cmdIdx = -1;

const CMDS = [
  ['/help', 'List all commands'],
  ['/status', 'Session info'],
  ['/model', 'View or switch model'],
  ['/plan', 'Toggle read-only mode'],
  ['/spawn', 'Dispatch sub-agent'],
  ['/team', 'Auto-plan with sub-agents'],
  ['/memory', 'View/add/delete memories'],
  ['/memory consolidate', 'Merge related memories'],
  ['/skill', 'List skills'],
  ['/skill install', 'Install a skill'],
  ['/skill reload', 'Reload skills from disk'],
  ['/cost', 'Cost dashboard'],
  ['/todo', 'Task list'],
  ['/trace', 'Toggle trace mode'],
  ['/compact', 'Compress history'],
  ['/session', 'Session management'],
  ['/clear', 'Clear conversation'],
  ['/exit', 'Exit'],
];

function renderMd(text) {
  let h = text.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  h = h.replace(/```([\\s\\S]*?)```/g, '<pre><code>$1</code></pre>');
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  h = h.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  h = h.replace(/^---$/gm, '<hr>');
  h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>.*<\\/li>)/gs, '<ul>$1</ul>');
  h = h.replace(/<\\/ul>\\s*<ul>/g, '');
  h = h.replace(/\\n/g, '<br>');
  return h;
}

function addMsg(cls, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  if (cls === 'assistant') {
    el.innerHTML = renderMd(text);
  } else {
    el.textContent = text;
  }
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
  return el;
}

function connect() {
  const wsPort = parseInt(location.port) - 1;
  ws = new WebSocket('ws://' + location.hostname + ':' + wsPort);
  ws.onopen = () => {
    status.textContent = 'Connected';
    status.className = 'connected';
  };
  ws.onclose = () => {
    status.textContent = 'Disconnected';
    status.className = 'disconnected';
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    switch (msg.type) {
      case 'stream_start':
        streamBuf = '';
        streamEl = addMsg('assistant', '');
        setRunning(true);
        break;
      case 'stream_text':
        if (streamEl) {
          streamBuf += msg.delta;
          streamEl.innerHTML = renderMd(streamBuf);
        }
        msgs.scrollTop = msgs.scrollHeight;
        break;
      case 'stream_end':
        streamEl = null;
        streamBuf = '';
        setRunning(false);
        break;
      case 'tool_call':
        addMsg('tool', '\\u2699 ' + msg.name + ' ' + (msg.args || ''));
        break;
      case 'tool_result':
        const prefix = msg.is_error ? '\\u2718 ' : '\\u2714 ';
        addMsg(msg.is_error ? 'error' : 'tool', prefix + msg.name + ': ' + msg.output);
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
      case 'permission_request':
        const el = document.createElement('div');
        el.className = 'msg permission';
        const btns = '<br>' +
          '<button class="btn-y" onclick="respond(\\'' +
          msg.id + '\\',\\'y\\')">Allow</button>' +
          '<button class="btn-a" onclick="respond(\\'' +
          msg.id + '\\',\\'a\\')">Always</button>' +
          '<button class="btn-n" onclick="respond(\\'' +
          msg.id + '\\',\\'n\\')">Deny</button>';
        el.innerHTML = msg.prompt + btns;
        msgs.appendChild(el);
        msgs.scrollTop = msgs.scrollHeight;
        break;
    }
  };
}

function respond(id, decision) {
  if (ws) ws.send(JSON.stringify({type: 'permission_response', id, decision}));
}

function setRunning(v) {
  isRunning = v;
  stopBtn.style.display = v ? 'inline-block' : 'none';
  sendBtn.style.display = v ? 'none' : 'inline-block';
}

function send() {
  const text = input.value.trim();
  if (!text || !ws) return;
  hideCmds();
  addMsg('user', text);
  ws.send(JSON.stringify({type: 'user_input', text}));
  input.value = '';
  if (!text.startsWith('/')) setRunning(true);
}

function cancelRun() {
  if (ws) ws.send(JSON.stringify({type: 'cancel'}));
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
  if (e.key === 'Enter') send();
};
input.oninput = () => {
  const v = input.value;
  if (v.startsWith('/') && !v.includes(' ')) { showCmds(v); }
  else { hideCmds(); }
};
connect();
</script>
</body>
</html>"""
