# evolucion_reporte.py — Reportes semanales PDF + WhatsApp
"""
Módulo de reportes semanales para Evolución by Simplex.
Genera un PDF con el resumen de la semana del teen y lo envía
al padre/madre vía WhatsApp (Green API).
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone

import aiosqlite
import httpx
from fpdf import FPDF

# ── Configuración Green API ───────────────────────────────────────────────────
GREEN_INSTANCE = "7107622171"
GREEN_TOKEN    = "d9dc6f6f2f5944888d313b3148a93a2d85b48b59b18e4c15ba"
GREEN_SERVER   = "7107"
GREEN_BASE     = f"https://{GREEN_SERVER}.api.greenapi.com/waInstance{GREEN_INSTANCE}"

DB_PATH_DEFAULT = os.path.join(os.path.dirname(__file__), "evolucion.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evolucion.reporte")

# ── Helpers de color/emoji ────────────────────────────────────────────────────
MOOD_EMOJIS = {
    (9, 10): "😄",
    (7,  8): "🙂",
    (5,  6): "😐",
    (3,  4): "😟",
    (1,  2): "😔",
}

def mood_emoji(score: float) -> str:
    for rng, emoji in MOOD_EMOJIS.items():
        if rng[0] <= round(score) <= rng[1]:
            return emoji
    return "😐"


def _phone_to_chat_id(phone: str) -> str:
    """Normaliza teléfono mexicano a chatId de WhatsApp."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = "52" + digits
    return f"{digits}@c.us"


