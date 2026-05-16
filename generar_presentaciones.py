#!/usr/bin/env python3
"""
Genera 3 presentaciones profesionales con:
- Binaurales reales (Web Audio API — 200Hz/208Hz = 8Hz alpha)
- Voz automatica por slide (Web Speech API es-MX)
- Auto-avance con progreso
- Controles flotantes de reproduccion
Output: C:\evolucion\presentaciones\
"""
import os, re
from pathlib import Path

import sys; sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(r"C:\evolucion\presentaciones")
OUT.mkdir(exist_ok=True)

SRC = Path(r"C:\evolucion\manuales")

# ── Motor binaural + voz ─────────────────────────────────────────────────────
ENGINE = r"""
<!-- ═══ MOTOR AUTOPRESENTACION + BINAURALES ═══ -->
<style>
#ctrl-bar{
  position:fixed;top:1rem;right:1.5rem;z-index:200;
  display:flex;gap:.5rem;align-items:center;
}
.cb{background:rgba(8,8,20,.92);border:1px solid #1a1a35;
  border-radius:99px;padding:.35rem .85rem;font-size:.72rem;font-weight:700;
  color:#8888aa;cursor:pointer;transition:all .2s;letter-spacing:.03em;}
.cb:hover,.cb.on{color:#00e5a0;border-color:rgba(0,229,160,.4);}
.cb.on{background:rgba(0,229,160,.08);}
#prog-bar{
  position:fixed;bottom:0;left:0;height:2px;background:#00e5a0;
  width:0%;transition:width .3s linear;z-index:200;
  box-shadow:0 0 6px rgba(0,229,160,.6);
}
#vol-hint{
  position:fixed;bottom:3.5rem;left:50%;transform:translateX(-50%);
  background:rgba(8,8,20,.95);border:1px solid #1a1a35;
  border-radius:12px;padding:.6rem 1.2rem;font-size:.78rem;color:#8888aa;
  z-index:300;display:none;text-align:center;
}
#slide-timer{font-size:.62rem;color:#4a4a6a;min-width:28px;text-align:center;}
</style>

<div id="ctrl-bar">
  <button class="cb" id="btn-play" title="Autopresentacion">▶ AUTO</button>
  <button class="cb" id="btn-sound" title="Binaurales">♫ ON</button>
  <span id="slide-timer"></span>
</div>
<div id="prog-bar"></div>
<div id="vol-hint">🎧 Usa audífonos para la experiencia binaural completa</div>

<script>
// ── Binaurales ────────────────────────────────────────────────────────────────
let audioCtx = null, gainNode = null, soundOn = false;

function startBinaural() {
  if (audioCtx) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();

  gainNode = audioCtx.createGain();
  gainNode.gain.setValueAtTime(0, audioCtx.currentTime);
  gainNode.gain.linearRampToValueAtTime(0.035, audioCtx.currentTime + 2);

  // Merger para stereo
  const merger = audioCtx.createChannelMerger(2);
  merger.connect(gainNode);
  gainNode.connect(audioCtx.destination);

  // Oído izquierdo: 200 Hz (tono base)
  const oscL = audioCtx.createOscillator();
  oscL.type = 'sine';
  oscL.frequency.value = 200;
  const splitterL = audioCtx.createChannelSplitter(1);
  oscL.connect(merger, 0, 0);

  // Oído derecho: 208 Hz (200 + 8Hz alpha = receptividad, relajacion)
  const oscR = audioCtx.createOscillator();
  oscR.type = 'sine';
  oscR.frequency.value = 208;
  oscR.connect(merger, 0, 1);

  // Ambient pad suave (drone 110Hz)
  const pad = audioCtx.createOscillator();
  pad.type = 'triangle';
  pad.frequency.value = 110;
  const padGain = audioCtx.createGain();
  padGain.gain.value = 0.015;
  pad.connect(padGain);
  padGain.connect(gainNode);

  oscL.start(); oscR.start(); pad.start();
  soundOn = true;
}

function stopBinaural() {
  if (!audioCtx) return;
  gainNode.gain.linearRampToValueAtTime(0, audioCtx.currentTime + 1);
  setTimeout(() => { audioCtx.close(); audioCtx = null; soundOn = false; }, 1100);
}

const btnSound = document.getElementById('btn-sound');
btnSound.onclick = () => {
  if (!soundOn) { startBinaural(); btnSound.textContent = '♫ ON'; btnSound.classList.add('on'); }
  else { stopBinaural(); btnSound.textContent = '♫ OFF'; btnSound.classList.remove('on'); }
};

// ── Autopresentacion + Voz ────────────────────────────────────────────────────
let autoMode = false, autoTimer = null, progTimer = null, progStart = 0, progDur = 0;

const progBar = document.getElementById('prog-bar');
const slideTimer = document.getElementById('slide-timer');
const btnPlay = document.getElementById('btn-play');
const volHint = document.getElementById('vol-hint');

// Narrations por slide — definidas por el deck
const narrations = window.DECK_NARRATIONS || [];
const slideDurations = window.DECK_DURATIONS || [];   // segundos por slide

function speak(text, onEnd) {
  if (!text || !window.speechSynthesis) { onEnd && onEnd(); return; }
  speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.lang = 'es-MX';
  utt.rate = 0.88;
  utt.pitch = 1.0;
  utt.volume = 1.0;
  // Preferir voz femenina o la primera disponible en es-MX
  const voices = speechSynthesis.getVoices();
  const esVoice = voices.find(v => v.lang.startsWith('es') && v.name.includes('Sabina'))
    || voices.find(v => v.lang.startsWith('es') && v.name.includes('Google'))
    || voices.find(v => v.lang.startsWith('es'));
  if (esVoice) utt.voice = esVoice;
  utt.onend = () => { onEnd && onEnd(); };
  speechSynthesis.speak(utt);
}

function startProgress(dur) {
  progBar.style.transition = 'none';
  progBar.style.width = '0%';
  progStart = Date.now();
  progDur = dur * 1000;
  let elapsed = 0;
  clearInterval(progTimer);
  progTimer = setInterval(() => {
    elapsed = Date.now() - progStart;
    const pct = Math.min(100, (elapsed / progDur) * 100);
    progBar.style.transition = '0.1s linear';
    progBar.style.width = pct + '%';
    const rem = Math.max(0, Math.ceil((progDur - elapsed) / 1000));
    slideTimer.textContent = rem > 0 ? rem + 's' : '';
    if (pct >= 100) clearInterval(progTimer);
  }, 100);
}

function autoNext() {
  if (!autoMode) return;
  const idx = cur;
  const narr = narrations[idx] || '';
  const dur = slideDurations[idx] || 12;
  startProgress(dur);
  if (narr) {
    speak(narr, () => {
      if (!autoMode) return;
      autoTimer = setTimeout(() => { if (autoMode) go(cur + 1); setTimeout(autoNext, 400); }, 1800);
    });
  } else {
    autoTimer = setTimeout(() => { if (autoMode) go(cur + 1); setTimeout(autoNext, 400); }, dur * 1000);
  }
}

btnPlay.onclick = () => {
  if (!autoMode) {
    autoMode = true;
    btnPlay.textContent = '⏸ PAUSE';
    btnPlay.classList.add('on');
    // Iniciar binaurales automaticamente
    if (!soundOn) { startBinaural(); btnSound.textContent = '♫ ON'; btnSound.classList.add('on'); }
    // Mostrar hint audífonos
    volHint.style.display = 'block';
    setTimeout(() => { volHint.style.display = 'none'; }, 4000);
    autoNext();
  } else {
    autoMode = false;
    btnPlay.textContent = '▶ AUTO';
    btnPlay.classList.remove('on');
    clearTimeout(autoTimer);
    clearInterval(progTimer);
    speechSynthesis.cancel();
    progBar.style.width = '0%';
    slideTimer.textContent = '';
  }
};

// Parar auto al navegar manualmente
const origGo = go;
window.go = function(n) {
  origGo(n);
  if (autoMode) {
    clearTimeout(autoTimer);
    clearInterval(progTimer);
    speechSynthesis.cancel();
    setTimeout(autoNext, 200);
  }
};
</script>
"""

