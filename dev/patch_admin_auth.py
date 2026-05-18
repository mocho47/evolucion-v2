import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('admin.html', encoding='utf-8') as f:
    content = f.read()

# ── 1. Add login screen CSS before </style> ──────────────────────────────────
login_css = """
/* Login overlay */
#login-overlay{position:fixed;inset:0;background:#050a14;z-index:9999;display:flex;align-items:center;justify-content:center}
#login-overlay.hidden{display:none}
.login-box{background:#0d1829;border:1px solid #7c3aed40;border-radius:16px;padding:40px;width:360px;max-width:90vw;text-align:center}
.login-box h2{font-size:1.4rem;font-weight:900;color:#fff;margin-bottom:8px}
.login-box p{color:#64748b;font-size:.9rem;margin-bottom:28px}
.login-logo{width:52px;height:52px;background:linear-gradient(135deg,#7c3aed,#4f46e5);border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:1.8rem;margin:0 auto 20px}
.login-input{width:100%;background:#050a14;border:1px solid #1e3a5f;border-radius:10px;color:#e2e8f0;padding:12px 16px;font-size:1rem;margin-bottom:16px;outline:none;transition:border .2s}
.login-input:focus{border-color:#7c3aed}
.login-btn{width:100%;background:linear-gradient(135deg,#7c3aed,#4f46e5);border:none;border-radius:10px;color:#fff;padding:13px;font-size:1rem;font-weight:700;cursor:pointer;transition:opacity .2s}
.login-btn:hover{opacity:.9}
.login-error{color:#f87171;font-size:.85rem;margin-top:12px;display:none}
"""

content = content.replace('</style>', login_css + '</style>', 1)

# ── 2. Add login overlay HTML right after <body> ──────────────────────────────
login_html = """
<div id="login-overlay">
  <div class="login-box">
    <div class="login-logo">🛡</div>
    <h2>Panel <span style="color:#a78bfa">Admin</span></h2>
    <p>Evolución by Simplex — acceso restringido</p>
    <input id="login-key-input" class="login-input" type="password" placeholder="Clave de administrador" autocomplete="off">
    <button class="login-btn" onclick="doLogin()">Entrar</button>
    <div class="login-error" id="login-err">Clave incorrecta</div>
  </div>
</div>
"""

content = content.replace('<body>', '<body>' + login_html, 1)

# ── 3. Replace const BASE = ''; with auth vars + login logic ─────────────────
auth_js = """const BASE = '';
let adminKey = sessionStorage.getItem('evo_admin_key') || '';

// ── Auth ──────────────────────────────────────────────────────────────────────
function authHeaders() {
  return { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey };
}

async function doLogin() {
  const key = document.getElementById('login-key-input').value.trim();
  if (!key) return;
  // Probe the server
  try {
    const r = await fetch(BASE + '/api/admin/stats', { headers: { 'X-Admin-Key': key } });
    if (r.status === 403) {
      document.getElementById('login-err').style.display = 'block';
      return;
    }
    adminKey = key;
    sessionStorage.setItem('evo_admin_key', key);
    document.getElementById('login-overlay').classList.add('hidden');
    initDashboard();
  } catch(e) {
    document.getElementById('login-err').style.display = 'block';
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !document.getElementById('login-overlay').classList.contains('hidden')) {
    doLogin();
  }
});

function checkAuth() {
  if (adminKey) {
    document.getElementById('login-overlay').classList.add('hidden');
    return true;
  }
  return false;
}
"""

content = content.replace("const BASE = '';\n", auth_js, 1)

# ── 4. Inject X-Admin-Key into all fetch calls ────────────────────────────────
# Pattern: fetch(BASE + '...') or fetch('/api/...')  without existing headers
# We need to add headers to each fetch call

# GET fetches (no options): fetch(BASE + '/api/admin/...')  -> fetch(BASE + '...', {headers: authHeaders()})
# POST fetches with JSON body: add 'X-Admin-Key' to headers
# Strategy: replace all fetch calls systematically