# ── 1. Generación del PDF ─────────────────────────────────────────────────────
async def generar_reporte_pdf(fid: str, db_path: str = DB_PATH_DEFAULT) -> bytes:
    """
    Genera un PDF de 1-2 páginas con el resumen semanal del teen
    para la familia `fid`. Devuelve los bytes del PDF.
    """
    ahora   = datetime.now(tz=timezone.utc)
    hace7   = ahora - timedelta(days=7)
    ts7     = hace7.isoformat()
    fecha_str = ahora.strftime("%d %b %Y")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Datos de la familia
        async with db.execute(
            "SELECT nombre, telefono_padre FROM familias WHERE id = ?", (fid,)
        ) as cur:
            familia = await cur.fetchone()
        if not familia:
            raise ValueError(f"Familia {fid} no encontrada en DB")
        nombre_familia = familia["nombre"]

        # Teen principal (primer teen activo de la familia)
        async with db.execute(
            "SELECT id, nombre, puntos_total FROM miembros "
            "WHERE familia_id = ? AND rol = 'teen' AND activo = 1 LIMIT 1",
            (fid,)
        ) as cur:
            teen = await cur.fetchone()

        if not teen:
            # fallback: cualquier miembro activo
            async with db.execute(
                "SELECT id, nombre, puntos_total FROM miembros "
                "WHERE familia_id = ? AND activo = 1 LIMIT 1",
                (fid,)
            ) as cur:
                teen = await cur.fetchone()

        teen_id   = teen["id"]   if teen else None
        teen_nombre = teen["nombre"] if teen else "tu teen"
        puntos_total = teen["puntos_total"] if teen else 0

        # Mood promedio últimos 7 días
        mood_promedio = None
        mood_registros = 0
        if teen_id:
            async with db.execute(
                "SELECT AVG(score) AS avg_score, COUNT(*) AS cnt "
                "FROM mood_history WHERE miembro_id = ? AND creado >= ?",
                (teen_id, ts7)
            ) as cur:
                row = await cur.fetchone()
                if row and row["avg_score"] is not None:
                    mood_promedio  = round(float(row["avg_score"]), 1)
                    mood_registros = int(row["cnt"])

        # Misiones esta semana
        async with db.execute(
            "SELECT "
            "  SUM(CASE WHEN estado = 'completada' OR aprobado = 1 THEN 1 ELSE 0 END) AS completadas, "
            "  SUM(CASE WHEN estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes, "
            "  COUNT(*) AS total "
            "FROM misiones "
            "WHERE familia_id = ? AND creado >= ?",
            (fid, ts7)
        ) as cur:
            mis = await cur.fetchone()
        mis_completadas = int(mis["completadas"] or 0)
        mis_pendientes  = int(mis["pendientes"]  or 0)
        mis_total       = int(mis["total"]       or 0)

        # Logros nuevos esta semana
        logros = []
        if teen_id:
            async with db.execute(
                "SELECT titulo, icono FROM logros "
                "WHERE miembro_id = ? AND creado >= ? ORDER BY creado DESC LIMIT 5",
                (teen_id, ts7)
            ) as cur:
                logros = [dict(r) for r in await cur.fetchall()]

        # Metas activas con progreso
        metas = []
        if teen_id:
            async with db.execute(
                "SELECT titulo, progreso FROM metas "
                "WHERE teen_id = ? AND estado = 'activa' ORDER BY creado DESC LIMIT 4",
                (teen_id,)
            ) as cur:
                metas = [dict(r) for r in await cur.fetchall()]

        # Aptitudes detectadas esta semana
        aptitudes = []
        if teen_id:
            async with db.execute(
                "SELECT tipo, descripcion, confianza FROM aptitudes "
                "WHERE teen_id = ? AND detectado >= ? ORDER BY confianza DESC LIMIT 4",
                (teen_id, ts7)
            ) as cur:
                aptitudes = [dict(r) for r in await cur.fetchall()]

        # Alertas de riesgo esta semana (tipo = 'vital' o 'riesgo_medio')
        alertas_riesgo = 0
        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM alertas "
            "WHERE familia_id = ? AND tipo IN ('vital','riesgo_medio') AND creado >= ?",
            (fid, ts7)
        ) as cur:
            row = await cur.fetchone()
            alertas_riesgo = int(row["cnt"] or 0) if row else 0

        # Acuerdos activos
        acuerdos_activos = 0
        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM acuerdos "
            "WHERE familia_id = ? AND estado = 'activo'",
            (fid,)
        ) as cur:
            row = await cur.fetchone()
            acuerdos_activos = int(row["cnt"] or 0) if row else 0

        # Regularización activa
        materias_reg = []
        if teen_id:
            async with db.execute(
                "SELECT materia, nivel, sesiones FROM regularizacion "
                "WHERE teen_id = ? AND estado = 'activo' ORDER BY sesiones DESC LIMIT 3",
                (teen_id,)
            ) as cur:
                materias_reg = [dict(r) for r in await cur.fetchall()]

    # ── Construir PDF ─────────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Colores
    MORADO  = (139, 92, 246)
    OSCURO  = (26, 26, 46)
    GRIS    = (100, 100, 120)
    VERDE   = (16, 185, 129)
    NARANJA = (245, 158, 11)
    BLANCO  = (255, 255, 255)
    FONDO_HEADER = (243, 240, 255)   # lavanda muy suave

    W = pdf.w - pdf.l_margin - pdf.r_margin  # ancho útil

    # ── Header ────────────────────────────────────────────────────────────────
    # Franja morada superior
    pdf.set_fill_color(*MORADO)
    pdf.rect(0, 0, pdf.w, 28, "F")

    pdf.set_y(5)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*BLANCO)
    pdf.cell(0, 8, "Evolución by Simplex", ln=False, align="L")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_y(14)
    pdf.cell(0, 6, f"Reporte Semanal · {fecha_str}", ln=True, align="L")

    pdf.set_y(32)

    # Título familia
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*MORADO)
    pdf.cell(0, 8, f"La semana de {teen_nombre}", ln=True, align="L")
    pdf.ln(2)

    # ── Mood ──────────────────────────────────────────────────────────────────
    _seccion_titulo(pdf, "Estado de ánimo", MORADO)

    if mood_promedio is not None:
        emoji = mood_emoji(mood_promedio)
        pdf.set_font("Helvetica", "B", 22)
        pdf.set_text_color(*OSCURO)
        # fpdf2 no renderiza emojis unicode directamente con Helvetica;
        # usamos la representación de texto del score + descripción textual
        pdf.cell(0, 10,
                 f"{mood_promedio}/10  —  {_mood_label(mood_promedio)}",
                 ln=True, align="L")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 5, f"Basado en {mood_registros} registro(s) esta semana", ln=True)
    else:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 8, "Sin registros de estado de ánimo esta semana.", ln=True)

    pdf.ln(3)

    # ── Misiones ──────────────────────────────────────────────────────────────
    _seccion_titulo(pdf, "Misiones", MORADO)

    if mis_total > 0:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*VERDE)
        pdf.cell(W / 2, 8, f"Completadas: {mis_completadas}", ln=False, align="L")
        pdf.set_text_color(*NARANJA)
        pdf.cell(W / 2, 8, f"Pendientes: {mis_pendientes}", ln=True, align="L")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 5, f"Total asignadas esta semana: {mis_total}", ln=True)
    else:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 8, "No hubo misiones asignadas esta semana.", ln=True)

    pdf.ln(3)

    # ── Puntos acumulados ────────────────────────────────────────────────────
    if puntos_total and int(puntos_total) > 0:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*MORADO)
        pdf.cell(0, 7, f"Puntos acumulados totales: {int(puntos_total)} pts", ln=True)
        pdf.ln(2)

    # ── Logros ────────────────────────────────────────────────────────────────
    if logros:
        _seccion_titulo(pdf, "Logros nuevos esta semana", MORADO)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*OSCURO)
        for lg in logros:
            icono = lg.get("icono") or "★"
            titulo = lg.get("titulo") or ""
            # Evitar caracteres non-latin que fpdf2 no puede renderizar
            icono_safe  = _ascii_safe(icono)
            titulo_safe = _ascii_safe(titulo)
            pdf.cell(0, 7, f"  {icono_safe}  {titulo_safe}", ln=True)
        pdf.ln(2)

    # ── Metas activas ─────────────────────────────────────────────────────────
    if metas:
        _seccion_titulo(pdf, "Metas activas", MORADO)
        for m in metas:
            titulo   = _ascii_safe(m.get("titulo") or "")
            progreso = int(m.get("progreso") or 0)
            # Barra de progreso textual
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(*OSCURO)
            pdf.cell(W * 0.6, 7, titulo, ln=False, align="L")
            pdf.set_text_color(*MORADO)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(W * 0.4, 7, f"{progreso}%", ln=True, align="R")
            # Barra visual
            _barra_progreso(pdf, progreso, W, MORADO, GRIS)
        pdf.ln(3)

    # ── Aptitudes ─────────────────────────────────────────────────────────────
    if aptitudes:
        _seccion_titulo(pdf, "Aptitudes detectadas", MORADO)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*OSCURO)
        for apt in aptitudes:
            tipo = _ascii_safe(str(apt.get("tipo") or "")).title()
            desc = _ascii_safe(str(apt.get("descripcion") or ""))
            conf = apt.get("confianza") or 0
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*MORADO)
            pdf.cell(W * 0.35, 7, tipo, ln=False)
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*OSCURO)
            pdf.multi_cell(W * 0.65, 7, f"{desc}  [{int(float(conf)*100)}%]")
        pdf.ln(2)

    # ── Regularización ───────────────────────────────────────────────────────
    if materias_reg:
        _seccion_titulo(pdf, "Regularizacion escolar", MORADO)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*OSCURO)
        for mr in materias_reg:
            materia  = _ascii_safe(str(mr.get("materia") or "")).title()
            nivel    = _ascii_safe(str(mr.get("nivel")   or ""))
            sesiones = int(mr.get("sesiones") or 0)
            pdf.cell(0, 7, f"  {materia}  |  Nivel: {nivel}  |  Sesiones: {sesiones}", ln=True)
        pdf.ln(2)

    # ── Acuerdos ─────────────────────────────────────────────────────────────
    if acuerdos_activos > 0:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 7, f"Acuerdos familiares activos: {acuerdos_activos}", ln=True)
        pdf.ln(2)

    # ── Alerta discreta ───────────────────────────────────────────────────────
    if alertas_riesgo > 0:
        pdf.set_fill_color(255, 249, 235)  # fondo amarillo muy suave
        pdf.set_draw_color(*NARANJA)
        pdf.set_line_width(0.5)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*NARANJA)
        pdf.rect(pdf.l_margin, pdf.get_y(), W, 12, "DF")
        pdf.cell(0, 12,
                 "  Hubo senales esta semana — te recomendamos platicar con calma.",
                 ln=True)
        pdf.ln(3)

    # ── Footer ────────────────────────────────────────────────────────────────
    _footer(pdf, GRIS)

    return bytes(pdf.output())