# ── Narrations ────────────────────────────────────────────────────────────────
NARRATIONS = {
"deck_app": [
  "Evolución. El primer asistente de desarrollo humano adolescente diseñado en México, para familias como la tuya.",
  "¿Cuándo fue la última vez que tu hijo te contó cómo se sentía de verdad? No es que no quieran hablar. Es que el momento no llega y la brecha crece sin que nadie la note.",
  "Evolución es un acompañante que tu hijo elige, y que tú puedes ver. Escucha sin juzgar, te muestra el estado emocional general, y te alerta cuando importa.",
  "Tu hijo necesita un espacio propio para crecer. Tú necesitas saber que está bien. Evolución hace posible las dos cosas al mismo tiempo, sin invadir su privacidad.",
  "Misiones, acuerdos, puntos y niveles. Herramientas familiares que crean motivación real, sin que tú tengas que estar encima.",
  "En menos de cinco minutos, toda la familia está conectada. Sin correo electrónico. Sin instalación. Solo el enlace y un código de seis letras.",
  "¿Reprobó una materia? Ya no es un drama. El asistente detecta el bloqueo real y le explica a tu hijo desde donde está él, a su ritmo, sin presión.",
  "Tu familia puede entrar ahora mismo. Solo ve a Evolución, crea tu espacio familiar y comparte el código con tus hijos. Empieza hoy.",
],
"deck_sep": [
  "Evolución. Una plataforma que ya opera, con familias reales, diseñada desde México para el sistema educativo mexicano.",
  "No existe en México una solución digital que combine tutoría conversacional con inteligencia artificial, perfil psicológico del alumno y seguimiento real del avance académico.",
  "Sin acceder a ningún dato individual, la SEP puede ver tendencias nacionales que hoy no existen en ningún sistema de información educativa.",
  "La plataforma detecta señales de riesgo en tiempo real: ausentismo emocional, deserción inminente, burnout docente. Datos que hoy nadie tiene.",
  "Un piloto de seis meses en tres planteles es suficiente para medir impacto real: retención, regularización y bienestar adolescente con evidencia.",
  "El costo por alumno es menor al de una hora de tutoría presencial. La escala potencial es de trece millones de adolescentes en el sistema.",
  "Solicitamos la oportunidad de presentar la plataforma en operación y definir juntos el primer plantel piloto con respaldo institucional.",
  "Evolución. Hecho en México. Para México.",
],
"deck_inversores": [
  "Evolución es la primera plataforma de desarrollo humano adolescente con inteligencia artificial conversacional, diseñada para el sistema educativo mexicano. Opera hoy. Escala mañana.",
  "Trece millones de adolescentes en el sistema educativo mexicano. Cero herramientas de acompañamiento emocional digital con inteligencia artificial. Ese es el mercado.",
  "La plataforma ya está desarrollada y en producción. Esta inversión es cien por ciento para escalar, no para construir. El riesgo técnico ya está resuelto.",
  "Modelo de ingresos predecible: suscripción mensual por familia, licencia institucional por plantel, y versión canónica premium con acompañamiento especializado.",
  "Año uno: doscientas familias en Guadalajara. Año dos: diez planteles piloto con la SEP. Año tres: presencia nacional y expansión a Latinoamérica.",
  "El equipo fundador combina experiencia técnica en inteligencia artificial, diseño de producto y desarrollo humano adolescente. Ya tenemos clientes reales.",
  "Buscamos un socio estratégico que comprenda el alcance de este proyecto, no solo un cheque. La plataforma opera. El equipo está listo. Lo que necesitamos es escalar.",
  "Esta es la oportunidad de ser parte del proyecto educativo más importante en México en los últimos diez años. La pregunta no es si va a suceder. Es si quieres estar adentro.",
],
}

