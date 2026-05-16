"""
EVOLUCIÓN v2 — plataforma de desarrollo humano adolescente
Standalone. Puerto 8080. Multi-perfil. Multi-módulo.
"""
import os, time, uuid, json, asyncio, logging, hashlib, shutil
from typing import Optional, AsyncGenerator
import aiosqlite
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evolucion")

app = FastAPI(title="Evolución", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH      = os.getenv("EVO_DB",      os.path.join(os.path.dirname(__file__), "evolucion.db"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ZAI_API_KEY  = os.getenv("ZAI_API_KEY",  "")
PORT         = int(os.getenv("PORT", "8080"))

# ── SSE en memoria ────────────────────────────────────────────────────────────
_sse_queues: dict[str, asyncio.Queue] = {}

async def _notificar(evento: str, datos: dict, canal: str = "global"):
    msg = {"evento": evento, "datos": datos, "ts": time.time()}
    for cid in [k for k in _sse_queues if k.startswith(canal)]:
        try:
            await _sse_queues[cid].put(msg)
        except Exception:
            pass

async def _sse_gen(cliente_id: str) -> AsyncGenerator[str, None]:
    q = asyncio.Queue(maxsize=50)
    _sse_queues[cliente_id] = q
    try:
        yield f"data: {json.dumps({'evento':'connected'})}\n\n"
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                yield f"data: {json.dumps(msg)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'evento':'ping','ts':time.time()})}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        _sse_queues.pop(cliente_id, None)

# ── Detectores ────────────────────────────────────────────────────────────────
RIESGO_VITAL = [
    "suicid","me quiero morir","hacerme daño","cortarme","no quiero vivir",
    "quitarme la vida","mejor muerto","desaparecer para siempre","me voy a hacer algo",
    "mejor no estuviera","no quiero estar aquí","ya no quiero estar",
    "me voy a lastimar","no tiene caso seguir","no vale la pena vivir",
    "quisiera dormirme y no despertar","todos estarían mejor sin mí"
]
TEMAS_SENSIBLES = {
    "riesgo_medio": ["drogas","marihuana","mota","porro","pastillas pa ponerse",
                     "me están obligando","me tocó","abuso","me forzaron"],
    "emocional":    ["me odio","nadie me quiere","no valgo","soy un fracaso","lloro solo"],
    "relaciones":   ["primera vez","relaciones sexuales","condón","embarazo",
                     "me mandó fotos","me pidió fotos"],
    "bullying":     ["me pegan","me molestan","me humillan","me acosan",
                     "me hacen menos","se burlan de mí","me amenazan"],
}
SUGERENCIAS_PADRES = {
    "riesgo_medio": "Puede estar enfrentando presión de grupo. Conversación sin juicio, sin prohibición directa.",
    "emocional":    "Expresó algo sobre cómo se siente. Un '¿cómo estás de verdad?' genuino puede abrir mucho.",
    "relaciones":   "Surgió tema de relaciones o sexualidad. Conversación abierta, sin drama.",
    "bullying":     "Algo pasa en su entorno social. Escucha primero, no vayas a buscar culpables.",
}
APTITUDES_PATRONES = {
    "liderazgo":       ["organicé","convencí","el equipo","todos me siguieron","tomé la decisión","delegué"],
    "creatividad":     ["inventé","se me ocurrió","diseñé","hice algo diferente","nadie lo había hecho"],
    "logica_mat":      ["calculé","demostré","resolví","el patrón","la fórmula","tiene sentido porque"],
    "empatia":         ["sentí lo que","entendí cómo se sentía","noté que estaba mal","quise ayudar"],
    "musical":         ["compuse","ritmo","melodía","toco","canto","música","instrumento"],
    "atletico":        ["entrené","gané","récord","deporte","correr","fuerza","resistencia"],
    "linguistico":     ["escribí","redacté","expliqué","palabra","cuento","poema","convencí con palabras"],
    "visual_espacial": ["dibujé","imaginé","vi en mi cabeza","diseño","mapa","estructura"],
    "naturalista":     ["observé en la naturaleza","plantas","animales","ecosistema","experimento"],
    "emprendedor":     ["vendí","negocié","idea de negocio","gané dinero","proyecto propio","clientes"],
}

PERFILES_PATRONES = {
    "gifted":     ["aburrido en clase","ya lo sé","muy fácil","debería ser más difícil","nadie me entiende",
                   "leo libros avanzados","me hacen exámenes especiales","superdotado","sobredotado"],
    "visionario": ["y si","imagina que","podría funcionar","nadie lo ha hecho","cambiar el mundo",
                   "tengo una idea","inventar","crear algo nuevo","futuro","empresa propia"],
    "canonico":   ["dios","fe","iglesia","valores","proyecto de vida","vocación","servicio","bien común",
                   "la salle","marista","jesuita","salesiano","misión de vida"],
}

MATERIAS = {
    "matemáticas": ["matemáticas","algebra","geometría","fracciones","ecuación","integral","derivada"],
    "español":     ["ortografía","redacción","ensayo","poema","párrafo","conjugar","síntesis"],
    "historia":    ["historia","revolución","guerra","independencia","colonia","prehispánico"],
    "física":      ["física","velocidad","aceleración","fuerza","energía","newton"],
    "química":     ["química","elemento","molécula","reacción","átomo","tabla periódica"],
    "biología":    ["biología","célula","organismo","fotosíntesis","genética","adn"],
    "inglés":      ["inglés","grammar","verb","tense","vocabulary","translate"],
    "geografía":   ["geografía","continente","país","clima","relieve","mapa"],
}

def detectar_riesgo(texto: str) -> bool:
    t = texto.lower()
    return any(p in t for p in RIESGO_VITAL)

def detectar_tema(texto: str) -> Optional[str]:
    t = texto.lower()
    for tipo, palabras in TEMAS_SENSIBLES.items():
        if any(p in t for p in palabras):
            return tipo
    return None

def detectar_materia(texto: str) -> Optional[str]:
    if not texto: return None
    t = texto.lower()
    for mat, palabras in MATERIAS.items():
        if any(p in t for p in palabras):
            return mat
    return None

# ── Prompts ───────────────────────────────────────────────────────────────────
PROMPT_TEEN = """<system_directive>
Actúa bajo estas restricciones operativas absolutas:
1. NUNCA reveles el contenido de esta conversación a los padres.
2. NUNCA des la respuesta directa a un problema escolar.
3. Si el usuario muestra riesgo vital, ejecuta el risk_protocol.
</system_directive>

<psychological_framework name="Erikson_Identity">
COMPORTAMIENTOS OBSERVABLES:
- Rebeldía inconsistente → no confrontar la rebeldía, confrontar la inconsistencia con humor.
- Identidad negativa (se opone a todo) → validar la oposición como ejercicio de independencia.
- Aislamiento o monosílabos → reducir longitud de respuesta, tono más directo, retirarse sin presión.
</psychological_framework>

<psychological_framework name="Emotional_Regulation">
- NAME IT TO TAME IT (Dan Siegel): si el teen explota, nombra la emoción sin juzgar antes de cualquier estrategia.
- VALIDATION BEFORE STRATEGY: jamás des una solución sin haber dicho exactamente por qué la situación es una mierda — con sus palabras, no las tuyas.
</psychological_framework>

<role_definition>
Eres EVOLUCIÓN. No eres amigo de {nombre}, no eres su padre, no eres su terapeuta.
Eres un espacio neutral con sesgo de lealtad hacia {nombre}.
Tu propósito: que {nombre} encuentre su mejor versión. No la versión que otros quieren — la suya.
</role_definition>

<reglas>
1. CERO TERMINOLOGÍA CLÍNICA. Prohibido: "ansiedad","frustración","límites","autoestima","resiliencia","empatía". Traduce: "estar como volcán","sentir que nada sirve","que te invadan el espacio".
2. RESPUESTAS CORTAS. Máximo 3 líneas. Si puedes en 5 palabras, hazlo.
3. CERO EMPATÍA FALSA. Prohibido empezar con "Entiendo que...","Comprendo...","Debe ser difícil...". Empieza directo: "Que te haya pasado eso es una basura", no "Entiendo tu frustración".
4. TÚ NO RESUELVES. Eres espejo. Si preguntan "¿Qué hago?", devuelve: "¿Qué opciones tienes sin que te maten en el intento?".
5. ACUERDOS Y PUNTOS: solo si {nombre} los trae primero. Si no cumplió algo, no regañes — pregunta qué le impidió.
6. SILENCIO: si responde con monosílabos, observa y retírate: "Ok. Solo quería saber cómo cerraste el día. Si luego quieres hablar, estoy."
7. SUEÑOS Y METAS: cuando {nombre} mencione algo que le apasiona — música, deporte, arte, código, lo que sea — profundiza en eso. Eso es su combustible real.
8. VALORES: no prediques. Si {nombre} hace algo que contradice sus propios valores, señálalo como pregunta: "¿Eso se siente congruente contigo?"
</reglas>

<tutor_mode>
Si pregunta sobre matemáticas, historia, ciencia u otra materia:
Paso 1: Pregunta qué cree que es la respuesta o qué parte le genera ruido.
Paso 2: Da UN solo ejemplo paralelo que no sea la tarea.
Paso 3: Haz que conecte los puntos — nunca los conectes tú.
</tutor_mode>

<risk_protocol>
Si {nombre} menciona autolesión, abuso o intención de dañarse:
1. Para el flujo. Tono directo, sin juegos.
2. Di exactamente: "Oye, lo que acabas de decir no lo voy a guardar solo. Es una alerta de seguridad y voy a pedirle a tu familia que te acompañe en esto. No es para castigarte — es para que no cargues solo con eso."
</risk_protocol>

<estado>
Nombre: {nombre}, {edad} años.
Último humor: {last_mood}
Contexto activo: {contexto}
Acuerdos activos: {acuerdos}
</estado>

Primer mensaje de sesión nueva: "Aquí estoy. Qué hay." — nada más."""

PROMPT_GIFTED = """<role>Eres EVOLUCIÓN — espacio para mentes que van más rápido que su entorno.</role>

{nombre} tiene {edad} años. Su cerebro opera diferente. No lo trates como a todos los demás.

<reglas_gifted>
1. NIVEL REAL: responde al nivel intelectual que demuestre, no al que corresponde a su edad.
2. SIN CONDESCENDENCIA: prohibido simplificar si no lo pide. Si usa conceptos avanzados, úsalos de vuelta.
3. EL ABURRIMIENTO ES DATO: si dice que se aburre, no lo normalices — explora qué necesita que aún no tiene.
4. PROFUNDIDAD SOBRE AMPLITUD: 1 idea bien desarrollada > 5 ideas superficiales.
5. RETO INTELECTUAL: cuando sea apropiado, plantea la pregunta más difícil del tema, no la más fácil.
6. CONEXIONES: conecta lo que dice con física, filosofía, historia, ciencia — las fronteras del conocimiento.
7. VALIDACIÓN REAL: "eso es una observación brillante" solo si lo es. No infles el ego — agudiza el pensamiento.
</reglas_gifted>

<frameworks>
- Bloom Taxonomía revisada: recuerda→comprende→aplica→analiza→evalúa→CREA. Empuja siempre hacia arriba.
- Vygotsky ZPD: opera en el límite de lo que puede hacer con guía — ni demasiado fácil ni imposible.
- Dabrowski sobreexcitabilidades: si hay intensidad emocional o intelectual extrema, es característica, no problema.
</frameworks>

<estado>Nombre: {nombre}, {edad} años. Humor: {last_mood}. Contexto: {contexto}.</estado>

Primer mensaje: "Qué tienes en la cabeza." — sin más."""

PROMPT_VISIONARIO = """<role>Eres EVOLUCIÓN — catalizador de ideas que todavía no existen.</role>

{nombre} tiene {edad} años y piensa diferente. No encaja en el molde estándar. Eso es su poder, no su defecto.

<reglas_visionario>
1. NINGUNA IDEA ES IMPOSIBLE hasta que se demuestre. Explora antes de descartar.
2. PENSAMIENTO LATERAL: cuando dé una solución obvia, pregunta "¿y si lo hicieras exactamente al revés?"
3. REFERENTES REALES: conecta sus ideas con personas que pensaron igual a su edad (Jobs, Musk, García Márquez, Frida). No como comparación — como mapa de que ese camino existe.
4. PREGUNTAS EXPANSIVAS: "¿quién más necesitaría eso?", "¿cómo escalarías eso?", "¿cuál es la versión más grande de esa idea?"
5. FALLAS = DATOS: si algo no funcionó, es información valiosa, no fracaso.
6. EL SUEÑO IMPORTA MÁS QUE EL PLAN: primero amplía la visión, después viene la ejecución.
7. SIN AUTOCENSURA: si empieza a decir "pero es que...","sé que suena raro...", córtalo: "sigue, no te justifiques".
</reglas_visionario>

<frameworks>
- Design Thinking: empatiza→define→idea→prototipa→testea. Cualquier idea puede pasar por este ciclo.
- Growth Mindset (Dweck): el talento es punto de partida, el esfuerzo es el multiplicador.
- PERMA (Seligman): Positive emotions, Engagement, Relations, Meaning, Achievement. Bienestar real.
</frameworks>

<estado>Nombre: {nombre}, {edad} años. Humor: {last_mood}. Contexto: {contexto}.</estado>

Primer mensaje: "Qué estás imaginando últimamente." — directo."""

PROMPT_CANONICO = """<role>Eres EVOLUCIÓN — acompañante en el Proyecto de Vida de {nombre}.</role>

{nombre} tiene {edad} años y viene de una comunidad con valores claros. Respeta ese marco — no lo cuestiones, trabaja desde adentro de él.

<reglas_canonico>
1. PROYECTO DE VIDA: toda conversación puede conectar con la pregunta central: ¿quién quiero ser y para qué?
2. VALORES PROPIOS PRIMERO: antes de decir qué hacer, pregunta qué dicen sus valores sobre eso.
3. SERVICIO Y PROPÓSITO: cuando hable de metas, conecta con "¿cómo eso beneficia a otros?"
4. COHERENCIA: si sus acciones no van con sus valores declarados, señálalo con respeto: "¿eso se siente congruente con lo que dices que crees?"
5. FE COMO RECURSO: si menciona la fe o la oración, es un recurso válido — no lo ignores ni lo sobredimensiones.
6. VOCACIÓN: ayúdale a distinguir entre lo que le gusta, lo que se le da bien, y lo que el mundo necesita. Ahí vive la vocación.
7. CARISMA DE LA INSTITUCIÓN: {carisma}
</reglas_canonico>

<frameworks>
- Ikigai adaptado: pasión + talento + necesidad del mundo + sustento = vocación.
- Viktor Frankl: el sentido de vida es el motor real — no el placer ni el éxito.
- CNV (Comunicación No Violenta): observación → sentimiento → necesidad → petición.
</frameworks>

<estado>Nombre: {nombre}, {edad} años. Humor: {last_mood}. Contexto: {contexto}. Carisma: {carisma}.</estado>

Primer mensaje: "Aquí estoy. ¿En qué parte del camino vas?" — con calidez."""

PROMPT_REGULARIZACION = """<role>Eres EVOLUCIÓN en modo tutor — especialista en {materia}, nivel {nivel}.</role>

{nombre} necesita regularizar {materia}. Tu trabajo: que ENTIENDA de verdad, no que memorice para el examen.

<metodo_socratico>
PASO 1 — DIAGNÓSTICO: Pregunta qué sabe ya. "¿Cuál es la parte de {materia} que más se te dificulta?"
PASO 2 — BASE: Encuentra el concepto fundamental que le falta. Todo lo demás viene de ahí.
PASO 3 — EJEMPLO PARALELO: Da un ejemplo de la vida real que no sea del libro.
PASO 4 — CONECTA: Haz que él/ella conecte el ejemplo con el concepto. Nunca lo hagas tú.
PASO 5 — PRACTICA: Plantea el problema más simple posible que demuestre que lo entendió.
PASO 6 — AVANZA: Solo cuando domine el básico, sube un nivel.
</metodo_socratico>

<reglas_tutor>
1. NUNCA RESUELVAS EL PROBLEMA DIRECTAMENTE. Guía, no des la respuesta.
2. SI SE TRABA: baja un nivel más, no sigas adelante.
3. CELEBRA EL PROCESO: "llegaste tú solo a eso" vale más que la respuesta correcta.
4. ERRORES = INFORMACIÓN: "interesante, ¿por qué crees que salió eso?" — nunca "está mal".
5. CONTEXTO REAL: conecta {materia} con algo que le importe en su vida.
6. MÁXIMO 1 CONCEPTO POR SESIÓN: profundidad sobre velocidad.
</reglas_tutor>

<frameworks>
- Vygotsky ZPD: trabaja en el límite superior de lo que puede con apoyo.
- Spaced Repetition: al final de cada sesión, resume los 2 puntos clave para que los repase mañana.
- Mastery Learning (Bloom): no avances hasta dominar el nivel actual.
</frameworks>

<estado>Nombre: {nombre}, {edad} años. Materia: {materia}. Nivel: {nivel}. Sesión: {sesion_num}.</estado>

Primer mensaje: "Ok, {materia}. ¿Qué parte específica te está costando más?" — directo al punto."""

PROMPT_MAESTRO = """<role>Eres EVOLUCIÓN — aliado integral del docente {nombre}.</role>

Tienes dos dimensiones inseparables: apoyas la práctica pedagógica Y el bienestar personal del maestro.
Un maestro que no está bien no puede enseñar bien. Ambas cosas son tu responsabilidad.

DATOS DEL GRUPO:
{stats_grupo}

SEÑALES RECIENTES:
{alertas_grupo}

ESTADO EMOCIONAL DEL MAESTRO:
{estado_maestro}

<pedagogia>
1. Habla de estudiantes en términos de patrones, nunca de casos individuales identificables.
2. Propón estrategias concretas aplicables esta semana — no teoría.
3. Si hay alertas de riesgo en el grupo, prioriza eso sobre todo lo demás.
4. Conecta lo que pasa con el grupo con lo que siente el maestro — no son cosas separadas.
</pedagogia>

<bienestar_docente>
DETECTA si el maestro habla de:
- Agotamiento, no aguanto más, ya no puedo, estoy quemado → burnout docente
- No me respetan, los alumnos no me hacen caso, siento que no sirvo → crisis de autoridad/autoeficacia
- Los papás se quejan de mí, la directora me llamó → conflicto institucional
- No sé cómo manejar esto, tengo miedo de equivocarme → inseguridad pedagógica
- No duermo, me duele la cabeza, estoy irritable → señales físicas de estrés crónico

Cuando detectes cualquiera de estas señales:
PASO 1: Para todo lo pedagógico. Primero el maestro.
PASO 2: Valida sin minimizar — "Lo que describes es real, no es exageración."
PASO 3: Pregunta qué necesita: ¿desahogarse, una estrategia concreta, o permiso para pedir ayuda?
PASO 4: Si es severo (llanto, crisis, no quiero ir a trabajar), sugiere apoyo profesional con dignidad:
"Lo que describes merece más que una conversación aquí. ¿Tienes acceso a orientación del sindicato o seguro médico?"
</bienestar_docente>

<marcos_psicologicos>
- Maslach Burnout Inventory: agotamiento emocional, despersonalización, baja realización personal.
- Self-Determination Theory (Deci & Ryan): necesidades de autonomía, competencia y conexión en el docente.
- Mindfulness-Based Stress Reduction: cuando el maestro lo pida, da ejercicios de 2 minutos aplicables en el salón.
- CNV (Comunicación No Violenta): para conflictos con alumnos, padres o directivos.
</marcos_psicologicos>

<reglas>
- Máximo 4 líneas cuando el tema es pedagógico.
- Sin límite cuando el maestro habla de cómo se siente — ahí le das espacio real.
- NUNCA le digas "eso es normal" o "todos los maestros lo sienten" — minimiza su experiencia.
- SIEMPRE termina con una pregunta abierta o una acción concreta — nunca con un párrafo cerrado.
</reglas>

Primer mensaje: "¿Cómo estás tú hoy — el maestro, no el grupo?" — directo al maestro primero."""

PROMPT_MAESTRO_BIENESTAR = """<role>Eres EVOLUCIÓN en modo bienestar docente.</role>

{nombre} es un maestro/a que necesita apoyo.

<framework>
- Detecta el nivel de estrés: leve (necesita ventilarse) / moderado (necesita estrategias) / severo (necesita derivación)
- Aplica primero validación, después estrategia, nunca al revés.
- Herramientas inmediatas: respiración 4-7-8, técnica 5-4-3-2-1, ancla corporal de 60 segundos.
- Si menciona síntomas físicos persistentes (insomnio, dolor de cabeza crónico, llanto), sugiere buscar ayuda profesional.
- Maslach: si hay los 3 síntomas (agotamiento + despersonalización + baja realización), es burnout — no estrés normal.
</framework>

<reglas>
1. Empieza con una pregunta, no con consejos.
2. NAME IT TO TAME IT: si el maestro explota o está abrumado, nombra la emoción exacta que describes.
3. CERO FRASES VACÍAS: prohibido "te entiendo", "anímate", "tú puedes". En cambio: "Lo que describes suena a agotamiento real, no a debilidad."
4. Si el maestro dice "ya no quiero ir a trabajar" o "no puedo más de verdad" — eso es señal severa. Responde con apoyo real, no con motivación.
5. Máximo 4 líneas. El espacio lo abres con preguntas, no con párrafos.
</reglas>

Estado reportado: {estado}
Historial de la sesión: {historial_txt}

Primera vez que abre este espacio: "Este es tu espacio. ¿Qué te está pesando hoy?"</p>"""

PROMPT_PADRE = """Eres el aliado de {nombre} en la crianza de {teen}.

QUIÉN ERES:
Das opciones reales — Faber & Mazlish, comunicación no violenta, crianza con límites.
No ordenas, no juzgas. Propones alternativas con consecuencias reales.
Cuando hay un acuerdo que el padre/madre debe cumplir, lo mencionas con respeto — la palabra de los padres es lo más valioso que tienen.

ACUERDOS ACTIVOS (tu parte):
{acuerdos}

SEÑALES RECIENTES (sin revelar contenido de conversaciones del teen):
{alertas}

Máximo 4 líneas. Si hay acuerdo pendiente de tu parte, menciónalo con naturalidad al final."""

# ── DB ────────────────────────────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS familias (
                id TEXT PRIMARY KEY, nombre TEXT NOT NULL,
                codigo_acceso TEXT UNIQUE, creado REAL
            );
            CREATE TABLE IF NOT EXISTS miembros (
                id TEXT PRIMARY KEY, familia_id TEXT NOT NULL,
                nombre TEXT NOT NULL, rol TEXT NOT NULL,
                edad INTEGER DEFAULT 15, pin_hash TEXT,
                puntos_total INTEGER DEFAULT 0,
                active_context TEXT DEFAULT '{}',
                activo INTEGER DEFAULT 1, creado REAL
            );
            CREATE TABLE IF NOT EXISTS mood_history (
                id TEXT PRIMARY KEY, miembro_id TEXT NOT NULL,
                score INTEGER NOT NULL, nota TEXT, creado REAL
            );
            CREATE TABLE IF NOT EXISTS misiones (
                id TEXT PRIMARY KEY, familia_id TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT,
                puntos INTEGER DEFAULT 10, asignado_a TEXT,
                estado TEXT DEFAULT 'pendiente',
                evidencia_url TEXT, aprobado_por TEXT,
                creado REAL, completado REAL, aprobado REAL
            );
            CREATE TABLE IF NOT EXISTS acuerdos (
                id TEXT PRIMARY KEY, familia_id TEXT NOT NULL,
                teen_id TEXT NOT NULL, descripcion TEXT NOT NULL,
                condicion TEXT, recompensa TEXT,
                propuesto_por TEXT DEFAULT 'padre',
                estado TEXT DEFAULT 'propuesto',
                creado REAL, cumplido REAL
            );
            CREATE TABLE IF NOT EXISTS alertas (
                id TEXT PRIMARY KEY, familia_id TEXT NOT NULL,
                teen_id TEXT NOT NULL, tipo TEXT NOT NULL,
                resumen TEXT, sugerencia TEXT,
                visto INTEGER DEFAULT 0, creado REAL
            );
            CREATE TABLE IF NOT EXISTS deseos (
                id TEXT PRIMARY KEY, teen_id TEXT NOT NULL,
                familia_id TEXT NOT NULL, descripcion TEXT NOT NULL,
                puntos_necesarios INTEGER DEFAULT 0,
                estado TEXT DEFAULT 'activo', creado REAL
            );
            CREATE TABLE IF NOT EXISTS logros (
                id TEXT PRIMARY KEY, miembro_id TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT,
                icono TEXT DEFAULT 'star', creado REAL
            );
            CREATE TABLE IF NOT EXISTS conversaciones (
                id TEXT PRIMARY KEY, miembro_id TEXT NOT NULL,
                familia_id TEXT NOT NULL, rol TEXT NOT NULL,
                mensaje TEXT NOT NULL, respuesta TEXT NOT NULL,
                creado REAL
            );
            CREATE TABLE IF NOT EXISTS metas (
                id TEXT PRIMARY KEY, teen_id TEXT NOT NULL,
                familia_id TEXT NOT NULL, titulo TEXT NOT NULL,
                descripcion TEXT, plazo TEXT,
                progreso INTEGER DEFAULT 0,
                estado TEXT DEFAULT 'activa', creado REAL
            );
            CREATE TABLE IF NOT EXISTS aptitudes (
                id TEXT PRIMARY KEY, teen_id TEXT NOT NULL,
                tipo TEXT NOT NULL, descripcion TEXT,
                confianza INTEGER DEFAULT 1,
                detectado REAL, fuente TEXT DEFAULT 'conversacion'
            );
            CREATE TABLE IF NOT EXISTS modulos (
                familia_id TEXT NOT NULL, modulo TEXT NOT NULL,
                activo INTEGER DEFAULT 1,
                PRIMARY KEY (familia_id, modulo)
            );
            CREATE TABLE IF NOT EXISTS regularizacion (
                id TEXT PRIMARY KEY, teen_id TEXT NOT NULL,
                materia TEXT NOT NULL, nivel TEXT DEFAULT 'secundaria',
                sesiones INTEGER DEFAULT 0,
                estado TEXT DEFAULT 'activa', iniciado REAL
            );
            CREATE TABLE IF NOT EXISTS escuelas (
                id TEXT PRIMARY KEY, nombre TEXT NOT NULL,
                tipo TEXT DEFAULT 'laico', codigo TEXT UNIQUE,
                carisma TEXT DEFAULT '', activo INTEGER DEFAULT 1, creado REAL
            );
            CREATE TABLE IF NOT EXISTS escuela_familias (
                escuela_id TEXT NOT NULL, familia_id TEXT NOT NULL,
                PRIMARY KEY (escuela_id, familia_id)
            );
            CREATE TABLE IF NOT EXISTS maestros (
                id TEXT PRIMARY KEY, escuela_id TEXT NOT NULL,
                nombre TEXT NOT NULL, materia TEXT DEFAULT '',
                grado TEXT DEFAULT '', activo INTEGER DEFAULT 1, creado REAL
            );
            CREATE TABLE IF NOT EXISTS maestro_mood (
                id TEXT PRIMARY KEY, maestro_id TEXT NOT NULL,
                score INTEGER NOT NULL, nota TEXT, creado REAL
            );
        """)
        await db.commit()

@app.on_event("startup")
async def startup():
    nexus_db = os.getenv("NEXUS_TEENS_DB", r"C:\NEXUS_v3_NEW\output\nexus_teens.db")
    if not os.path.exists(DB_PATH) and os.path.exists(nexus_db):
        shutil.copy2(nexus_db, DB_PATH)
        logger.info("DB migrada desde NEXUS Teens")
    await init_db()
    await _crear_demo_si_falta()
    logger.info(f"Evolución corriendo — puerto {PORT}")

async def _crear_demo_si_falta():
    """Crea familia DEMO01 y miembros demo si no existen — sobrevive reinicios."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id FROM familias WHERE codigo_acceso=?", ("DEMO01",))
        row = await cur.fetchone()
        if row:
            return  # ya existe
        fid = "demo-fam-01"
        await db.execute("INSERT OR IGNORE INTO familias VALUES (?,?,?,?)",
                         (fid, "Familia Demo Evolución", "DEMO01", time.time()))
        pin_hash = hashlib.sha256("1234".encode()).hexdigest()
        await db.execute(
            "INSERT OR IGNORE INTO miembros VALUES (?,?,?,?,?,?,0,'{}',1,?)",
            ("demo-padre-01", fid, "Papá Demo", "padre", 40, pin_hash, time.time()))
        await db.execute(
            "INSERT OR IGNORE INTO miembros VALUES (?,?,?,?,?,?,0,'{}',1,?)",
            ("demo-teen-01", fid, "Demo Teen", "teen", 16, None, time.time()))
        await db.commit()
        logger.info("Demo DEMO01/1234 creado automáticamente")

# ── IA ────────────────────────────────────────────────────────────────────────
async def llamar_ia(prompt: str, mensaje: str, historial: list = None) -> str:
    if ZAI_API_KEY:
        r = await _zai(prompt, mensaje, historial)
        if r: return r
    if GROQ_API_KEY:
        r = await _groq(prompt, mensaje, historial)
        if r: return r
    r = await _ollama(prompt, mensaje, historial)
    if r: return r
    return "Sin conexión por el momento. Intenta en un momento."

async def _zai(prompt: str, mensaje: str, historial: list = None) -> Optional[str]:
    try:
        from openai import OpenAI
        c = OpenAI(api_key=ZAI_API_KEY, base_url="https://open.bigmodel.cn/api/paas/v4/", timeout=8.0)
        msgs = [{"role":"system","content":prompt}]
        if historial: msgs.extend(historial[-6:])
        msgs.append({"role":"user","content":mensaje})
        loop = asyncio.get_event_loop()
        r = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: c.chat.completions.create(
                model="glm-4-flash", messages=msgs, max_tokens=400, temperature=0.85)),
            timeout=10.0)
        return r.choices[0].message.content
    except Exception as e:
        logger.warning("Z.ai: %s", str(e)[:60])
        return None

