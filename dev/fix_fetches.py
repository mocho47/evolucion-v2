import sys
sys.stdout.reconfigure(encoding='utf-8')

content = open('admin.html', encoding='utf-8').read()

replacements = [
    (
        "fetch(BASE + `/api/admin/alerta/${id}/notificar`, {method:'POST'})",
        "fetch(BASE + `/api/admin/alerta/${id}/notificar`, {method:'POST', headers: authHeaders()})"
    ),
    (
        "fetch(BASE + `/api/admin/alerta/${id}/marcar-vista`, {method:'POST'})",
        "fetch(BASE + `/api/admin/alerta/${id}/marcar-vista`, {method:'POST', headers: authHeaders()})"
    ),
    (
        "fetch(BASE + `/api/admin/modulos/${fid}`)",
        "fetch(BASE + `/api/admin/modulos/${fid}`, {headers: authHeaders()})"
    ),
    (
        "fetch(BASE + `/api/admin/modulos/${fid}`, {",
        "fetch(BASE + `/api/admin/modulos/${fid}`, {headers: authHeaders(), "
    ),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f"Fixed: {old[:60]}")
    else:
        print(f"Not found: {old[:60]}")

open('admin.html', 'w', encoding='utf-8').write(content)
print("Done")
