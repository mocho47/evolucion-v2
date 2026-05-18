import sys, re
sys.stdout.reconfigure(encoding='utf-8')

for fname in ['admin.html', 'maestro.html', 'evolucion.html']:
    content = open(f'C:/evolucion/{fname}', encoding='utf-8').read()
    onclick_funcs = set(re.findall(r'onclick="([\w]+)\(', content))
    defined_funcs = set(re.findall(r'(?:async\s+)?function\s+(\w+)\s*\(', content))
    arrow_funcs = set(re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', content))
    all_defined = defined_funcs | arrow_funcs
    missing = onclick_funcs - all_defined
    print(f'\n=== {fname} ===')
    print(f'onclick funcs: {len(onclick_funcs)}, defined: {len(all_defined)}, missing: {len(missing)}')
    for m in sorted(missing):
        print(f'  ZOMBIE: {m}')
    if not missing:
        print('  All functions defined OK')
    # Also check fetch calls to non-existent endpoints
    fetches = re.findall(r"fetch\(BASE \+ ['\"`](/api/[^'\"`)]+)", content)
    print(f'API calls: {len(fetches)}')
