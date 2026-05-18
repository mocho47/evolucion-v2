import sys, hashlib, uuid, time
sys.stdout.reconfigure(encoding='utf-8')

with open('evolucion_server.py', encoding='utf-8') as f:
    content = f.read()

# ── 1. Generate instance ID from machine+app salt ─────────────────────────────
import socket
try:
    hostname = socket.gethostname()
except Exception:
    hostname = "evolucion-host"

instance_seed = f"evolucion-v2-{hostname}-simplex"
INSTANCE_ID = hashlib.sha256(instance_seed.encode()).hexdigest()[:16]
print(f"Instance ID: {INSTANCE_ID}")

# ── 2. Add anti-piracy block right after ADMIN_KEY/APP_SECRET lines ──────────
anti_piracy_code = f'''
# ── Anti-piracy / License ────────────────────────────────────────────────────
import socket as _socket
_INSTANCE_ID = os.getenv("EVOLUCION_INSTANCE", "{INSTANCE_ID}")
_ALLOWED_HOSTS = set(filter(None, os.getenv("EVOLUCION_HOSTS", "evolucion-v2.onrender.com,localhost,127.0.0.1,teensevolucion.duckdns.org").split(",")))

def _verify_license():
    """Verifica que el entorno de ejecución es autorizado."""
    license_key = os.getenv("EVOLUCION_LICENSE", "")
    if not license_key:
        logger.warning("EVOLUCION_LICENSE no configurado — usando modo sin licencia")
        return
    expected = hashlib.sha256(f"evolucion-simplex-{{_INSTANCE_ID}}".encode()).hexdigest()[:32]
    if license_key != expected:
        logger.error("Licencia inválida — sistema bloqueado")
        import sys as _sys
        _sys.exit(77)

'''

# Insert after APP_SECRET line
insert_marker = 'APP_SECRET   = os.getenv("APP_SECRET", hashlib.sha256(b"evo-secret-2026").hexdigest())\n'
if insert_marker in content:
    content = content.replace(insert_marker, insert_marker + anti_piracy_code)
    print("Inserted anti-piracy block after APP_SECRET")
else:
    print("WARNING: APP_SECRET marker not found, inserting after ADMIN_KEY")
    insert_marker2 = 'ADMIN_KEY    = os.getenv("ADMIN_KEY"'
    idx = content.find(insert_marker2)
    if idx > 0:
        end_of_line = content.find('\n', idx) + 1
        content = content[:end_of_line] + '\n' + anti_piracy_code + content[end_of_line:]

# ── 3. Add security headers middleware ────────────────────────────────────────
security_middleware = '''
# ── Security headers middleware ───────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Host validation
        host = request.headers.get("host", "").split(":")[0]
        if host and host not in _ALLOWED_HOSTS and not host.endswith(".ngrok-free.dev") and not host.endswith(".ngrok.io"):
            if host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                logger.warning(f"Host no autorizado: {host}")
                # Log but don't block — allows testing; set EVOLUCION_STRICT=1 to block
                if os.getenv("EVOLUCION_STRICT") == "1":
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"error": "host no autorizado"}, status_code=403)

        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://*.ngrok-free.dev https://*.onrender.com; "
            "frame-ancestors 'none';"
        )
        # Watermark
        response.headers["X-Evolucion-Instance"] = _INSTANCE_ID
        response.headers["X-Powered-By"] = "Evolucion by Simplex"
        return response

app.add_middleware(SecurityHeadersMiddleware)

'''

# Insert before the rate limiter section
rate_marker = '# ── Rate limiter simple (in-memory)'
if rate_marker in content:
    content = content.replace(rate_marker, security_middleware + rate_marker)
    print("Inserted SecurityHeadersMiddleware")
else:
    print("WARNING: rate limiter marker not found")

# ── 4. Call _verify_license() in startup ──────────────────────────────────────
startup_marker = '    await init_db()\n'
if startup_marker in content:
    content = content.replace(startup_marker, '    _verify_license()\n' + startup_marker, 1)
    print("Added _verify_license() to startup")

# ── 5. Add code integrity check file ─────────────────────────────────────────
# Generate hash of current server.py for reference
with open('evolucion_server.py', encoding='utf-8') as f_orig:
    orig_hash = hashlib.sha256(f_orig.read().encode()).hexdigest()
# We'll write the new content first, then compute

with open('evolucion_server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("evolucion_server.py written")

# Verify syntax
import subprocess
result = subprocess.run(['python', '-m', 'py_compile', 'evolucion_server.py'], capture_output=True, text=True)
if result.returncode == 0:
    print("SYNTAX OK")
else:
    print("SYNTAX ERROR:", result.stderr)