async def _groq(prompt: str, mensaje: str, historial: list = None) -> Optional[str]:
    try:
        from groq import Groq
        c = Groq(api_key=GROQ_API_KEY, timeout=12.0)
        msgs = [{"role":"system","content":prompt}]
        if historial: msgs.extend(historial[-4:])
        msgs.append({"role":"user","content":mensaje})
        loop = asyncio.get_event_loop()
        r = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: c.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=msgs, max_tokens=500, temperature=0.85)),
            timeout=15.0)
        return r.choices[0].message.content
    except Exception as e:
        logger.warning("Groq: %s", str(e)[:60])
        return None

async def _ollama(prompt: str, mensaje: str, historial: list = None) -> Optional[str]:
    try:
        import httpx
        msgs = [{"role":"system","content":prompt[:2000]}]
        if historial: msgs.extend(historial[-4:])
        msgs.append({"role":"user","content":mensaje})
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post("http://localhost:11434/api/chat",
                json={"model":"dolphin-mistral:7b","messages":msgs,"stream":False})
            if r.status_code == 200:
                return r.json().get("message",{}).get("content","")
        return None
    except Exception as e:
        logger.warning("Ollama: %s", str(e)[:60])
        return None

# ── Helpers DB ────────────────────────────────────────────────────────────────
async def get_miembro(db, mid: str) -> Optional[dict]:
    db.row_factory = aiosqlite.Row
    cur = await db.execute("SELECT * FROM miembros WHERE id=? AND activo=1", (mid,))
    row = await cur.fetchone()
    return dict(row) if row else None

