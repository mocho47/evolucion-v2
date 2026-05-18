import sys, re
sys.stdout.reconfigure(encoding='utf-8')

server = open('C:/evolucion/evolucion_server.py', encoding='utf-8').read()
# All defined endpoints
server_endpoints = set(re.findall(r'@app\.(?:get|post|put|delete|patch)\("(/api/[^"]+)"', server))
print(f"Server endpoints: {len(server_endpoints)}")

for fname in ['admin.html', 'maestro.html', 'evolucion.html']:
    content = open(f'C:/evolucion/{fname}', encoding='utf-8').read()
    # Extract all fetch URL patterns
    # /api/... (literal)
    literal = re.findall(r"['\`](/api/[^'\`\$\?]+)", content)
    # Template literal parts
    template = re.findall(r"['\`](/api/[^'\`\$]+)\$\{", content)
    all_calls = set(literal + template)

    print(f"\n=== {fname} API calls ===")
    for call in sorted(all_calls):
        # Normalize path params
        normalized = re.sub(r'/\{[^}]+\}', '/{id}', call)
        normalized_server = any(
            re.sub(r'/\{[^}]+\}', '/{id}', ep) == normalized
            for ep in server_endpoints
        )
        status = 'OK' if normalized_server else 'MISSING'
        print(f"  {status}: {call}")