# ── Helpers internos para PDF ─────────────────────────────────────────────────
def _seccion_titulo(pdf: FPDF, texto: str, color: tuple):
    """Línea de título de sección con subrayado morado."""
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*color)
    pdf.cell(0, 8, texto.upper(), ln=True)
    # línea decorativa
    x0 = pdf.l_margin
    y0 = pdf.get_y()
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.4)
    pdf.line(x0, y0, x0 + 40, y0)
    pdf.ln(3)


def _barra_progreso(pdf: FPDF, pct: int, width: float, color_fill: tuple, color_bg: tuple):
    """Dibuja una barra de progreso horizontal."""
    h = 4
    x = pdf.l_margin
    y = pdf.get_y()
    # fondo
    pdf.set_fill_color(*color_bg)
    pdf.rect(x, y, width, h, "F")
    # relleno
    fill_w = max(1, width * min(pct, 100) / 100)
    pdf.set_fill_color(*color_fill)
    pdf.rect(x, y, fill_w, h, "F")
    pdf.set_y(y + h + 2)


def _footer(pdf: FPDF, color: tuple):
    """Footer fijo al fondo de la página."""
    pdf.set_y(-15)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*color)
    pdf.cell(0, 5,
             "Evolucion by Simplex  ·  evolucion-v2.onrender.com  ·  Reporte generado automaticamente",
             ln=True, align="C")