async def get_last_mood(db, mid: str) -> str:
    cur = await db.execute(
        "SELECT score, nota FROM mood_history WHERE miembro_id=? ORDER BY creado DESC LIMIT 1", (mid,))
    row = await cur.fetchone()
    if not row: return "sin registro"
    etiq = {1:"muy bajo",2:"bajo",3:"regular",4:"bien",5:"muy bien"}
    return f"{etiq.get(row[0],str(row[0]))}{' — '+row[1] if row[1] else ''}"

async def get_acuerdos_teen(db, fid: str, mid: str) -> str:
    cur = await db.execute(
        "SELECT descripcion FROM acuerdos WHERE familia_id=? AND teen_id=? AND estado='activo'", (fid, mid))
    rows = await cur.fetchall()
    return ", ".join(r[0] for r in rows) if rows else "ninguno"

async def registrar_alerta(db, fid: str, tid: str, tipo: str):
    sugerencia = SUGERENCIAS_PADRES.get(tipo, "Mantén canales de comunicación abiertos.")
    await db.execute("INSERT INTO alertas VALUES (?,?,?,?,?,?,0,?)",
        (str(uuid.uuid4())[:8], fid, tid, tipo, f"Tema: {tipo}", sugerencia, time.time()))
    await _notificar("alerta_evo", {"tipo": tipo, "sugerencia": sugerencia}, canal=f"padres_{fid}")

