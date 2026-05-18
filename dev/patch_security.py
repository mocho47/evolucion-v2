import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('evolucion_server.py', encoding='utf-8') as f:
    lines = f.readlines()

orig_count = len(lines)
changes = []

def patch(idx, old, new, desc):
    if old not in lines[idx]:
        print(f"SKIP {desc}: not found at line {idx+1}")
        return False
    lines[idx] = lines[idx].replace(old, new, 1)
    changes.append(f"L{idx+1}: {desc}")
    return True

# ── 1. Remove duplicate StreamingResponse import (L1182) ──
patch(1181, '        from fastapi.responses import StreamingResponse as SR\n', '', 'remove dup import')
patch(1182, '        return SR(buf,', '        return StreamingResponse(buf,', 'fix SR alias')

# ── 2. Fix bare except clauses ──
patch(1067, 'except: ctx = {}', 'except Exception: ctx = {}', 'bare except L1068')
patch(1855, '            except:\n', '            except Exception:\n', 'bare except L1856')
patch(1871, '        except:\n', '        except Exception:\n', 'bare except L1872')
patch(1878, '        except:\n', '        except Exception:\n', 'bare except L1879')
patch(2084, '    except:\n', '    except Exception:\n', 'bare except L2085')
patch(2096, '        except: ctx = {}', '        except Exception: ctx = {}', 'bare except L2097')
patch(2214, '        except: pass\n', '        except Exception: pass\n', 'bare except L2215')
patch(2226, '        except: ctx = {}', '        except Exception: ctx = {}', 'bare except L2227')
patch(2276, '        except: pass\n', '        except Exception: pass\n', 'bare except L2277')
patch(2288, '        except: ctx = {}', '        except Exception: ctx = {}', 'bare except L2289')

# ── 3. Add _verify_admin to admin endpoints (insert after def lines, track offset) ──
offset = 0

def add_verify(base_line_0based, old_sig, new_sig, verify_call='    _verify_admin(request)\n'):
    global offset
    ln = base_line_0based + offset
    patch(ln, old_sig, new_sig, f"auth: {old_sig[:40]}")
    lines.insert(ln + 1, verify_call)
    offset += 1

add_verify(1842, 'async def admin_stats():', 'async def admin_stats(request: Request):')
add_verify(1883, 'async def admin_familias():', 'async def admin_familias(request: Request):')
add_verify(1897, 'async def admin_escuelas():', 'async def admin_escuelas(request: Request):')
add_verify(1913, 'async def sembrar_demo():', 'async def sembrar_demo(request: Request):')
add_verify(2581, 'async def admin_alertas_criticas():', 'async def admin_alertas_criticas(request: Request):')
add_verify(2597, 'async def admin_notificar_alerta(aid: str):', 'async def admin_notificar_alerta(aid: str, request: Request):')
add_verify(2614, 'async def admin_marcar_vista(aid: str):', 'async def admin_marcar_vista(aid: str, request: Request):')
add_verify(2621, 'async def admin_broadcast(req: Request):', 'async def admin_broadcast(req: Request):', '    _verify_admin(req)\n')
add_verify(2638, 'async def admin_reporte_masivo():', 'async def admin_reporte_masivo(request: Request):')
add_verify(2653, 'async def admin_pregunta_masiva():', 'async def admin_pregunta_masiva(request: Request):')
add_verify(2670, 'async def admin_set_modulos(fid: str, req: Request):', 'async def admin_set_modulos(fid: str, req: Request):', '    _verify_admin(req)\n')
add_verify(2682, 'async def admin_metricas():', 'async def admin_metricas(request: Request):')
add_verify(2712, 'async def admin_chat(req: Request):', 'async def admin_chat(req: Request):', '    _verify_admin(req)\n')

