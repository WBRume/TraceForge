export interface DashboardConfig {
  url: string
  port: number
  listenHost: string
  localIps?: string[]
  token: string
  stateRoot: string
  allowedRoots: string[]
  hostId: string
  protocolVersion: number
  platform: string
}

export function renderDashboardHtml(config: DashboardConfig): string {
  const maskedToken = config.token.length > 8 
    ? config.token.slice(0, 4) + '•'.repeat(config.token.length - 8) + config.token.slice(-4)
    : '••••••••••••••••'
  const configJson = JSON.stringify({
    resource_host_url: config.url,
    token: config.token
  }, null, 2)

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TraceForge Resource Host - 监控面板</title>
  <link rel="icon" href="/favicon.ico" type="image/x-icon">
  <style>
    :root {
      --bg-primary: #0f1117;
      --bg-secondary: #171923;
      --bg-tertiary: #1f2333;
      --border-color: #2d3748;
      --text-main: #f7fafc;
      --text-muted: #a0aec0;
      --accent-purple: #7e14ff;
      --accent-purple-light: #9f47ff;
      --accent-green: #38a169;
      --accent-green-glow: rgba(56, 161, 105, 0.35);
      --accent-blue: #3182ce;
      --accent-red: #e53e3e;
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 14px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-primary);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      line-height: 1.5;
      padding: 24px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-lg);
      padding: 16px 24px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .brand svg {
      width: 36px;
      height: 36px;
      border-radius: 8px;
    }
    .brand-title h1 {
      font-size: 20px;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .brand-title p {
      font-size: 13px;
      color: var(--text-muted);
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(56, 161, 105, 0.15);
      color: #48bb78;
      border: 1px solid rgba(56, 161, 105, 0.3);
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 13px;
      font-weight: 600;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      background: #48bb78;
      border-radius: 50%;
      box-shadow: 0 0 10px var(--accent-green-glow);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0.7); }
      70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(72, 187, 120, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0); }
    }
    .grid-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }
    .metric-card {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      position: relative;
    }
    .metric-label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
    }
    .metric-value {
      font-size: 20px;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .metric-card .copy-btn {
      padding: 4px 8px;
      font-size: 12px;
    }
    .main-cards {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 860px) {
      .main-cards { grid-template-columns: 1fr; }
    }
    .card {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 10px;
    }
    .card-title {
      font-size: 15px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      font-size: 13px;
      font-weight: 500;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-color);
      background: var(--bg-tertiary);
      color: var(--text-main);
      cursor: pointer;
      transition: all 0.2s ease;
      text-decoration: none;
    }
    .btn:hover {
      background: #2b3245;
      border-color: #4a5568;
    }
    .btn-primary {
      background: var(--accent-purple);
      border-color: var(--accent-purple);
      color: white;
    }
    .btn-primary:hover {
      background: var(--accent-purple-light);
    }
    .btn-danger {
      background: rgba(229, 62, 62, 0.15);
      border-color: rgba(229, 62, 62, 0.4);
      color: #fc8181;
    }
    .btn-danger:hover {
      background: var(--accent-red);
      color: white;
    }
    .token-display {
      background: var(--bg-primary);
      border: 1px solid var(--border-color);
      padding: 10px 14px;
      border-radius: var(--radius-sm);
      font-family: SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      word-break: break-all;
    }
    .roots-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 180px;
      overflow-y: auto;
    }
    .root-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--bg-primary);
      border: 1px solid var(--border-color);
      padding: 8px 12px;
      border-radius: var(--radius-sm);
      font-size: 13px;
    }
    .root-path {
      font-family: SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      color: #e2e8f0;
      word-break: break-all;
    }
    .badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 9999px;
      font-weight: 600;
    }
    .badge-success { background: rgba(56, 161, 105, 0.2); color: #48bb78; }
    .badge-warning { background: rgba(237, 137, 54, 0.2); color: #ed8936; }
    .activity-section {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      flex: 1;
    }
    .activity-table-wrapper {
      max-height: 240px;
      overflow-y: auto;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border-color);
    }
    th {
      background: var(--bg-tertiary);
      color: var(--text-muted);
      font-weight: 600;
      position: sticky;
      top: 0;
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }
    footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 10px;
      color: var(--text-muted);
      font-size: 12px;
    }
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--accent-purple);
      color: white;
      padding: 10px 20px;
      border-radius: var(--radius-md);
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
      font-size: 13px;
      font-weight: 500;
      opacity: 0;
      transform: translateY(20px);
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      pointer-events: none;
      z-index: 1000;
    }
    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <svg viewBox="0 0 48 46" fill="none">
        <path fill="#863bff" d="M25.946 44.938c-.664.845-2.021.375-2.021-.698V33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.947 44.94z"/>
      </svg>
      <div class="brand-title">
        <h1>TraceForge Resource Host</h1>
        <p>同机资源宿主服务 · 本机 Git 与工作区操作守护进程</p>
      </div>
    </div>
    <div style="display:flex; align-items:center; gap: 12px;">
      <div class="status-badge">
        <div class="status-dot"></div>
        <span id="host-status-text">运行中 (Port: ${config.port})</span>
      </div>
      <button class="btn btn-danger" onclick="confirmShutdown()">⏹️ 退出服务</button>
    </div>
  </header>

  <div class="grid-metrics">
    <div class="metric-card">
      <span class="metric-label">服务监听地址</span>
      <div class="metric-value">
        <span id="metric-url">${config.listenHost === '0.0.0.0' ? '0.0.0.0:' + config.port : config.url}</span>
        <button class="btn copy-btn" onclick="copyText('${config.url}', '服务地址已复制')">复制本地</button>
      </div>
      ${(config.localIps && config.localIps.length > 0) ? `
      <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">
        <span>可访问局域网/网关地址 (点击复制):</span>
        <div style="display: flex; gap: 6px; flex-wrap: wrap;">
          ${config.localIps.map(ip => `<button class="btn" style="padding: 2px 6px; font-size: 11px; background: #1a202c;" onclick="copyText('http://${ip}:${config.port}', 'http://${ip}:${config.port} 已复制')">${ip}:${config.port}</button>`).join('')}
        </div>
      </div>` : ''}
    </div>
    <div class="metric-card">
      <span class="metric-label">运行时间 (Uptime)</span>
      <div class="metric-value" id="metric-uptime">00:00:00</div>
    </div>
    <div class="metric-card">
      <span class="metric-label">内存占用 (Memory)</span>
      <div class="metric-value" id="metric-memory">-- MB</div>
    </div>
    <div class="metric-card">
      <span class="metric-label">主机 ID & 协议</span>
      <div class="metric-value" style="font-size: 15px; font-family: monospace;">
        ${config.hostId.slice(0, 8)}... (v${config.protocolVersion})
      </div>
    </div>
  </div>

  <div class="main-cards">
    <div class="card">
      <div class="card-header">
        <div class="card-title">🔑 访问凭据 (Token)</div>
        <div style="display: flex; gap: 8px;">
          <button class="btn" onclick="copyText('${config.token}', 'Token 已复制到剪贴板')">复制 Token</button>
          <button class="btn btn-primary" onclick="copyConfigJson()">📦 复制平台配置</button>
        </div>
      </div>
      <p style="font-size: 13px; color: var(--text-muted);">
        在 TraceForge Web 个人设置的“同机资源服务地址”与“凭据”中填入对应项，或点击右上方一键复制。
      </p>
      <div class="token-display">
        <span id="token-text">${maskedToken}</span>
        <button class="btn" style="padding: 2px 8px; font-size: 12px;" onclick="toggleToken()">显示明文</button>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">💾 状态存储目录 (state_root)</div>
        <button class="btn" onclick="openStateFolder()">📁 打开目录</button>
      </div>
      <p style="font-size: 13px; color: var(--text-muted);">
        持久化存储 Host 身份、操作 journal.sqlite3 以及检查点快照。请勿随意删除。
      </p>
      <div class="token-display" style="font-family: SFMono-Regular, Menlo, Monaco, Consolas, monospace;">
        ${config.stateRoot}
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <div class="card-title">📁 授权工作区与仓库目录 (allowed_roots)</div>
      <div style="display: flex; gap: 8px; align-items: center;">
        <span style="font-size: 12px; color: var(--text-muted);"><span id="roots-count">${config.allowedRoots.length}</span> 个授权根目录</span>
        <button class="btn btn-primary" style="padding: 2px 10px; font-size: 12px;" onclick="promptAddRoot()">+ 添加授权目录</button>
      </div>
    </div>
    <div class="roots-list" id="roots-container">
      ${config.allowedRoots.length === 0 
        ? '<div style="color: var(--text-muted); font-size: 13px; padding: 10px 0;">当前尚未限制授权工作区目录。可在 host.json 中配置，或通过平台一键连接自动动态追加授权。</div>'
        : config.allowedRoots.map(r => `
          <div class="root-item">
            <span class="root-path">${r}</span>
            <span class="badge badge-success">已授权</span>
          </div>
        `).join('')
      }
    </div>
  </div>

  <div class="activity-section">
    <div class="card-header">
      <div class="card-title">📊 实时操作与请求监控 (Recent Activity)</div>
      <span style="font-size: 12px; color: var(--text-muted);" id="activity-count">自动刷新中...</span>
    </div>
    <div class="activity-table-wrapper">
      <table>
        <thead>
          <tr>
            <th style="width: 100px;">时间</th>
            <th style="width: 80px;">方法</th>
            <th>路径 / 操作类型</th>
            <th style="width: 90px;">状态码</th>
            <th style="width: 90px;">耗时</th>
          </tr>
        </thead>
        <tbody id="activity-tbody">
          <tr>
            <td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">暂无操作记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <footer>
    <div>TraceForge Resource Host · 纯独立运行时 · 免安装 Node/Bun/Python</div>
    <div style="display: flex; gap: 12px;">
      <a href="/dashboard" class="btn" style="padding: 3px 10px; font-size: 12px;">刷新面板</a>
      <a href="https://github.com/WBRume/TraceForge" target="_blank" class="btn" style="padding: 3px 10px; font-size: 12px;">文档与源码</a>
    </div>
  </footer>

  <div id="toast" class="toast">已复制</div>

  <script>
    const fullToken = "${config.token}";
    const maskedToken = "${maskedToken}";
    let tokenVisible = false;

    function toggleToken() {
      tokenVisible = !tokenVisible;
      const el = document.getElementById('token-text');
      const btn = event.target;
      if (tokenVisible) {
        el.innerText = fullToken;
        btn.innerText = '隐藏明文';
      } else {
        el.innerText = maskedToken;
        btn.innerText = '显示明文';
      }
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      toast.innerText = msg;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 2200);
    }

    function copyText(text, successMsg) {
      navigator.clipboard.writeText(text).then(() => {
        showToast(successMsg || '已复制');
      }).catch(() => {
        const input = document.createElement('input');
        input.value = text;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        document.body.removeChild(input);
        showToast(successMsg || '已复制');
      });
    }

    function copyConfigJson() {
      const bestUrl = "${(config.localIps && config.localIps.length > 0) ? `http://${config.localIps[0]}:${config.port}` : config.url}";
      const json = JSON.stringify({
        resource_host_url: bestUrl,
        token: fullToken
      }, null, 2);
      copyText(json, '平台连接配置 (JSON) 已复制');
    }

    function openStateFolder() {
      fetch('/v1/system/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: "${config.stateRoot.replace(/\\/g, '\\\\')}" })
      }).then(r => {
        if (r.ok) showToast('已在资源管理器中打开');
        else showToast('打开目录失败');
      }).catch(() => showToast('无法打开目录'));
    }

    function confirmShutdown() {
      if (confirm('确认停止并退出 TraceForge Resource Host 吗？\\n退出后平台将无法访问本机资源。')) {
        fetch('/v1/system/shutdown', { method: 'POST' }).then(() => {
          document.body.innerHTML = '<div style="display:flex;height:100vh;justify-content:center;align-items:center;flex-direction:column;gap:16px;"><h1>TraceForge Resource Host 已停止</h1><p style="color:#a0aec0">服务已安全退出，您可以关闭此窗口。</p></div>';
        }).catch(() => {
          document.body.innerHTML = '<div style="display:flex;height:100vh;justify-content:center;align-items:center;flex-direction:column;gap:16px;"><h1>TraceForge Resource Host 已停止</h1><p style="color:#a0aec0">服务已退出。</p></div>';
        });
      }
    }

    async function promptAddRoot() {
      const p = prompt('请输入要授权的本地绝对路径（例如代码仓库或工作区所在的父目录）：');
      if (!p || !p.trim()) return;
      try {
        const res = await fetch('/v1/roots/grant', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + fullToken
          },
          body: JSON.stringify({ roots: [p.trim()] })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          showToast('目录授权成功并已保存！');
          if (Array.isArray(data.allowed_roots)) {
            renderRoots(data.allowed_roots);
          }
        } else {
          alert('授权失败: ' + (data.detail || data.error || '未知错误'));
        }
      } catch (err) {
        alert('请求失败: ' + err.message);
      }
    }

    function renderRoots(roots) {
      const container = document.getElementById('roots-container');
      const countEl = document.getElementById('roots-count');
      if (countEl) countEl.innerText = roots.length;
      if (!container) return;
      if (!roots || roots.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; padding: 10px 0;">当前尚未限制授权工作区目录。可在 host.json 中配置，或通过平台一键连接自动动态追加授权。</div>';
      } else {
        container.innerHTML = roots.map(function(r) {
          return '<div class="root-item"><span class="root-path">' + r + '</span><span class="badge badge-success">已授权</span></div>';
        }).join('');
      }
    }

    function formatUptime(seconds) {
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = Math.floor(seconds % 60);
      return [h, m, s].map(v => String(v).padStart(2, '0')).join(':');
    }

    async function pollStatus() {
      try {
        const res = await fetch('/v1/status');
        if (!res.ok) return;
        const data = await res.json();
        
        if (data.uptime !== undefined) {
          document.getElementById('metric-uptime').innerText = formatUptime(data.uptime);
        }
        if (data.memory_mb !== undefined) {
          document.getElementById('metric-memory').innerText = data.memory_mb + ' MB';
        }
        if (Array.isArray(data.allowed_roots)) {
          renderRoots(data.allowed_roots);
        }
        
        if (Array.isArray(data.recent_activities)) {
          const tbody = document.getElementById('activity-tbody');
          document.getElementById('activity-count').innerText = '共 ' + data.recent_activities.length + ' 条记录';
          if (data.recent_activities.length > 0) {
            tbody.innerHTML = data.recent_activities.map(item => {
              const statusBadge = item.status < 300 
                ? '<span class="badge badge-success">' + item.status + ' OK</span>'
                : '<span class="badge badge-warning">' + item.status + '</span>';
              return '<tr>' +
                '<td>' + (item.time || '') + '</td>' +
                '<td><span style="font-weight:600;">' + (item.method || 'GET') + '</span></td>' +
                '<td><code>' + (item.kind ? ('[' + item.kind + '] ') : '') + (item.path || '') + '</code></td>' +
                '<td>' + statusBadge + '</td>' +
                '<td>' + (item.duration_ms ? (item.duration_ms + ' ms') : '< 1 ms') + '</td>' +
                '</tr>';
            }).join('');
          }
        }
      } catch (e) { }
    }

    setInterval(pollStatus, 2000);
    pollStatus();
  </script>
</body>
</html>`
}