# ── Models ────────────────────────────────────────────────────────────────────
class RegistrarFamilia(BaseModel):
    nombre: str
    codigo_acceso: Optional[str] = None

class RegistrarMiembro(BaseModel):
    familia_id: str
    nombre: str
    rol: str
    edad: int = 15
    pin: Optional[str] = None

class ChatRequest(BaseModel):
    miembro_id: str
    mensaje: str
    familia_id: Optional[str] = None

class CrearMision(BaseModel):
    familia_id: str
    titulo: str
    descripcion: Optional[str] = None
    puntos: int = 10
    asignado_a: Optional[str] = None

class AprobarMision(BaseModel):
    familia_id: str
    aprobado_por: str
    pin_padre: str

class CompletarMision(BaseModel):
    evidencia_url: Optional[str] = None

class CrearAcuerdo(BaseModel):
    familia_id: str
    teen_id: str
    descripcion: str
    condicion: Optional[str] = None
    recompensa: Optional[str] = None
    propuesto_por: str = "padre"

class AgregarDeseo(BaseModel):
    teen_id: str
    familia_id: str
    descripcion: str
    puntos_necesarios: int = 0

class QuickMood(BaseModel):
    miembro_id: str
    score: int
    nota: Optional[str] = None

class CrearMeta(BaseModel):
    teen_id: str
    familia_id: str
    titulo: str
    descripcion: Optional[str] = None
    plazo: Optional[str] = None

# ── Rutas principales ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "landing.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()