def add_auth_to_fetch(m):
    full = m.group(0)
    url_part = m.group(1)
    # Already has authHeaders? skip
    if 'authHeaders' in full or 'X-Admin-Key' in full:
        return full
    return f"fetch({url_part}, {{headers: authHeaders()}})"

def add_auth_to_fetch_with_opts(m):
    full = m.group(0)
    url_part = m.group(1)
    opts_inner = m.group(2)
    if 'authHeaders' in full or 'X-Admin-Key' in full:
        return full
    # Inject headers into existing options
    # If has headers: {...}, merge. Otherwise add headers key.
    if "'headers'" in opts_inner or '"headers"' in opts_inner or 'headers:' in opts_inner:
        # Already has headers, just add the key inside
        return full.replace("'Content-Type':'application/json'", "'Content-Type':'application/json','X-Admin-Key':adminKey").replace(
            "'Content-Type': 'application/json'", "'Content-Type': 'application/json', 'X-Admin-Key': adminKey")
    else:
        # Add headers to options
        new_opts = opts_inner.rstrip()
        if new_opts.endswith(','):
            new_opts += " headers: authHeaders(),"
        else:
            new_opts += ", headers: authHeaders()"
        return f"fetch({url_part}, {{{new_opts}}})"
    return full

# Simple approach: find fetch calls to /api/admin/ and add auth
# Replace simple GET fetch calls first
content = re.sub(
    r"fetch\((BASE \+ '/api/admin/[^']+)'?\)",
    lambda m: m.group(0).replace(')', ", {headers: authHeaders()})") if 'authHeaders' not in m.group(0) else m.group(0),
    content
)

# Replace POST/PUT fetch calls that already have options object - add X-Admin-Key to headers
# Pattern: fetch(BASE + '...', { method:'POST', ... })
def patch_fetch_with_options(m):
    url = m.group(1)
    opts = m.group(2)
    if 'authHeaders' in opts or 'X-Admin-Key' in opts:
        return m.group(0)
    # Insert 'X-Admin-Key': adminKey into headers if present, otherwise add headers
    if 'headers:' in opts:
        # Add to existing headers object
        opts = re.sub(r"(headers:\s*\{)", r"\1'X-Admin-Key': adminKey, ", opts)
    else:
        opts = opts.rstrip()
        if opts.endswith(','):
            opts += " headers: authHeaders(),"
        else:
            opts += ", headers: authHeaders()"
    return f"fetch({url}, {{{opts}}})"

content = re.sub(
    r"fetch\((BASE \+ '/api/admin/[^']+'),\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}\)",
    patch_fetch_with_options,
    content
)

# Also patch sembrar-demo calls (absolute path)
content = content.replace(
    "fetch('/api/admin/sembrar-demo', {method:'POST'})",
    "fetch('/api/admin/sembrar-demo', {method:'POST', headers: authHeaders()})"
)
content = content.replace(
    "fetch('/api/ping-demo')",
    "fetch('/api/ping-demo', {headers: authHeaders()})"
)

# ── 5. Wrap initDashboard on load ─────────────────────────────────────────────
# Replace DOMContentLoaded or initial load calls
if 'function initDashboard' not in content:
    # Wrap the existing load calls in initDashboard
    # Find where loadStats() is called on init
    content = content.replace(
        'loadStats();\nsetInterval(',
        'function initDashboard() {\n  loadStats();\n}\n\nif (checkAuth()) initDashboard();\n\nsetInterval('
    )
    # Fallback: if above didn't match, add initDashboard before setInterval
    if 'function initDashboard' not in content:
        content = content.replace(
            'setInterval(async () => {',
            'function initDashboard() { loadStats(); }\nif (checkAuth()) initDashboard();\n\nsetInterval(async () => {',
            1  # only first occurrence
        )

with open('admin.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("admin.html patched successfully")