DURATIONS = {
  "deck_app":       [12, 14, 14, 13, 12, 11, 13, 12],
  "deck_sep":       [10, 15, 13, 13, 13, 12, 13, 10],
  "deck_inversores":[12, 14, 13, 13, 13, 12, 14, 14],
}

# ── Leer e inyectar ───────────────────────────────────────────────────────────
DECKS = [
  ("deck_familias.html", "deck_app",       "Evolución — Para Familias"),
  ("deck_sep.html",      "deck_sep",       "Evolución — Para la SEP"),
  ("deck_inversores.html","deck_inversores","Evolución — Para Inversores"),
]

for src_name, narr_key, title in DECKS:
  src_path = SRC / src_name
  if not src_path.exists():
    print(f"FALTA: {src_name}")
    continue
  html = src_path.read_text(encoding="utf-8")

  # Patch title
  html = re.sub(r'<title>.*?</title>', f'<title>{title}</title>', html)

  # Inyectar narrations como JS global antes de </body>
  narrs  = NARRATIONS[narr_key]
  durs   = DURATIONS[narr_key]
  narr_js = f"""
<script>
window.DECK_NARRATIONS = {narrs};
window.DECK_DURATIONS  = {durs};
</script>
"""

  # Inyectar antes de </body>
  inject = narr_js + ENGINE
  html = html.replace('</body>', inject + '\n</body>')

  out_name = narr_key + ".html"
  out_path = OUT / out_name
  out_path.write_text(html, encoding="utf-8")
  print(f"OK  {out_name}")

print(f"\nPresentaciones en: {OUT}")