# ── 4. Fix fake-Request bug in admin_chat ──
for i, l in enumerate(lines):
    if "type('R', ()," in l and 'admin_broadcast' in l:
        sp = ' ' * (len(l) - len(l.lstrip()))
        replacement = (
            f"{sp}if params.get('mensaje'):\n"
            f"{sp}    _bc_enviados = 0\n"
            f"{sp}    async with aiosqlite.connect(DB_PATH) as _db:\n"
            f"{sp}        _bc_cur = await _db.execute(\n"
            f"{sp}            \"SELECT telefono_padre FROM familias WHERE telefono_padre IS NOT NULL AND telefono_padre != ''\")\n"
            f"{sp}        _bc_tels = [r[0] for r in await _bc_cur.fetchall()]\n"
            f"{sp}    for _tel in _bc_tels:\n"
            f"{sp}        if await send_whatsapp(_tel, params['mensaje']): _bc_enviados += 1\n"
            f"{sp}        await asyncio.sleep(1.5)\n"
            f"{sp}    accion_ejecutada = f'Broadcast enviado: {{_bc_enviados}} familias'\n"
        )
        lines[i] = replacement
        # Remove old accion_ejecutada line that followed
        if i + 1 < len(lines) and 'accion_ejecutada' in lines[i+1] and 'Broadcast' in lines[i+1]:
            lines[i+1] = ''
        changes.append(f"Fixed fake Request broadcast at line {i+1}")
        break

# ── 5. Add GET /api/admin/modulos/{fid} ──
for i, l in enumerate(lines):
    if '@app.post("/api/admin/modulos/{fid}")' in l:
        new_get = (
            '\n@app.get("/api/admin/modulos/{fid}")\n'
            'async def admin_get_modulos(fid: str, request: Request):\n'
            '    _verify_admin(request)\n'
            '    async with aiosqlite.connect(DB_PATH) as db:\n'
            '        modulos = await get_modulos_familia(db, fid)\n'
            '    return {"ok": True, "fid": fid, "modulos": modulos}\n'
        )
        lines.insert(i, new_get)
        changes.append(f"Added GET /api/admin/modulos/{{fid}} at i={i+1}")
        break

# ── 6. Add DELETE /api/familia/{fid}/datos (LFPDPPP) ──
delete_endpoint = (
    '\n# LFPDPPP art.8 — derecho de supresion\n'
    '@app.delete("/api/familia/{fid}/datos")\n'
    'async def eliminar_datos_familia(fid: str, request: Request):\n'
    '    admin_key = request.headers.get("X-Admin-Key") or request.query_params.get("key", "")\n'
    '    if admin_key != ADMIN_KEY:\n'
    '        raise HTTPException(403, "No autorizado")\n'
    '    async with aiosqlite.connect(DB_PATH) as db:\n'
    '        row = await (await db.execute("SELECT id FROM familias WHERE id=?", (fid,))).fetchone()\n'
    '        if not row:\n'
    '            raise HTTPException(404, "Familia no encontrada")\n'
    '        for tabla, col in [\n'
    '            ("conversaciones","familia_id"),("alertas","familia_id"),\n'
    '            ("mood_history","familia_id"),("misiones","familia_id"),\n'
    '            ("acuerdos","familia_id"),("modulos","familia_id"),\n'
    '            ("regularizacion","familia_id"),("logros","familia_id"),\n'
    '            ("miembros","familia_id"),\n'
    '        ]:\n'
    '            await db.execute(f"DELETE FROM {tabla} WHERE {col}=?", (fid,))\n'
    '        await db.execute("DELETE FROM familias WHERE id=?", (fid,))\n'
    '        await db.commit()\n'
    '    logger.info(f"LFPDPPP: datos familia {fid} eliminados")\n'
    '    return {"ok": True, "eliminado": fid, "ley": "LFPDPPP art.8"}\n'
)
for i, l in enumerate(lines):
    if '# -- Main' in l or '# ── Main' in l:
        lines.insert(i, delete_endpoint)
        changes.append(f"Added DELETE /api/familia/{{fid}}/datos at i={i+1}")
        break

with open('evolucion_server.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"Original: {orig_count} lines -> New: {len(lines)} lines")
print(f"\nChanges ({len(changes)}):")
for c in changes:
    print(f"  OK {c}")