def _mood_label(score: float) -> str:
    if score >= 8.5:
        return "Excelente"
    if score >= 7:
        return "Bien"
    if score >= 5:
        return "Regular"
    if score >= 3:
        return "Bajo"
    return "Necesita atencion"


def _ascii_safe(text: str) -> str:
    """
    Reemplaza caracteres fuera del rango Latin-1 con equivalentes seguros
    para que fpdf2 con Helvetica no lance UnicodeEncodeError.
    Sustituye emojis comunes por texto equivalente.
    """
    emoji_map = {
        "★": "*", "✓": "OK", "✗": "X", "→": "->", "←": "<-",
        "✅": "[OK]", "❌": "[X]", "⭐": "*", "🏆": "[Logro]",
        "🎯": "[Meta]", "💡": "[Idea]", "📊": "[Reporte]", "🔥": "[!]",
    }
    for emoji, rep in emoji_map.items():
        text = text.replace(emoji, rep)
    # Codificación Latin-1 segura
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── 2. Envío del reporte vía WhatsApp ─────────────────────────────────────────
async def enviar_reporte_whatsapp(
    telefono: str,
    fid: str,
    db_path: str = DB_PATH_DEFAULT,
) -> bool:
    """
    Genera el PDF de la familia `fid` y lo envía vía Green API
    al `telefono` del padre/madre. Devuelve True si tuvo éxito.
    """
    try:
        pdf_bytes = await generar_reporte_pdf(fid, db_path)
    except Exception as e:
        logger.error(f"[reporte] Error generando PDF para familia {fid}: {e}")
        return False

    # Guardar PDF temporalmente
    tmp_path = os.path.join(tempfile.gettempdir(), f"reporte_{fid}.pdf")
    try:
        with open(tmp_path, "wb") as f:
            f.write(pdf_bytes)

        chat_id = _phone_to_chat_id(telefono)
        caption = "Tu reporte semanal de Evolucion esta listo"

        async with httpx.AsyncClient(timeout=30) as client:
            with open(tmp_path, "rb") as f:
                r = await client.post(
                    f"{GREEN_BASE}/sendFileByUpload/{GREEN_TOKEN}",
                    data={"chatId": chat_id, "caption": caption},
                    files={"file": ("reporte_semanal.pdf", f, "application/pdf")},
                )

        if r.status_code == 200:
            logger.info(f"[reporte] PDF enviado a {telefono} (familia {fid})")
            return True
        else:
            logger.warning(
                f"[reporte] Fallo envío a {telefono}: HTTP {r.status_code} — {r.text[:200]}"
            )
            return False

    except Exception as e:
        logger.error(f"[reporte] Excepción enviando a {telefono} (familia {fid}): {e}")
        return False
    finally:
        # Limpiar archivo temporal
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── 3. Enviar reportes a todas las familias ───────────────────────────────────
async def enviar_reportes_todas_familias(db_path: str = DB_PATH_DEFAULT):
    """
    Consulta todas las familias con teléfono configurado y envía
    el reporte semanal a cada una.
    """
    logger.info("[reporte] Iniciando envío masivo de reportes semanales...")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, nombre, telefono_padre FROM familias "
            "WHERE telefono_padre IS NOT NULL AND telefono_padre != ''"
        ) as cur:
            familias = [dict(r) for r in await cur.fetchall()]

    if not familias:
        logger.info("[reporte] No hay familias con teléfono configurado.")
        return

    logger.info(f"[reporte] {len(familias)} familia(s) a notificar.")

    ok_count  = 0
    err_count = 0

    for fam in familias:
        fid       = fam["id"]
        nombre    = fam["nombre"]
        telefono  = fam["telefono_padre"]
        logger.info(f"[reporte] Procesando familia: {nombre} ({fid})")

        exito = await enviar_reporte_whatsapp(telefono, fid, db_path)
        if exito:
            ok_count += 1
        else:
            err_count += 1

        # Pequeña pausa para no saturar la API
        await asyncio.sleep(2)

    logger.info(
        f"[reporte] Envío completado — OK: {ok_count} | Errores: {err_count} "
        f"| Total: {len(familias)}"
    )


# ── 4. Bloque de prueba manual ────────────────────────────────────────────────
if __name__ == "__main__":
    print("Evolucion — Reporte Semanal")
    print(f"DB: {DB_PATH_DEFAULT}")
    print("Iniciando envio de reportes a todas las familias...")
    asyncio.run(enviar_reportes_todas_familias(DB_PATH_DEFAULT))
    print("Listo.")

# LISTO: evolucion_reporte.py generado
