import sys
sys.stdout.reconfigure(encoding='utf-8')

anti_copy_js = """
<script>
// Evolucion by Simplex — proteccion de contenido
(function(){
  // Deshabilitar clic derecho en produccion
  const prod = !['localhost','127.0.0.1'].includes(location.hostname);
  if (prod) {
    document.addEventListener('contextmenu', e => e.preventDefault());
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && ['u','s','p'].includes(e.key.toLowerCase())) e.preventDefault();
      if (e.key === 'F12') e.preventDefault();
    });
  }
  // Anti-iframe
  if (window.top !== window.self) { window.top.location = window.self.location; }
  // Console warning
  console.log('%cEvolucion by Simplex', 'color:#7c3aed;font-size:1.5rem;font-weight:900');
  console.log('%cSoftware propietario. Uso no autorizado es ilegal.', 'color:#ef4444;font-size:.85rem');
})();
</script>
"""

for fname in ['admin.html', 'maestro.html', 'evolucion.html']:
    try:
        with open(fname, encoding='utf-8') as f:
            content = f.read()
        if 'proteccion de contenido' not in content:
            content = content.replace('</body>', anti_copy_js + '</body>', 1)
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Protected: {fname}")
        else:
            print(f"Already protected: {fname}")
    except FileNotFoundError:
        print(f"Not found: {fname}")