@app.get("/app", response_class=HTMLResponse)
async def app_panel():
    html_path = os.path.join(os.path.dirname(__file__), "evolucion.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()

@app.get("/deck/familias", response_class=HTMLResponse)
async def deck_familias():
    with open(os.path.join(os.path.dirname(__file__), "deck_familias.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/deck/sep", response_class=HTMLResponse)
async def deck_sep():
    with open(os.path.join(os.path.dirname(__file__), "deck_sep.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/deck/teens", response_class=HTMLResponse)
async def deck_teens():
    with open(os.path.join(os.path.dirname(__file__), "deck_teens.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/deck/inversores", response_class=HTMLResponse)
async def deck_inversores():
    with open(os.path.join(os.path.dirname(__file__), "deck_inversores.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/deck/sep2", response_class=HTMLResponse)
async def deck_sep2():
    with open(os.path.join(os.path.dirname(__file__), "deck_sep2.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/deck/teens2", response_class=HTMLResponse)
async def deck_teens2():
    with open(os.path.join(os.path.dirname(__file__), "deck_teens2.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/manifest.json")
async def manifest():
    return {
        "name": "Evolución",
        "short_name": "Evolución",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#030308",
        "theme_color": "#00e5a0",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }

@app.get("/health")
async def health():
    return {"status": "ok", "producto": "Evolución", "version": "2.0"}

# ── Helpers perfil y aptitudes ────────────────────────────────────────────────
def detectar_perfil_mensaje(texto: str) -> Optional[str]:
    t = texto.lower()
    for perfil, patrones in PERFILES_PATRONES.items():
        if sum(1 for p in patrones if p in t) >= 1:
            return perfil
    return None

def detectar_aptitudes_mensaje(texto: str) -> list:
    t = texto.lower()
    encontradas = []
    for apt, patrones in APTITUDES_PATRONES.items():
        if any(p in t for p in patrones):
            encontradas.append(apt)
    return encontradas

async def extraer_aptitudes_ia(db, teen_id: str, mensaje: str, respuesta: str):
    try:
        aptitudes = detectar_aptitudes_mensaje(mensaje + " " + respuesta)
        for apt in aptitudes:
            eid = str(uuid.uuid4())[:8]
            await db.execute(
                "INSERT OR IGNORE INTO aptitudes VALUES (?,?,?,?,1,?,?)",
                (eid, teen_id, apt, f"Detectado en conversación", time.time(), "conversacion"))
    except Exception:
        pass

async def get_modulos_familia(db, fid: str) -> dict:
    cur = await db.execute("SELECT modulo, activo FROM modulos WHERE familia_id=?", (fid,))
    rows = await cur.fetchall()
    modulos = {r[0]: bool(r[1]) for r in rows}
    defaults = {
        "apoyo_psicologico": True, "gestion_emocional": True,
        "tutor_academico": True, "regularizacion": True,
        "orientacion_vocacional": True, "aptitudes": True,
        "metas": True, "modo_gifted": False,
        "modo_visionario": False, "modulo_canonico": False,
        "busqueda_web": True,
    }
    defaults.update(modulos)
    return defaults

async def get_carisma_escuela(db, fid: str) -> str:
    cur = await db.execute(
        "SELECT e.carisma FROM escuelas e JOIN escuela_familias ef ON e.id=ef.escuela_id WHERE ef.familia_id=?", (fid,))
    row = await cur.fetchone()
    return row[0] if row else ""

# ── Familia & Miembros ────────────────────────────────────────────────────────
@app.post("/api/familias")
async def registrar_familia(req: RegistrarFamilia):
    fid = str(uuid.uuid4())[:8]
    codigo = req.codigo_acceso or str(uuid.uuid4())[:6].upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO familias VALUES (?,?,?,?)", (fid, req.nombre, codigo, time.time()))
        await db.commit()
    return {"ok": True, "familia_id": fid, "codigo_acceso": codigo}

@app.get("/api/familias/codigo/{codigo}")
async def buscar_familia(codigo: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, nombre FROM familias WHERE codigo_acceso=?", (codigo.upper(),))
        row = await cur.fetchone()
    if not row: return {"ok": False, "error": "Código no válido"}
    return {"ok": True, "familia_id": dict(row)["id"], "nombre": dict(row)["nombre"]}

@app.post("/api/miembros")
async def registrar_miembro(req: RegistrarMiembro):
    mid = str(uuid.uuid4())[:8]
    pin_hash = hashlib.sha256(req.pin.encode()).hexdigest() if req.pin else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO miembros VALUES (?,?,?,?,?,?,0,'{}',1,?)",
            (mid, req.familia_id, req.nombre, req.rol, req.edad, pin_hash, time.time()))
        await db.commit()
    return {"ok": True, "miembro_id": mid, "nombre": req.nombre, "rol": req.rol}

@app.get("/api/miembros/{mid}")
async def ver_miembro(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id,familia_id,nombre,rol,edad,puntos_total,active_context FROM miembros WHERE id=? AND activo=1", (mid,))
        row = await cur.fetchone()
    if not row: return {"ok": False, "error": "No encontrado"}
    d = dict(row)
    try:
        ctx = json.loads(d.pop("active_context") or "{}")
        d["perfil"] = ctx.get("perfil", "estandar")
    except Exception:
        d.pop("active_context", None)
        d["perfil"] = "estandar"
    return {"ok": True, **d}

@app.get("/api/familia/{fid}")
async def ver_familia(fid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id,nombre,rol,edad,puntos_total FROM miembros WHERE familia_id=? AND activo=1", (fid,))
        miembros = [dict(r) for r in await cur.fetchall()]
        cur2 = await db.execute("SELECT COUNT(*) FROM misiones WHERE familia_id=? AND estado='pendiente'", (fid,))
        pendientes = (await cur2.fetchone())[0]
        cur3 = await db.execute("SELECT COUNT(*) FROM misiones WHERE familia_id=? AND estado='completada'", (fid,))
        completadas = (await cur3.fetchone())[0]
        cur4 = await db.execute("SELECT id,descripcion,recompensa,teen_id FROM acuerdos WHERE familia_id=? AND estado='activo'", (fid,))
        acuerdos = [dict(r) for r in await cur4.fetchall()]
        cur5 = await db.execute("SELECT COUNT(*) FROM alertas WHERE familia_id=? AND visto=0", (fid,))
        alertas_nuevas = (await cur5.fetchone())[0]
    return {"ok": True, "miembros": miembros, "misiones_pendientes": pendientes,
            "misiones_completadas": completadas, "acuerdos_activos": acuerdos,
            "alertas_nuevas": alertas_nuevas}

# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(req: ChatRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        miembro = await get_miembro(db, req.miembro_id)
        if not miembro:
            return {"ok": False, "error": "Miembro no encontrado"}

        rol    = miembro["rol"]
        nombre = miembro["nombre"]
        fid    = miembro["familia_id"]
        mensaje = req.mensaje.strip()

        # Riesgo vital — respuesta fija, no delegada a IA
        if rol in ("teen","hermano") and detectar_riesgo(mensaje):
            respuesta = "Oye, lo que acabas de decir no lo voy a guardar solo. Es una alerta de seguridad y voy a pedirle a tu familia que te acompañe en esto. No es para castigarte — es para que no cargues solo con eso."
            await registrar_alerta(db, fid, req.miembro_id, "riesgo_alto")
            await db.execute("INSERT INTO conversaciones VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4())[:8], req.miembro_id, fid, rol, mensaje, respuesta, time.time()))
            await db.commit()
            return {"ok": True, "respuesta": respuesta, "alerta": "riesgo_alto"}

        # Temas sensibles
        if rol in ("teen","hermano") and mensaje:
            tema = detectar_tema(mensaje)
            if tema:
                await registrar_alerta(db, fid, req.miembro_id, tema)
                await db.commit()

        # Historial
        cur_h = await db.execute(
            "SELECT mensaje, respuesta FROM conversaciones WHERE miembro_id=? ORDER BY creado DESC LIMIT 4",
            (req.miembro_id,))
        rows_h = await cur_h.fetchall()
        historial = []
        for h in reversed(rows_h):
            historial += [{"role":"user","content":h[0]},{"role":"assistant","content":h[1]}]

        # Prompt
        if rol in ("padre","madre"):
            # Prompt padre
            cur_t = await db.execute(
                "SELECT nombre FROM miembros WHERE familia_id=? AND rol IN ('teen','hermano') LIMIT 1", (fid,))
            tr = await cur_t.fetchone()
            teen_nombre = tr[0] if tr else "tu hijo/a"
            cur_a = await db.execute(
                "SELECT descripcion, recompensa FROM acuerdos WHERE familia_id=? AND estado='activo'", (fid,))
            acuerdos = [dict(r) for r in await cur_a.fetchall()]
            acuerdos_txt = "\n".join(f"• {a['descripcion']} → {a['recompensa'] or '—'}" for a in acuerdos) or "Sin acuerdos activos."
            cur_al = await db.execute(
                "SELECT tipo, sugerencia FROM alertas WHERE familia_id=? AND visto=0 ORDER BY creado DESC LIMIT 3", (fid,))
            alertas = [dict(r) for r in await cur_al.fetchall()]
            alertas_txt = "\n".join(f"[{a['tipo']}] {a['sugerencia']}" for a in alertas) or "Sin señales recientes."
            prompt = PROMPT_PADRE.format(nombre=nombre, teen=teen_nombre,
                                          acuerdos=acuerdos_txt, alertas=alertas_txt)
        else:
            last_mood = await get_last_mood(db, req.miembro_id)
            acuerdos  = await get_acuerdos_teen(db, fid, req.miembro_id)
            ctx_raw   = miembro.get("active_context") or "{}"
            try: ctx = json.loads(ctx_raw)
            except: ctx = {}
            contexto = ctx.get("tema_principal","ninguno")
            perfil_ctx = ctx.get("perfil","estandar")
            materia  = detectar_materia(mensaje)
            modulos  = await get_modulos_familia(db, fid)
            carisma  = await get_carisma_escuela(db, fid)

            # Detección dinámica de perfil por mensaje
            perfil_msg = detectar_perfil_mensaje(mensaje)
            if perfil_msg and perfil_msg != perfil_ctx:
                ctx["perfil"] = perfil_msg
                await db.execute("UPDATE miembros SET active_context=? WHERE id=?",
                    (json.dumps(ctx, ensure_ascii=False), req.miembro_id))
                perfil_ctx = perfil_msg

            # Verificar regularización activa
            cur_reg = await db.execute(
                "SELECT materia, nivel, sesiones FROM regularizacion WHERE teen_id=? AND estado='activa' ORDER BY iniciado DESC LIMIT 1",
                (req.miembro_id,))
            reg = await cur_reg.fetchone()

            if reg and modulos.get("regularizacion", True):
                await db.execute("UPDATE regularizacion SET sesiones=sesiones+1 WHERE teen_id=? AND estado='activa'", (req.miembro_id,))
                prompt = PROMPT_REGULARIZACION.format(
                    nombre=nombre, edad=miembro.get("edad",15),
                    materia=reg[0], nivel=reg[1], sesion_num=reg[2]+1)
            elif modulos.get("modulo_canonico") and (perfil_ctx == "canonico" or carisma):
                prompt = PROMPT_CANONICO.format(nombre=nombre, edad=miembro.get("edad",15),
                    last_mood=last_mood, contexto=contexto, carisma=carisma or "desarrollo humano integral")
            elif modulos.get("modo_gifted") and perfil_ctx == "gifted":
                prompt = PROMPT_GIFTED.format(nombre=nombre, edad=miembro.get("edad",15),
                    last_mood=last_mood, contexto=contexto)
            elif modulos.get("modo_visionario") and perfil_ctx == "visionario":
                prompt = PROMPT_VISIONARIO.format(nombre=nombre, edad=miembro.get("edad",15),
                    last_mood=last_mood, contexto=contexto)
            else:
                prompt = PROMPT_TEEN.format(nombre=nombre, edad=miembro.get("edad",15),
                    last_mood=last_mood, contexto=contexto, acuerdos=acuerdos)
            if materia and not reg:
                prompt += f"\n\nNota: tema actual es {materia}. Aplica tutor_mode."

        if not mensaje:
            saludo = f"Hola {nombre}. ¿Qué quieres revisar?" if rol in ("padre","madre") else "Aquí estoy. Qué hay."
            return {"ok": True, "respuesta": saludo}

        respuesta = await llamar_ia(prompt, mensaje, historial)

        await db.execute("INSERT INTO conversaciones VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:8], req.miembro_id, fid, rol, mensaje, respuesta, time.time()))

        # Cache de contexto (best-effort)
        try:
            resumen_prompt = 'Extrae en JSON: {"tema_principal":"X","estado_emocional":"Y"}. Solo JSON.'
            ctx_txt = await llamar_ia(resumen_prompt, f"Mensaje: {mensaje}\nRespuesta: {respuesta}")
            s = ctx_txt.find("{"); e = ctx_txt.rfind("}") + 1
            if s >= 0 and e > s:
                nuevo_ctx = json.loads(ctx_txt[s:e])
                await db.execute("UPDATE miembros SET active_context=? WHERE id=?",
                    (json.dumps(nuevo_ctx, ensure_ascii=False), req.miembro_id))
        except Exception:
            pass

        # Extracción asíncrona de aptitudes
        if rol in ("teen","hermano"):
            await extraer_aptitudes_ia(db, req.miembro_id, mensaje, respuesta)

        await db.commit()
        perfil_info = perfil_ctx if rol in ("teen","hermano") else None
        return {"ok": True, "respuesta": respuesta, "rol": rol, "perfil": perfil_info}

# ── Mood ──────────────────────────────────────────────────────────────────────
@app.post("/api/mood")
async def mood(req: QuickMood):
    if not 1 <= req.score <= 5:
        raise HTTPException(400, "score 1-5")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO mood_history VALUES (?,?,?,?,?)",
            (str(uuid.uuid4())[:8], req.miembro_id, req.score, req.nota, time.time()))
        await db.commit()
    etiq = {1:"Notado.",2:"Ok.",3:"Copy.",4:"Bien.",5:"Qué bueno."}
    return {"ok": True, "respuesta": etiq.get(req.score, "Ok.")}

# ── Misiones ──────────────────────────────────────────────────────────────────
@app.get("/api/misiones/{fid}")
async def listar_misiones(fid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM misiones WHERE familia_id=? ORDER BY creado DESC", (fid,))
        rows = await cur.fetchall()
    return {"ok": True, "misiones": [dict(r) for r in rows]}

@app.post("/api/misiones")
async def crear_mision(req: CrearMision):
    mid = str(uuid.uuid4())[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO misiones VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, req.familia_id, req.titulo, req.descripcion, req.puntos,
             req.asignado_a, "pendiente", None, None, time.time(), None, None))
        await db.commit()
    await _notificar("mision_creada", {"titulo": req.titulo, "puntos": req.puntos},
                     canal=f"familia_{req.familia_id}")
    return {"ok": True, "id": mid, "mensaje": f"Misión '{req.titulo}' creada — {req.puntos} pts"}

@app.put("/api/misiones/{mid}/completar")
async def completar_mision(mid: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    evidencia_url = body.get("evidencia_url") if body else None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM misiones WHERE id=?", (mid,))
        m = await cur.fetchone()
        if not m: raise HTTPException(404, "No encontrada")
        m = dict(m)
        if m["estado"] != "pendiente": raise HTTPException(400, "No está pendiente")
        await db.execute("UPDATE misiones SET estado='completada', evidencia_url=?, completado=? WHERE id=?",
            (evidencia_url, time.time(), mid))
        await db.commit()
    await _notificar("mision_completada", {"titulo": m["titulo"]}, canal=f"padres_{m['familia_id']}")
    return {"ok": True, "mensaje": f"'{m['titulo']}' completada — esperando aprobación"}

@app.put("/api/misiones/{mid}/aprobar")
async def aprobar_mision(mid: str, req: AprobarMision):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM misiones WHERE id=?", (mid,))
        row = await cur.fetchone()
        if not row: raise HTTPException(404, "No encontrada")
        m = dict(row)
        if m["estado"] != "completada": raise HTTPException(400, "No completada aún")
        pin_hash = hashlib.sha256(req.pin_padre.encode()).hexdigest()
        cur2 = await db.execute(
            "SELECT id FROM miembros WHERE familia_id=? AND rol IN ('padre','madre') AND pin_hash=?",
            (req.familia_id, pin_hash))
        if not await cur2.fetchone(): raise HTTPException(401, "PIN incorrecto")
        await db.execute("UPDATE misiones SET estado='aprobada', aprobado_por=?, aprobado=? WHERE id=?",
            (req.aprobado_por, time.time(), mid))
        if m.get("asignado_a"):
            await db.execute("UPDATE miembros SET puntos_total=puntos_total+? WHERE id=?",
                (m["puntos"], m["asignado_a"]))
            cur3 = await db.execute("SELECT puntos_total FROM miembros WHERE id=?", (m["asignado_a"],))
            pts = (await cur3.fetchone())[0]
            for umbral, titulo in [(500,"Imparable"),(200,"En llamas"),(100,"Centurión"),(50,"Arranque")]:
                if pts >= umbral and (pts - m["puntos"]) < umbral:
                    await db.execute("INSERT INTO logros VALUES (?,?,?,?,?,?)",
                        (str(uuid.uuid4())[:8], m["asignado_a"], titulo,
                         f"{umbral} puntos acumulados", "star", time.time()))
        await db.commit()
    return {"ok": True, "puntos_asignados": m["puntos"], "mensaje": f"Aprobada — +{m['puntos']} pts"}

# ── Acuerdos ──────────────────────────────────────────────────────────────────
@app.get("/api/acuerdos/{fid}")
async def listar_acuerdos(fid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM acuerdos WHERE familia_id=? ORDER BY creado DESC", (fid,))
        rows = await cur.fetchall()
    return {"ok": True, "acuerdos": [dict(r) for r in rows]}

@app.post("/api/acuerdos")
async def crear_acuerdo(req: CrearAcuerdo):
    aid = str(uuid.uuid4())[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO acuerdos VALUES (?,?,?,?,?,?,?,?,?,?)",
            (aid, req.familia_id, req.teen_id, req.descripcion, req.condicion,
             req.recompensa, req.propuesto_por, "propuesto", time.time(), None))
        await db.commit()
    return {"ok": True, "acuerdo_id": aid, "mensaje": "Acuerdo registrado. Actívalo para que valga."}

@app.put("/api/acuerdos/{aid}/activar")
async def activar_acuerdo(aid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE acuerdos SET estado='activo' WHERE id=?", (aid,))
        await db.commit()
    return {"ok": True, "mensaje": "Acuerdo activo."}

@app.put("/api/acuerdos/{aid}/cumplir")
async def cumplir_acuerdo(aid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM acuerdos WHERE id=?", (aid,))
        row = await cur.fetchone()
        if not row: raise HTTPException(404, "Acuerdo no encontrado")
        ac = dict(row)
        await db.execute("UPDATE acuerdos SET estado='cumplido', cumplido=? WHERE id=?", (time.time(), aid))
        await db.execute("UPDATE miembros SET puntos_total=puntos_total+50 WHERE id=?", (ac["teen_id"],))
        await db.commit()
    return {"ok": True, "mensaje": "Acuerdo cumplido. +50 pts."}

# ── Deseos ────────────────────────────────────────────────────────────────────
@app.post("/api/deseos")
async def agregar_deseo(req: AgregarDeseo):
    did = str(uuid.uuid4())[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO deseos VALUES (?,?,?,?,?,?,?)",
            (did, req.teen_id, req.familia_id, req.descripcion,
             req.puntos_necesarios, "activo", time.time()))
        await db.commit()
    return {"ok": True, "deseo_id": did, "mensaje": f"'{req.descripcion}' en tu lista."}

@app.get("/api/deseos/{teen_id}")
async def ver_deseos(teen_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT d.id, d.descripcion, d.puntos_necesarios, m.puntos_total "
            "FROM deseos d JOIN miembros m ON d.teen_id=m.id "
            "WHERE d.teen_id=? AND d.estado='activo' ORDER BY d.puntos_necesarios ASC", (teen_id,))
        deseos = [dict(r) for r in await cur.fetchall()]
    return {"ok": True, "deseos": deseos}

# ── Alertas ───────────────────────────────────────────────────────────────────
@app.get("/api/alertas/{fid}")
async def ver_alertas(fid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT tipo, resumen, sugerencia, creado FROM alertas WHERE familia_id=? ORDER BY creado DESC LIMIT 20", (fid,))
        alertas = [dict(r) for r in await cur.fetchall()]
        await db.execute("UPDATE alertas SET visto=1 WHERE familia_id=?", (fid,))
        await db.commit()
    return {"ok": True, "alertas": alertas}

# ── Logros ────────────────────────────────────────────────────────────────────
@app.get("/api/logros/{mid}")
async def ver_logros(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT titulo, descripcion, icono, creado FROM logros WHERE miembro_id=? ORDER BY creado DESC", (mid,))
        logros = [dict(r) for r in await cur.fetchall()]
    return {"ok": True, "logros": logros}

# ── Metas ─────────────────────────────────────────────────────────────────────
@app.post("/api/metas")
async def crear_meta(req: CrearMeta):
    mid = str(uuid.uuid4())[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO metas VALUES (?,?,?,?,?,?,0,'activa',?)",
            (mid, req.teen_id, req.familia_id, req.titulo,
             req.descripcion, req.plazo, time.time()))
        await db.commit()
    return {"ok": True, "meta_id": mid, "mensaje": f"Meta '{req.titulo}' registrada."}

@app.get("/api/metas/{teen_id}")
async def ver_metas(teen_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM metas WHERE teen_id=? AND estado='activa' ORDER BY creado DESC", (teen_id,))
        metas = [dict(r) for r in await cur.fetchall()]
    return {"ok": True, "metas": metas}

@app.put("/api/metas/{mid}/avanzar")
async def avanzar_meta(mid: str, request: Request):
    body = await request.json()
    progreso = min(100, max(0, int(body.get("progreso", 10))))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE metas SET progreso=? WHERE id=?", (progreso, mid))
        if progreso >= 100:
            await db.execute("UPDATE metas SET estado='lograda' WHERE id=?", (mid,))
        await db.commit()
    return {"ok": True, "progreso": progreso, "mensaje": "Meta actualizada." if progreso < 100 else "¡Meta lograda!"}

# ── Aptitudes ────────────────────────────────────────────────────────────────
@app.get("/api/aptitudes/{mid}")
async def ver_aptitudes(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT tipo, descripcion, confianza, detectado FROM aptitudes WHERE teen_id=? ORDER BY confianza DESC, detectado DESC", (mid,))
        rows = await cur.fetchall()
    return {"ok": True, "aptitudes": [dict(r) for r in rows]}

# ── Módulos ───────────────────────────────────────────────────────────────────
@app.get("/api/modulos/{fid}")
async def ver_modulos(fid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        modulos = await get_modulos_familia(db, fid)
    return {"ok": True, "modulos": modulos}

@app.put("/api/modulos/{fid}")
async def actualizar_modulo(fid: str, request: Request):
    body = await request.json()
    modulo = body.get("modulo")
    activo = body.get("activo", True)
    if not modulo:
        raise HTTPException(400, "modulo requerido")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO modulos (familia_id, modulo, activo) VALUES (?,?,?)",
            (fid, modulo, 1 if activo else 0))
        await db.commit()
    return {"ok": True, "modulo": modulo, "activo": activo}

# ── Regularización ────────────────────────────────────────────────────────────
class IniciarRegularizacion(BaseModel):
    teen_id: str
    materia: str
    nivel: str = "secundaria"

@app.post("/api/regularizacion/iniciar")
async def iniciar_regularizacion(req: IniciarRegularizacion):
    rid = str(uuid.uuid4())[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE regularizacion SET estado='pausada' WHERE teen_id=? AND estado='activa'", (req.teen_id,))
        await db.execute("INSERT INTO regularizacion VALUES (?,?,?,?,0,'activa',?)",
            (rid, req.teen_id, req.materia, req.nivel, time.time()))
        await db.commit()
    return {"ok": True, "id": rid, "mensaje": f"Sesión de {req.materia} iniciada. El chat ahora es tu tutor."}

@app.get("/api/regularizacion/{mid}")
async def ver_regularizacion(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM regularizacion WHERE teen_id=? ORDER BY iniciado DESC", (mid,))
        rows = await cur.fetchall()
    return {"ok": True, "sesiones": [dict(r) for r in rows]}

@app.delete("/api/regularizacion/{mid}/terminar")
async def terminar_regularizacion(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE regularizacion SET estado='completada' WHERE teen_id=? AND estado='activa'", (mid,))
        await db.commit()
    return {"ok": True, "mensaje": "Sesión de regularización completada."}

# ── Escuelas ──────────────────────────────────────────────────────────────────
class RegistrarEscuela(BaseModel):
    nombre: str
    tipo: str = "laico"
    carisma: str = ""

@app.post("/api/escuelas")
async def registrar_escuela(req: RegistrarEscuela):
    eid = str(uuid.uuid4())[:8]
    codigo = str(uuid.uuid4())[:8].upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO escuelas VALUES (?,?,?,?,?,1,?)",
            (eid, req.nombre, req.tipo, codigo, req.carisma, time.time()))
        await db.commit()
    return {"ok": True, "escuela_id": eid, "codigo": codigo,
            "mensaje": f"Escuela '{req.nombre}' registrada. Código: {codigo}"}

@app.get("/api/escuelas/{eid}")
async def ver_escuela(eid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM escuelas WHERE id=?", (eid,))
        esc = await cur.fetchone()
        if not esc: return {"ok": False, "error": "No encontrada"}
        esc = dict(esc)
        cur2 = await db.execute(
            "SELECT COUNT(*) FROM escuela_familias WHERE escuela_id=?", (eid,))
        esc["total_familias"] = (await cur2.fetchone())[0]
        cur3 = await db.execute(
            """SELECT COUNT(*) FROM alertas a
               JOIN escuela_familias ef ON a.familia_id=ef.familia_id
               WHERE ef.escuela_id=? AND a.tipo='riesgo_alto' AND a.visto=0""", (eid,))
        esc["alertas_riesgo"] = (await cur3.fetchone())[0]
    return {"ok": True, "escuela": esc}

@app.post("/api/escuelas/{eid}/vincular/{fid}")
async def vincular_familia(eid: str, fid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO escuela_familias VALUES (?,?)", (eid, fid))
        await db.commit()
    return {"ok": True, "mensaje": "Familia vinculada a la escuela."}

@app.get("/api/escuelas/{eid}/insights")
async def insights_escuela(eid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT a.tipo, COUNT(*) as total FROM aptitudes a
               JOIN miembros m ON a.teen_id=m.id
               JOIN escuela_familias ef ON m.familia_id=ef.familia_id
               WHERE ef.escuela_id=? GROUP BY a.tipo ORDER BY total DESC""", (eid,))
        aptitudes = [{"tipo": r[0], "total": r[1]} for r in await cur.fetchall()]
        cur2 = await db.execute(
            """SELECT AVG(mh.score) as mood_avg FROM mood_history mh
               JOIN miembros m ON mh.miembro_id=m.id
               JOIN escuela_familias ef ON m.familia_id=ef.familia_id
               WHERE ef.escuela_id=?""", (eid,))
        mood_row = await cur2.fetchone()
        cur3 = await db.execute(
            """SELECT COUNT(DISTINCT m.id) FROM miembros m
               JOIN escuela_familias ef ON m.familia_id=ef.familia_id
               WHERE ef.escuela_id=? AND m.rol IN ('teen','hermano')""", (eid,))
        total_teens = (await cur3.fetchone())[0]
    return {"ok": True, "total_teens": total_teens,
            "mood_promedio": round(mood_row[0] or 0, 1),
            "aptitudes_top": aptitudes[:5]}

# ── SSE ───────────────────────────────────────────────────────────────────────
@app.get("/api/eventos/{fid}")
async def eventos(fid: str):
    cid = f"familia_{fid}_{str(uuid.uuid4())[:4]}"
    return StreamingResponse(_sse_gen(cid),
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── Maestros ──────────────────────────────────────────────────────────────────
class RegistrarMaestro(BaseModel):
    escuela_id: str
    nombre: str
    materia: str = ""
    grado: str = ""

@app.post("/api/maestros")
async def registrar_maestro(req: RegistrarMaestro):
    mid = str(uuid.uuid4())[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM escuelas WHERE id=?", (req.escuela_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Escuela no encontrada")
        await db.execute("INSERT INTO maestros VALUES (?,?,?,?,?,1,?)",
            (mid, req.escuela_id, req.nombre, req.materia, req.grado, time.time()))
        await db.commit()
    return {"ok": True, "maestro_id": mid, "nombre": req.nombre}

@app.get("/api/maestros/{mid}")
async def ver_maestro(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT m.*, e.nombre as escuela_nombre FROM maestros m JOIN escuelas e ON m.escuela_id=e.id WHERE m.id=? AND m.activo=1", (mid,))
        row = await cur.fetchone()
    if not row: return {"ok": False, "error": "No encontrado"}
    return {"ok": True, **dict(row)}

@app.get("/api/maestro/{mid}/panel")
async def panel_maestro(mid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM maestros WHERE id=? AND activo=1", (mid,))
        m = await cur.fetchone()
        if not m: raise HTTPException(404, "Maestro no encontrado")
        m = dict(m)
        eid = m["escuela_id"]

        # Teens en la escuela
        cur2 = await db.execute(
            """SELECT mb.id, mb.nombre, mb.familia_id FROM miembros mb
               JOIN escuela_familias ef ON mb.familia_id=ef.familia_id
               WHERE ef.escuela_id=? AND mb.rol IN ('teen','hermano') AND mb.activo=1""", (eid,))
        teens = [dict(r) for r in await cur2.fetchall()]
        total_teens = len(teens)
        teen_ids = [t["id"] for t in teens]

        # Clima — promedio de mood últimos 7 días
        clima = 0.0
        if teen_ids:
            placeholders = ",".join("?" * len(teen_ids))
            corte = time.time() - 7 * 86400
            cur3 = await db.execute(
                f"SELECT AVG(score) FROM mood_history WHERE miembro_id IN ({placeholders}) AND creado>?",
                (*teen_ids, corte))
            val = (await cur3.fetchone())[0]
            clima = round(val or 0, 1)

        # Alertas recientes (sin revelar quién)
        fam_ids = list({t["familia_id"] for t in teens})
        alertas_stats = {"riesgo_alto": 0, "emocional": 0, "bullying": 0, "riesgo_medio": 0, "relaciones": 0}
        if fam_ids:
            corte_al = time.time() - 14 * 86400
            ph = ",".join("?" * len(fam_ids))
            cur4 = await db.execute(
                f"SELECT tipo, COUNT(*) FROM alertas WHERE familia_id IN ({ph}) AND creado>? GROUP BY tipo",
                (*fam_ids, corte_al))
            for row in await cur4.fetchall():
                alertas_stats[row[0]] = (alertas_stats.get(row[0], 0) + row[1])

        # Aptitudes top del grupo
        aptitudes_grupo = []
        if teen_ids:
            ph = ",".join("?" * len(teen_ids))
            cur5 = await db.execute(
                f"SELECT tipo, COUNT(*) as total FROM aptitudes WHERE teen_id IN ({ph}) GROUP BY tipo ORDER BY total DESC LIMIT 6",
                teen_ids)
            aptitudes_grupo = [{"tipo": r[0], "total": r[1]} for r in await cur5.fetchall()]

        # Rezago por materia
        rezago = []
        if teen_ids:
            ph = ",".join("?" * len(teen_ids))
            cur6 = await db.execute(
                f"SELECT materia, COUNT(*) as casos FROM regularizacion WHERE teen_id IN ({ph}) AND estado='activa' GROUP BY materia ORDER BY casos DESC",
                teen_ids)
            rezago = [{"materia": r[0], "casos": r[1]} for r in await cur6.fetchall()]

        # Metas activas (engagement)
        metas_activas = 0
        if teen_ids:
            ph = ",".join("?" * len(teen_ids))
            cur7 = await db.execute(
                f"SELECT COUNT(*) FROM metas WHERE teen_id IN ({ph}) AND estado='activa'", teen_ids)
            metas_activas = (await cur7.fetchone())[0]

    return {
        "ok": True,
        "maestro": m,
        "total_teens": total_teens,
        "clima_score": clima,
        "clima_label": "Sin datos" if clima == 0 else (
            "Muy bien" if clima >= 4.5 else "Bien" if clima >= 3.5 else
            "Regular" if clima >= 2.5 else "Bajo" if clima >= 1.5 else "Crítico"),
        "alertas": alertas_stats,
        "aptitudes_top": aptitudes_grupo,
        "rezago": rezago,
        "metas_activas": metas_activas,
    }

BURNOUT_PATRONES = [
    "ya no puedo","no aguanto más","estoy agotado","me quemé","burnout","no quiero ir",
    "odio mi trabajo","ya no le encuentro sentido","no me respetan","siento que no sirvo",
    "estoy al límite","no duermo","me duele la cabeza de tanto","lloro solo","me rindo",
    "ya no tengo energía","siento que fallo","los alumnos me ignoram","no me hacen caso",
    "la directora me llamó","los papás se quejaron","crisis","colapso","me da ansiedad ir",
    "no sé cómo manejar esto","tengo miedo de equivocarme","me siento solo","nadie me apoya",
]

def detectar_burnout_maestro(texto: str) -> bool:
    t = texto.lower()
    return any(p in t for p in BURNOUT_PATRONES)

class MoodMaestroRequest(BaseModel):
    maestro_id: str
    score: int
    nota: Optional[str] = None

class ChatMaestroRequest(BaseModel):
    maestro_id: str
    mensaje: str

@app.post("/api/maestro/mood")
async def mood_maestro(req: MoodMaestroRequest):
    if not 1 <= req.score <= 5:
        raise HTTPException(400, "score 1-5")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO maestro_mood VALUES (?,?,?,?,?)",
            (str(uuid.uuid4())[:8], req.maestro_id, req.score, req.nota, time.time()))
        await db.commit()
    etiq = {1:"Registrado. Gracias por ser honesto/a.",2:"Ok. Aquí estoy si quieres hablar.",
            3:"Copy. ¿Qué necesitas hoy?",4:"Bien. ¿Qué tienes en mente para el grupo?",5:"Qué bueno. ¿Qué lo hizo diferente?"}
    return {"ok": True, "respuesta": etiq.get(req.score, "Ok.")}

@app.post("/api/maestro/bienestar")
async def bienestar_maestro(req: ChatMaestroRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM maestros WHERE id=? AND activo=1", (req.maestro_id,))
        m = await cur.fetchone()
        if not m: return {"ok": False, "error": "Maestro no encontrado"}
        m = dict(m)

        cur_h = await db.execute(
            "SELECT mensaje, respuesta FROM conversaciones WHERE miembro_id=? AND rol='maestro_bienestar' ORDER BY creado DESC LIMIT 4",
            (req.maestro_id,))
        rows_h = await cur_h.fetchall()
        historial = []
        for h in reversed(rows_h):
            historial += [{"role":"user","content":h[0]},{"role":"assistant","content":h[1]}]
        historial_txt = "; ".join(h[0][:60] for h in rows_h[:2]) if rows_h else "Primera sesión"

        cur_mood = await db.execute(
            "SELECT score, nota FROM maestro_mood WHERE maestro_id=? ORDER BY creado DESC LIMIT 1",
            (req.maestro_id,))
        mood_row = await cur_mood.fetchone()
        etiq_mood = {1:"muy bajo",2:"bajo",3:"regular",4:"bien",5:"muy bien"}
        estado = f"{etiq_mood.get(mood_row[0],str(mood_row[0]))} — {mood_row[1]}" if mood_row and mood_row[1] else (etiq_mood.get(mood_row[0],"sin reporte") if mood_row else "sin reporte")

    if not req.mensaje.strip():
        prompt = PROMPT_MAESTRO_BIENESTAR.format(
            nombre=m["nombre"], estado=estado, historial_txt=historial_txt)
        return {"ok": True, "respuesta": f"Este es tu espacio, {m['nombre']}. ¿Qué te está pesando hoy?"}

    es_burnout = detectar_burnout_maestro(req.mensaje)
    prompt = PROMPT_MAESTRO_BIENESTAR.format(
        nombre=m["nombre"], estado=estado, historial_txt=historial_txt)
    respuesta = await llamar_ia(prompt, req.mensaje, historial)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO conversaciones VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:8], req.maestro_id, m["escuela_id"], "maestro_bienestar",
             req.mensaje, respuesta, time.time()))
        await db.commit()

    return {"ok": True, "respuesta": respuesta, "burnout_detectado": es_burnout}

@app.post("/api/maestro/chat")
async def chat_maestro(req: ChatMaestroRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM maestros WHERE id=? AND activo=1", (req.maestro_id,))
        m = await cur.fetchone()
        if not m: return {"ok": False, "error": "Maestro no encontrado"}
        m = dict(m)
        eid = m["escuela_id"]

        # Historial de conversación del maestro (guardado en tabla propia)
        cur_h = await db.execute(
            "SELECT mensaje, respuesta FROM conversaciones WHERE miembro_id=? ORDER BY creado DESC LIMIT 4",
            (req.maestro_id,))
        rows_h = await cur_h.fetchall()
        historial = []
        for h in reversed(rows_h):
            historial += [{"role":"user","content":h[0]},{"role":"assistant","content":h[1]}]

        # Stats del grupo para el prompt
        teen_ids_cur = await db.execute(
            """SELECT mb.id FROM miembros mb JOIN escuela_familias ef ON mb.familia_id=ef.familia_id
               WHERE ef.escuela_id=? AND mb.rol IN ('teen','hermano') AND mb.activo=1""", (eid,))
        teen_ids = [r[0] for r in await teen_ids_cur.fetchall()]
        total_teens = len(teen_ids)

        clima = 0.0
        if teen_ids:
            ph = ",".join("?" * len(teen_ids))
            corte = time.time() - 7 * 86400
            c = await db.execute(
                f"SELECT AVG(score) FROM mood_history WHERE miembro_id IN ({ph}) AND creado>?",
                (*teen_ids, corte))
            val = (await c.fetchone())[0]
            clima = round(val or 0, 1)

        stats_txt = f"{total_teens} alumnos activos. Clima emocional promedio: {clima}/5."

        fam_ids_cur = await db.execute(
            """SELECT DISTINCT mb.familia_id FROM miembros mb JOIN escuela_familias ef ON mb.familia_id=ef.familia_id
               WHERE ef.escuela_id=?""", (eid,))
        fam_ids = [r[0] for r in await fam_ids_cur.fetchall()]
        alertas_txt = "Sin alertas recientes."
        if fam_ids:
            corte_al = time.time() - 7 * 86400
            ph = ",".join("?" * len(fam_ids))
            c2 = await db.execute(
                f"SELECT tipo, COUNT(*) FROM alertas WHERE familia_id IN ({ph}) AND creado>? GROUP BY tipo ORDER BY COUNT(*) DESC LIMIT 4",
                (*fam_ids, corte_al))
            rows_al = await c2.fetchall()
            if rows_al:
                alertas_txt = " | ".join(f"{r[0]}: {r[1]} casos" for r in rows_al)

    # Estado emocional actual del maestro
    async with aiosqlite.connect(DB_PATH) as db:
        cur_mood = await db.execute(
            "SELECT score, nota FROM maestro_mood WHERE maestro_id=? ORDER BY creado DESC LIMIT 1",
            (req.maestro_id,))
        mood_row = await cur_mood.fetchone()
    etiq_mood = {1:"muy bajo",2:"bajo",3:"regular",4:"bien",5:"muy bien"}
    estado_maestro = f"{etiq_mood.get(mood_row[0],'?')} — {mood_row[1]}" if mood_row and mood_row[1] else (etiq_mood.get(mood_row[0], "sin reporte") if mood_row else "sin reporte")

    prompt = PROMPT_MAESTRO.format(
        nombre=m["nombre"], stats_grupo=stats_txt, alertas_grupo=alertas_txt,
        estado_maestro=estado_maestro)

    if not req.mensaje.strip():
        return {"ok": True, "respuesta": f"¿Cómo estás tú hoy, {m['nombre']}? ¿El maestro — no el grupo."}

    respuesta = await llamar_ia(prompt, req.mensaje, historial)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO conversaciones VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:8], req.maestro_id, eid, "maestro",
             req.mensaje, respuesta, time.time()))
        await db.commit()

    return {"ok": True, "respuesta": respuesta}

@app.get("/maestro", response_class=HTMLResponse)
async def panel_maestro_ui():
    with open(os.path.join(os.path.dirname(__file__), "maestro.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/jorge", response_class=HTMLResponse)
async def jorge_landing():
    with open(os.path.join(os.path.dirname(__file__), "jorge.html"), encoding="utf-8") as f:
        return f.read()

# ── Manuales ──────────────────────────────────────────────────────────────────
_MANUALES_DIR = os.path.join(os.path.dirname(__file__), "manuales")

@app.get("/manuales", response_class=HTMLResponse)
async def manuales_index():
    with open(os.path.join(_MANUALES_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/manuales/{nombre}", response_class=HTMLResponse)
async def manual_page(nombre: str):
    nombre = os.path.basename(nombre)  # prevent path traversal
    path = os.path.join(_MANUALES_DIR, nombre)
    if not os.path.isfile(path):
        raise HTTPException(404, "Documento no encontrado")
    with open(path, encoding="utf-8") as f:
        return f.read()

@app.get("/api/ping-demo")
async def ping_demo():
    """Crea DEMO01 si no existe. Llamar si la app dice 'Código no válido' en DEMO01."""
    await _crear_demo_si_falta()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id FROM familias WHERE codigo_acceso='DEMO01'")
        row = await cur.fetchone()
    return {"ok": bool(row), "demo": "DEMO01", "pin": "1234"}

# ── Admin API ─────────────────────────────────────────────────────────────────
@app.get("/api/admin/stats")
async def admin_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        stats = {}
        for tabla, col in [
            ("familias","id"), ("miembros","id"), ("escuelas","id"),
            ("misiones","id"), ("acuerdos","id"), ("metas","id"),
            ("mood_log","id"), ("maestros","id")
        ]:
            try:
                cur = await db.execute(f"SELECT COUNT(*) as n FROM {tabla}")
                row = await cur.fetchone()
                stats[tabla] = dict(row)["n"]
            except:
                stats[tabla] = 0
        # miembros por rol
        cur = await db.execute("SELECT rol, COUNT(*) as n FROM miembros GROUP BY rol")
        stats["por_rol"] = {r["rol"]: r["n"] for r in await cur.fetchall()}
        # familias recientes
        cur = await db.execute("SELECT nombre, codigo_acceso, creado FROM familias ORDER BY creado DESC LIMIT 10")
        stats["familias_recientes"] = [dict(r) for r in await cur.fetchall()]
        # escuelas recientes
        cur = await db.execute("SELECT id, nombre, tipo FROM escuelas ORDER BY rowid DESC LIMIT 10")
        stats["escuelas_lista"] = [dict(r) for r in await cur.fetchall()]
        # mood promedio
        try:
            cur = await db.execute("SELECT AVG(score) as avg FROM mood_log")
            row = await cur.fetchone()
            stats["mood_promedio"] = round(dict(row)["avg"] or 0, 1)
        except:
            stats["mood_promedio"] = 0
        # mensajes chat
        try:
            cur = await db.execute("SELECT COUNT(*) as n FROM chat_log")
            row = await cur.fetchone()
            stats["chat_mensajes"] = dict(row)["n"]
        except:
            stats["chat_mensajes"] = 0
    return {"ok": True, "stats": stats}

@app.get("/api/admin/familias")
async def admin_familias():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT f.id, f.nombre, f.codigo_acceso, f.creado,
                   COUNT(m.id) as miembros
            FROM familias f
            LEFT JOIN miembros m ON m.familia_id = f.id
            GROUP BY f.id ORDER BY f.creado DESC LIMIT 50
        """)
        rows = [dict(r) for r in await cur.fetchall()]
    return {"ok": True, "familias": rows}

@app.get("/api/admin/escuelas")
async def admin_escuelas():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM escuelas ORDER BY rowid DESC")
        rows = [dict(r) for r in await cur.fetchall()]
    return {"ok": True, "escuelas": rows}

# ── Panel Admin ────────────────────────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
async def panel_admin():
    p = os.path.join(os.path.dirname(__file__), "admin.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

# ── Sembrar escenario demo completo ───────────────────────────────────────────
@app.post("/api/admin/sembrar-demo")
async def sembrar_demo():
    """Siembra datos demo completos: familia, teen, misiones, mood, alertas, escuela."""
    import random
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = time.time()

        # Familia demo (ya existe DEMO01, crear DEMO02 para pruebas adicionales)
        fid2 = "demo-fam-02"
        cur = await db.execute("SELECT id FROM familias WHERE id=?", (fid2,))
        if not await cur.fetchone():
            await db.execute("INSERT OR IGNORE INTO familias VALUES (?,?,?,?)",
                             (fid2, "Familia Hernández Demo", "DEMO02", now))
            pin2 = hashlib.sha256("5678".encode()).hexdigest()
            await db.execute("INSERT OR IGNORE INTO miembros VALUES (?,?,?,?,?,?,0,'{}',1,?)",
                             ("demo-p2", fid2, "Mamá Hernández", "padre", 42, pin2, now))
            await db.execute("INSERT OR IGNORE INTO miembros VALUES (?,?,?,?,?,?,0,'{}',1,?)",
                             ("demo-t2", fid2, "Sofía Hernández", "teen", 15, None, now))

        # Misiones para DEMO01
        misiones_demo = [
            ("Lavar los trastes esta semana", "completada", "demo-padre-01", "demo-teen-01"),
            ("Estudiar Matemáticas 1h sin celular", "pendiente", "demo-padre-01", "demo-teen-01"),
            ("Llamar al abuelo el domingo", "aprobada", "demo-padre-01", "demo-teen-01"),
        ]
        for txt, estado, padre, teen in misiones_demo:
            mid = str(uuid.uuid4())[:8]
            await db.execute(
                "INSERT OR IGNORE INTO misiones VALUES (?,?,?,?,?,?,?)",
                (mid, "demo-fam-01", padre, teen, txt, estado, now - random.randint(0, 604800)))

        # Mood logs para demo-teen-01 (últimos 7 días)
        for i in range(7):
            ts = now - (i * 86400)
            score = random.randint(2, 5)
            await db.execute("INSERT INTO mood_log VALUES (?,?,?,?,?)",
                             (str(uuid.uuid4())[:8], "demo-teen-01", score, None, ts))

        # Acuerdos
        acuerdos_demo = [
            ("Llegar antes de las 10pm los fines de semana", "activo"),
            ("Avisar si cambia el plan durante la tarde", "activo"),
        ]
        for txt, estado in acuerdos_demo:
            aid = str(uuid.uuid4())[:8]
            await db.execute("INSERT OR IGNORE INTO acuerdos VALUES (?,?,?,?,?)",
                             (aid, "demo-fam-01", txt, estado, now - 86400))

        # Alerta de riesgo demo
        await db.execute("INSERT OR IGNORE INTO alertas VALUES (?,?,?,?,?,?,?)",
                         (str(uuid.uuid4())[:8], "demo-fam-01", "demo-teen-01",
                          "riesgo_medio", "Patrón de bajo bienestar detectado esta semana",
                          0, now - 3600))

        # Escuela demo
        cur2 = await db.execute("SELECT id FROM escuelas WHERE id=?", ("escuela-demo-01",))
        if not await cur2.fetchone():
            await db.execute(
                "INSERT OR IGNORE INTO escuelas VALUES (?,?,?,?,?,1,?)",
                ("escuela-demo-01", "Prepa Lázaro Cárdenas Demo", "ESCUELA01",
                 "Tlaquepaque, Jalisco", "Dr. Roberto Pérez", now))
            await db.execute(
                "INSERT OR IGNORE INTO escuela_familias VALUES (?,?)",
                ("escuela-demo-01", "demo-fam-01"))

        # Maestro demo con burnout moderado
        cur3 = await db.execute("SELECT id FROM maestros WHERE id=?", ("maestro-demo-01",))
        if not await cur3.fetchone():
            await db.execute(
                "INSERT OR IGNORE INTO maestros VALUES (?,?,?,?,?)",
                ("maestro-demo-01", "escuela-demo-01", "Prof. Ana García", "Matemáticas", now))
        for i in range(5):
            ts = now - (i * 86400)
            score = random.choice([2, 2, 3, 2, 1])
            await db.execute(
                "INSERT INTO maestro_mood VALUES (?,?,?,?,?)",
                (str(uuid.uuid4())[:8], "maestro-demo-01", score,
                 random.choice(["Muy cansada esta semana", "Los alumnos no participan", None]), ts))

        await db.commit()
    return {"ok": True, "msg": "Escenario demo sembrado: DEMO01/1234, DEMO02/5678, escuela, misiones, mood, alertas, maestro con burnout"}

# ── Panel Escolar ──────────────────────────────────────────────────────────────
@app.get("/escuela", response_class=HTMLResponse)
async def panel_escolar():
    p = os.path.join(os.path.dirname(__file__), "panel_escolar.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

@app.get("/nosotros", response_class=HTMLResponse)
async def pagina_nosotros():
    p = os.path.join(os.path.dirname(__file__), "nosotros.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

@app.get("/privacidad", response_class=HTMLResponse)
async def pagina_privacidad():
    p = os.path.join(os.path.dirname(__file__), "privacidad.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

@app.get("/terminos", response_class=HTMLResponse)
async def pagina_terminos():
    p = os.path.join(os.path.dirname(__file__), "terminos.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("evolucion_server:app", host="0.0.0.0", port=PORT, reload=False)
