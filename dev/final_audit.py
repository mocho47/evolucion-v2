import sys, re
sys.stdout.reconfigure(encoding='utf-8')

server = open('C:/evolucion/evolucion_server.py', encoding='utf-8').read()
server_eps = set(re.findall(r'@app\.(?:get|post|put|delete|patch)\("(/api/[^"]+)"', server))

print("=== SERVER ENDPOINTS ===")
print(f"Total: {len(server_eps)}")

print("\n=== PANEL AUDIT ===")
panels = {
    'evolucion.html': 'teen/padre',
    'maestro.html': 'maestro',
    'admin.html': 'admin',
}

for fname, user_type in panels.items():
    content = open(f'C:/evolucion/{fname}', encoding='utf-8').read()

    # Count interactive elements
    buttons = len(re.findall(r'<button', content))
    onclick_funcs = set(re.findall(r'onclick="([\w]+)\(', content))
    defined_funcs = set(re.findall(r'(?:async\s+)?function\s+(\w+)\s*\(', content))
    window_funcs = set(re.findall(r'window\.(\w+)\s*=\s*(?:async\s+)?function', content))
    all_defined = defined_funcs | window_funcs
    missing = onclick_funcs - all_defined
    has_login = 'login' in content.lower() or 'codigo' in content.lower()
    has_privacy = 'privacidad' in content.lower() or 'privacy' in content.lower()

    print(f"\n{fname} [{user_type}]")
    print(f"  Buttons: {buttons} | onclick funcs: {len(onclick_funcs)} | defined: {len(all_defined)}")
    print(f"  Zombie functions: {sorted(missing) or 'NONE'}")
    print(f"  Has auth/login: {has_login}")
    print(f"  Has privacy link: {has_privacy}")

print("\n=== ADMIN PROTECTION ===")
admin_endpoints = re.findall(r'@app\.[a-z]+\("(/api/admin/[^"]+)"', server)
for ep in admin_endpoints:
    # Find the endpoint def and check for _verify_admin
    pattern = f'"{ep}"'
    idx = server.find(pattern)
    chunk = server[idx:idx+300]
    protected = '_verify_admin' in chunk
    print(f"  {'OK' if protected else 'MISSING AUTH'}: {ep}")

print("\n=== BARE EXCEPT CHECK ===")
bare = re.findall(r'\n\s+except:\s*\n', server)
print(f"  Bare except: {len(bare)} remaining (should be 0)")
