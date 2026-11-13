"""
Motor de Traducción Conversacional Bidireccional y Abecedario LSC — SignBridge Extended v4.0.

Gestiona:
1. Catálogo extendido de +45 señas conversacionales bimanuales y unimanuales en 7 categorías (LSC).
2. Integración completa del Abecedario en Lengua de Señas Colombiana (27 letras: A-Z + Ñ).
3. Sub-modos de reconocimiento: CONVERSATION (Palabras/Frases), ALPHABET_LSC (Deletreo) e HYBRID.
4. Conjugador gramatical automático de glosas LSC + deletreo a oraciones fluidas en español.
5. Traductor Inverso (Texto / Frases / Voz -> Secuencia Animada en Modelo 3D de Manos Unimanual/Bimanual).
6. Historial conversacional bidireccional (Persona Sorda [Señas/TTS] <-> Oyente [Micrófono/STT]).
"""

from __future__ import annotations
import math
import re
import time
import unicodedata
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from backend.lsc_alphabet import (
    LSC_ALPHABET_CATALOG,
    CHAR_TO_LSC_ID,
    get_lsc_letter_pose,
    classify_lsc_alphabet,
)


CONVERSATIONAL_SIGNS_CATALOG: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # 1. PRONOMBRES Y SUJETOS (6 Señas)
    # =========================================================================
    "S_YO": {
        "id": "S_YO",
        "label": "Yo",
        "emoji": "🙋",
        "category": "Pronombres",
        "bimanual": False,
        "default_phrase": "Yo",
        "description": "Dedo índice o mano apuntando hacia el centro del pecho propio.",
        "color": "#38BDF8",
    },
    "S_TU": {
        "id": "S_TU",
        "label": "Tú / Usted",
        "emoji": "👉",
        "category": "Pronombres",
        "bimanual": False,
        "default_phrase": "Tú",
        "description": "Dedo índice apuntando directamente hacia el interlocutor.",
        "color": "#38BDF8",
    },
    "S_EL": {
        "id": "S_EL",
        "label": "Él / Ella",
        "emoji": "👈",
        "category": "Pronombres",
        "bimanual": False,
        "default_phrase": "Él / Ella",
        "description": "Dedo índice señalando hacia un costado en tercera persona.",
        "color": "#38BDF8",
    },
    "S_NOSOTROS": {
        "id": "S_NOSOTROS",
        "label": "Nosotros",
        "emoji": "👥",
        "category": "Pronombres",
        "bimanual": False,
        "default_phrase": "Nosotros",
        "description": "Mano en arco o dos dedos describiendo un semicírculo frente al pecho.",
        "color": "#38BDF8",
    },
    "S_AMIGO": {
        "id": "S_AMIGO",
        "label": "Amigo / Compañero",
        "emoji": "🧑‍🤝‍🧑",
        "category": "Pronombres",
        "bimanual": True,
        "default_phrase": "Hola amigo, qué gusto verte.",
        "description": "Ambas manos uniéndose cálidamente o índices entrelazándose.",
        "color": "#06B6D4",
    },
    "S_PROFESOR": {
        "id": "S_PROFESOR",
        "label": "Profesor / Docente",
        "emoji": "👨‍🏫",
        "category": "Pronombres",
        "bimanual": False,
        "default_phrase": "Profesor",
        "description": "Mano en configuración de enseñanza proyectándose desde la altura de la sien.",
        "color": "#06B6D4",
    },

    # =========================================================================
    # 2. SALUDOS Y CORTESÍA (9 Señas)
    # =========================================================================
    "S_HOLA": {
        "id": "S_HOLA",
        "label": "Hola",
        "emoji": "👋",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Hola, un gusto saludarte.",
        "description": "Mano abierta con palma al frente en saludo cordial.",
        "color": "#00F0FF",
    },
    "S_BUENOS_DIAS": {
        "id": "S_BUENOS_DIAS",
        "label": "Buenos días",
        "emoji": "🌅",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Buenos días, ¿cómo amaneces?",
        "description": "Mano abierta partiendo del pecho y abriéndose como el sol naciente sobre el brazo base.",
        "color": "#38BDF8",
    },
    "S_BUENAS_TARDES": {
        "id": "S_BUENAS_TARDES",
        "label": "Buenas tardes",
        "emoji": "🌇",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Buenas tardes para todos.",
        "description": "Mano dominante deslizándose suavemente sobre el antebrazo opuesto.",
        "color": "#F59E0B",
    },
    "S_BUENAS_NOCHES": {
        "id": "S_BUENAS_NOCHES",
        "label": "Buenas noches",
        "emoji": "🌙",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Buenas noches, que descanses.",
        "description": "Mano dominante descendiendo en arco cerrándose frente al brazo base.",
        "color": "#6366F1",
    },
    "S_GRACIAS": {
        "id": "S_GRACIAS",
        "label": "Gracias",
        "emoji": "🙏",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Muchas gracias por tu ayuda.",
        "description": "Yemas de la mano abierta desde el mentón proyectándose hacia adelante.",
        "color": "#10B981",
    },
    "S_POR_FAVOR": {
        "id": "S_POR_FAVOR",
        "label": "Por favor",
        "emoji": "🤲",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Por favor, te lo agradezco.",
        "description": "Ambas palmas abiertas juntas frente al pecho en solicitud respetuosa.",
        "color": "#F59E0B",
    },
    "S_MUCHO_GUSTO": {
        "id": "S_MUCHO_GUSTO",
        "label": "Mucho gusto",
        "emoji": "🤝",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Mucho gusto en conocerte y hablar contigo.",
        "description": "Ambas manos abiertas convergiendo y tocándose en el centro del pecho.",
        "color": "#06B6D4",
    },
    "S_DISCULPA": {
        "id": "S_DISCULPA",
        "label": "Disculpa / Perdón",
        "emoji": "🙇",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Disculpa por favor / Con permiso.",
        "description": "Mano en Y o puño suave sobre el pecho/mentón en gesto de excusa.",
        "color": "#F97316",
    },
    "S_ADIOS": {
        "id": "S_ADIOS",
        "label": "Adiós",
        "emoji": "👋",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Hasta luego, que tengas un excelente día.",
        "description": "Mano dominante abierta oscilando lateralmente en despedida.",
        "color": "#6366F1",
    },

    # =========================================================================
    # 3. VERBOS Y ACCIONES COTIDIANAS (10 Señas)
    # =========================================================================
    "S_QUERER": {
        "id": "S_QUERER",
        "label": "Querer / Desear",
        "emoji": "💙",
        "category": "Verbos",
        "bimanual": True,
        "default_phrase": "Yo quiero esto, por favor.",
        "description": "Ambas manos semi-curvadas atrayendo hacia el pecho.",
        "color": "#EC4899",
    },
    "S_NECESITAR": {
        "id": "S_NECESITAR",
        "label": "Necesitar",
        "emoji": "📌",
        "category": "Verbos",
        "bimanual": False,
        "default_phrase": "Necesito tu apoyo en este momento.",
        "description": "Dedo índice en gancho o con pulgar moviéndose con firmeza hacia abajo.",
        "color": "#F43F5E",
    },
    "S_COMER": {
        "id": "S_COMER",
        "label": "Comer",
        "emoji": "🍽️",
        "category": "Verbos",
        "bimanual": False,
        "default_phrase": "Tengo hambre, quiero comer.",
        "description": "Yemas de los 5 dedos unidas (capullo Q) llevándose hacia la boca.",
        "color": "#10B981",
    },
    "S_AGUA": {
        "id": "S_AGUA",
        "label": "Beber / Agua",
        "emoji": "💧",
        "category": "Verbos",
        "bimanual": False,
        "default_phrase": "Por favor regálame un vaso de agua.",
        "description": "Dedo índice y pulgar (o letra L) acercándose al mentón/boca.",
        "color": "#0EA5E9",
    },
    "S_ESTUDIAR": {
        "id": "S_ESTUDIAR",
        "label": "Estudiar / Aprender",
        "emoji": "📚",
        "category": "Verbos",
        "bimanual": True,
        "default_phrase": "Estoy estudiando Lengua de Señas Colombiana.",
        "description": "Mano no dominante abierta como un cuaderno y mano dominante sobre ella.",
        "color": "#8B5CF6",
    },
    "S_TRABAJAR": {
        "id": "S_TRABAJAR",
        "label": "Trabajar",
        "emoji": "🛠️",
        "category": "Verbos",
        "bimanual": True,
        "default_phrase": "Estoy trabajando en el proyecto.",
        "description": "Ambos puños cerrados tocándose rítmicamente por las muñecas.",
        "color": "#F59E0B",
    },
    "S_HABLAR": {
        "id": "S_HABLAR",
        "label": "Hablar / Conversar",
        "emoji": "🗣️",
        "category": "Verbos",
        "bimanual": True,
        "default_phrase": "Quiero conversar contigo en lengua de señas.",
        "description": "Dedos índices o manos alternando movimiento frente al pecho.",
        "color": "#00F0FF",
    },
    "S_IR": {
        "id": "S_IR",
        "label": "Ir / Vamos",
        "emoji": "🚶",
        "category": "Verbos",
        "bimanual": False,
        "default_phrase": "Voy hacia allá ahora mismo.",
        "description": "Dedo índice desplazándose hacia adelante/arriba con decisión.",
        "color": "#10B981",
    },
    "S_ENTENDIDO": {
        "id": "S_ENTENDIDO",
        "label": "Entendido",
        "emoji": "💡",
        "category": "Verbos",
        "bimanual": False,
        "default_phrase": "He comprendido el mensaje con claridad.",
        "description": "Puño cerrado firme o toque afirmativo cerca de la sien.",
        "color": "#3B82F6",
    },
    "S_NO_ENTIENDO": {
        "id": "S_NO_ENTIENDO",
        "label": "No entiendo",
        "emoji": "🤔",
        "category": "Verbos",
        "bimanual": False,
        "default_phrase": "No entiendo bien, ¿puedes explicarme de nuevo?",
        "description": "Índice en la sien oscilando en negación.",
        "color": "#F43F5E",
    },

    # =========================================================================
    # 4. PREGUNTAS E INTERROGATIVOS (7 Señas)
    # =========================================================================
    "S_COMO_ESTAS": {
        "id": "S_COMO_ESTAS",
        "label": "¿Cómo estás?",
        "emoji": "❓",
        "category": "Preguntas",
        "bimanual": True,
        "default_phrase": "¿Cómo te encuentras el día de hoy?",
        "description": "Ambas manos sobre el pecho abriéndose hacia los costados con expresión interrogativa.",
        "color": "#8B5CF6",
    },
    "S_QUE": {
        "id": "S_QUE",
        "label": "¿Qué?",
        "emoji": "🧐",
        "category": "Preguntas",
        "bimanual": True,
        "default_phrase": "¿Qué necesitas o qué sucede?",
        "description": "Ambas palmas abiertas hacia arriba oscilando suavemente.",
        "color": "#A855F7",
    },
    "S_DONDE": {
        "id": "S_DONDE",
        "label": "¿Dónde?",
        "emoji": "📍",
        "category": "Preguntas",
        "bimanual": True,
        "default_phrase": "¿Dónde se encuentra ese lugar?",
        "description": "Dedos índices de ambas manos señalando en búsqueda espacial.",
        "color": "#EC4899",
    },
    "S_CUANDO": {
        "id": "S_CUANDO",
        "label": "¿Cuándo?",
        "emoji": "🕒",
        "category": "Preguntas",
        "bimanual": False,
        "default_phrase": "¿Cuándo nos vemos?",
        "description": "Dedo índice girando o señalando la muñeca como un reloj.",
        "color": "#F59E0B",
    },
    "S_QUIEN": {
        "id": "S_QUIEN",
        "label": "¿Quién?",
        "emoji": "👤",
        "category": "Preguntas",
        "bimanual": False,
        "default_phrase": "¿Quién es esa persona?",
        "description": "Dedo índice dibujando un pequeño contorno o apuntando en pregunta.",
        "color": "#06B6D4",
    },
    "S_POR_QUE": {
        "id": "S_POR_QUE",
        "label": "¿Por qué?",
        "emoji": "❔",
        "category": "Preguntas",
        "bimanual": False,
        "default_phrase": "¿Por qué ocurre esto?",
        "description": "Mano tocando la frente y abriéndose en interrogación.",
        "color": "#8B5CF6",
    },
    "S_CUANTO": {
        "id": "S_CUANTO",
        "label": "¿Cuánto?",
        "emoji": "🔢",
        "category": "Preguntas",
        "bimanual": False,
        "default_phrase": "¿Cuánto cuesta o cuántos son?",
        "description": "Dedos abriéndose desde el puño en gesto de conteo.",
        "color": "#10B981",
    },

    # =========================================================================
    # 5. RESPUESTAS Y ESTADOS DE ÁNIMO (8 Señas)
    # =========================================================================
    "S_SI": {
        "id": "S_SI",
        "label": "Sí / De acuerdo",
        "emoji": "✅",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "Sí, estoy totalmente de acuerdo.",
        "description": "Dedo índice vertical asintiendo hacia adelante.",
        "color": "#10B981",
    },
    "S_NO": {
        "id": "S_NO",
        "label": "No / Negación",
        "emoji": "❌",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "No, no estoy de acuerdo.",
        "description": "Dedo índice y pulgar en L o índice oscilando lateralmente en negación.",
        "color": "#F43F5E",
    },
    "S_BIEN": {
        "id": "S_BIEN",
        "label": "Bien / Excelente",
        "emoji": "👍",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "Me encuentro muy bien, todo excelente.",
        "description": "Pulgar extendido hacia arriba con firmeza.",
        "color": "#00F0FF",
    },
    "S_MAL": {
        "id": "S_MAL",
        "label": "Mal",
        "emoji": "👎",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "No me siento bien / Hay un problema.",
        "description": "Pulgar apuntando hacia abajo.",
        "color": "#F59E0B",
    },
    "S_REGULAR": {
        "id": "S_REGULAR",
        "label": "Más o menos",
        "emoji": "⚖️",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "Más o menos, ahí vamos.",
        "description": "Mano abierta horizontal basculando de lado a lado.",
        "color": "#EAB308",
    },
    "S_FELIZ": {
        "id": "S_FELIZ",
        "label": "Feliz / Contento",
        "emoji": "😊",
        "category": "Respuestas",
        "bimanual": True,
        "default_phrase": "Estoy muy feliz y agradecido.",
        "description": "Ambas manos ascendiendo alegremente frente al pecho.",
        "color": "#10B981",
    },
    "S_CANSADO": {
        "id": "S_CANSADO",
        "label": "Cansado",
        "emoji": "😮‍💨",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "Estoy un poco cansado hoy.",
        "description": "Mano descendiendo pesadamente frente al torso.",
        "color": "#94A3B8",
    },
    "S_OCUPADO": {
        "id": "S_OCUPADO",
        "label": "Ocupado",
        "emoji": "⏳",
        "category": "Respuestas",
        "bimanual": True,
        "default_phrase": "En este momento estoy ocupado.",
        "description": "Manos en actividad rápida sobre el espacio frontal.",
        "color": "#F97316",
    },

    # =========================================================================
    # 6. TIEMPO Y LUGARES COTIDIANOS (4 Señas)
    # =========================================================================
    "S_HOY": {
        "id": "S_HOY",
        "label": "Hoy / Ahora",
        "emoji": "📅",
        "category": "Tiempo y Lugar",
        "bimanual": False,
        "default_phrase": "Hoy mismo",
        "description": "Mano indicando el espacio presente inmediato hacia abajo.",
        "color": "#38BDF8",
    },
    "S_MANANA": {
        "id": "S_MANANA",
        "label": "Mañana",
        "emoji": "🌤️",
        "category": "Tiempo y Lugar",
        "bimanual": False,
        "default_phrase": "Nos vemos mañana.",
        "description": "Dedo pulgar o índice proyectándose en arco hacia adelante (futuro cercano).",
        "color": "#38BDF8",
    },
    "S_CASA": {
        "id": "S_CASA",
        "label": "Casa / Hogar",
        "emoji": "🏠",
        "category": "Tiempo y Lugar",
        "bimanual": True,
        "default_phrase": "Voy para mi casa.",
        "description": "Ambas manos abiertas inclinadas uniendo las yemas arriba formando el techo de una casa.",
        "color": "#10B981",
    },
    "S_UNIVERSIDAD": {
        "id": "S_UNIVERSIDAD",
        "label": "Universidad / Clase",
        "emoji": "🎓",
        "category": "Tiempo y Lugar",
        "bimanual": False,
        "default_phrase": "Estoy en la universidad presentando el proyecto.",
        "description": "Mano en configuración U (índice y meñique en LSC) realizando un pequeño círculo.",
        "color": "#8B5CF6",
    },

    # =========================================================================
    # 7. EMERGENCIA Y CONTROL DE DIÁLOGO (6 Señas)
    # =========================================================================
    "S_AYUDA": {
        "id": "S_AYUDA",
        "label": "Ayuda / SOS",
        "emoji": "🆘",
        "category": "Emergencia",
        "bimanual": True,
        "default_phrase": "Necesito ayuda o asistencia prioritaria, por favor.",
        "description": "Puño dominante sobre palma no dominante horizontal, o señal de 3 dedos / Shaka.",
        "color": "#EF4444",
    },
    "S_MEDICO": {
        "id": "S_MEDICO",
        "label": "Médico / Dolor",
        "emoji": "🩺",
        "category": "Emergencia",
        "bimanual": True,
        "default_phrase": "Necesito atención médica o siento dolor.",
        "description": "Dedos índice y medio tocando el pulso en la muñeca de la otra mano.",
        "color": "#F43F5E",
    },
    "S_ESPERA": {
        "id": "S_ESPERA",
        "label": "Espera un momento",
        "emoji": "✋",
        "category": "Control",
        "bimanual": True,
        "default_phrase": "Por favor espera un momento mientras respondo.",
        "description": "Ambas palmas abiertas mirando hacia el frente empujando el aire.",
        "color": "#EAB308",
    },
    "S_DESPACIO": {
        "id": "S_DESPACIO",
        "label": "Más despacio",
        "emoji": "🐢",
        "category": "Control",
        "bimanual": True,
        "default_phrase": "Por favor señálame o háblame un poco más despacio.",
        "description": "Ambas palmas abiertas horizontales descendiendo con calma.",
        "color": "#14B8A6",
    },
    "S_REPETIR": {
        "id": "S_REPETIR",
        "label": "Repetir",
        "emoji": "🔄",
        "category": "Control",
        "bimanual": False,
        "default_phrase": "¿Puedes repetir eso por favor?",
        "description": "Mano abierta descendiendo suavemente para pedir repetición.",
        "color": "#06B6D4",
    },
    "S_CONTINUAR": {
        "id": "S_CONTINUAR",
        "label": "Continuar",
        "emoji": "▶️",
        "category": "Control",
        "bimanual": False,
        "default_phrase": "Adelante, podemos continuar con la conversación.",
        "description": "Dedos índice y medio extendidos (seña de paz / continuar).",
        "color": "#10B981",
    },
}

# Conjunto canónico de señas conversacionales dinámicas (que involucran cinemática activa)
DYNAMIC_CONVERSATIONAL_SIGNS = {
    "S_BUENOS_DIAS", "S_BUENAS_TARDES", "S_BUENAS_NOCHES", "S_GRACIAS", "S_MUCHO_GUSTO",
    "S_ADIOS", "S_QUERER", "S_NECESITAR", "S_COMER", "S_TRABAJAR", "S_HABLAR",
    "S_IR", "S_NO_ENTIENDO", "S_COMO_ESTAS", "S_QUE", "S_DONDE", "S_CUANDO",
    "S_QUIEN", "S_POR_QUE", "S_CUANTO", "S_SI", "S_NO", "S_REGULAR", "S_FELIZ",
    "S_CANSADO", "S_OCUPADO", "S_MANANA", "S_UNIVERSIDAD", "S_DESPACIO", "S_REPETIR",
}

# Normalizar alias de metadatos para compatibilidad total con HUD, API REST y Estabilizador Dinámico
for _sid, _smeta in CONVERSATIONAL_SIGNS_CATALOG.items():
    _smeta["word"] = _smeta["label"]
    _smeta["phrase"] = _smeta["default_phrase"]
    _smeta["hands"] = 2 if _smeta.get("bimanual") else 1
    if "is_dynamic" not in _smeta:
        _smeta["is_dynamic"] = (_sid in DYNAMIC_CONVERSATIONAL_SIGNS)


# Diccionario léxico Español -> sign_id para traducir frases habladas/escritas al Modelo 3D de Manos
SPANISH_WORD_TO_SIGN_ID: Dict[str, str] = {
    # Pronombres y personas
    "yo": "S_YO", "mi": "S_YO", "mio": "S_YO", "conmigo": "S_YO",
    "tu": "S_TU", "usted": "S_TU", "ustedes": "S_TU", "tuyo": "S_TU", "contigo": "S_TU",
    "el": "S_EL", "ella": "S_EL", "ellos": "S_EL", "ellas": "S_EL",
    "nosotros": "S_NOSOTROS", "nosotras": "S_NOSOTROS", "nuestro": "S_NOSOTROS",
    "amigo": "S_AMIGO", "amiga": "S_AMIGO", "amigos": "S_AMIGO", "companero": "S_AMIGO", "companera": "S_AMIGO",
    "profesor": "S_PROFESOR", "profesora": "S_PROFESOR", "profe": "S_PROFESOR", "docente": "S_PROFESOR", "maestro": "S_PROFESOR",
    # Saludos y cortesía
    "hola": "S_HOLA", "saludos": "S_HOLA", "buenas": "S_HOLA",
    "gracias": "S_GRACIAS", "agradezco": "S_GRACIAS", "agradecido": "S_GRACIAS",
    "favor": "S_POR_FAVOR", "porfavor": "S_POR_FAVOR",
    "gusto": "S_MUCHO_GUSTO", "encantado": "S_MUCHO_GUSTO", "placer": "S_MUCHO_GUSTO",
    "disculpa": "S_DISCULPA", "perdon": "S_DISCULPA", "perdona": "S_DISCULPA", "permiso": "S_DISCULPA", "siento": "S_DISCULPA",
    "adios": "S_ADIOS", "chao": "S_ADIOS", "luego": "S_ADIOS", "despido": "S_ADIOS",
    # Verbos
    "quiero": "S_QUERER", "querer": "S_QUERER", "quieres": "S_QUERER", "quiere": "S_QUERER", "queremos": "S_QUERER", "deseo": "S_QUERER",
    "necesito": "S_NECESITAR", "necesitar": "S_NECESITAR", "necesitas": "S_NECESITAR", "necesitamos": "S_NECESITAR", "urge": "S_NECESITAR",
    "comer": "S_COMER", "como": "S_COMER", "comida": "S_COMER", "hambre": "S_COMER", "almorzar": "S_COMER", "cenar": "S_COMER",
    "agua": "S_AGUA", "beber": "S_AGUA", "tomar": "S_AGUA", "sed": "S_AGUA", "vaso": "S_AGUA",
    "estudiar": "S_ESTUDIAR", "estudio": "S_ESTUDIAR", "estudias": "S_ESTUDIAR", "aprender": "S_ESTUDIAR", "aprendo": "S_ESTUDIAR", "leer": "S_ESTUDIAR",
    "trabajar": "S_TRABAJAR", "trabajo": "S_TRABAJAR", "trabajas": "S_TRABAJAR", "laborar": "S_TRABAJAR",
    "hablar": "S_HABLAR", "hablo": "S_HABLAR", "conversar": "S_HABLAR", "comunicar": "S_HABLAR", "decir": "S_HABLAR", "senas": "S_HABLAR",
    "ir": "S_IR", "voy": "S_IR", "vas": "S_IR", "vamos": "S_IR", "caminar": "S_IR",
    "entiendo": "S_ENTENDIDO", "entendido": "S_ENTENDIDO", "entender": "S_ENTENDIDO", "comprendo": "S_ENTENDIDO", "claro": "S_ENTENDIDO",
    # Preguntas
    "que": "S_QUE", "cual": "S_QUE",
    "donde": "S_DONDE", "adonde": "S_DONDE", "lugar": "S_DONDE",
    "cuando": "S_CUANDO", "hora": "S_CUANDO",
    "quien": "S_QUIEN", "quienes": "S_QUIEN",
    "porque": "S_POR_QUE",
    "cuanto": "S_CUANTO", "cuantos": "S_CUANTO", "precio": "S_CUANTO",
    # Respuestas y estados
    "si": "S_SI", "afirmativo": "S_SI", "acepto": "S_SI", "correcto": "S_SI",
    "no": "S_NO", "nunca": "S_NO", "negativo": "S_NO", "jamas": "S_NO",
    "bien": "S_BIEN", "excelente": "S_BIEN", "genial": "S_BIEN", "perfecto": "S_BIEN", "bueno": "S_BIEN", "ok": "S_BIEN",
    "mal": "S_MAL", "malo": "S_MAL", "peor": "S_MAL",
    "regular": "S_REGULAR", "masomenos": "S_REGULAR",
    "feliz": "S_FELIZ", "contento": "S_FELIZ", "alegre": "S_FELIZ", "alegria": "S_FELIZ",
    "cansado": "S_CANSADO", "cansada": "S_CANSADO", "agotado": "S_CANSADO", "sueno": "S_CANSADO",
    "ocupado": "S_OCUPADO", "ocupada": "S_OCUPADO",
    # Tiempo y lugares
    "hoy": "S_HOY", "ahora": "S_HOY", "actualmente": "S_HOY", "ya": "S_HOY",
    "manana": "S_MANANA", "futuro": "S_MANANA", "despues": "S_MANANA",
    "casa": "S_CASA", "hogar": "S_CASA", "vivienda": "S_CASA",
    "universidad": "S_UNIVERSIDAD", "clase": "S_UNIVERSIDAD", "colegio": "S_UNIVERSIDAD", "escuela": "S_UNIVERSIDAD", "proyecto": "S_UNIVERSIDAD",
    # Emergencia y control
    "ayuda": "S_AYUDA", "ayudame": "S_AYUDA", "auxilio": "S_AYUDA", "socorro": "S_AYUDA", "sos": "S_AYUDA", "emergencia": "S_AYUDA",
    "medico": "S_MEDICO", "doctor": "S_MEDICO", "dolor": "S_MEDICO", "duele": "S_MEDICO", "enfermo": "S_MEDICO", "hospital": "S_MEDICO", "salud": "S_MEDICO",
    "espera": "S_ESPERA", "esperar": "S_ESPERA", "momento": "S_ESPERA", "pausa": "S_ESPERA", "alto": "S_ESPERA", "detente": "S_ESPERA",
    "despacio": "S_DESPACIO", "lento": "S_DESPACIO", "calma": "S_DESPACIO",
    "repite": "S_REPETIR", "repetir": "S_REPETIR", "otra": "S_REPETIR", "nuevamente": "S_REPETIR",
    "continuar": "S_CONTINUAR", "continua": "S_CONTINUAR", "sigue": "S_CONTINUAR", "adelante": "S_CONTINUAR",
}

# Frases compuestas de múltiples palabras que mapean a una sola seña en LSC
SPANISH_MULTIWORD_PHRASES: List[Tuple[str, str]] = [
    ("como estas", "S_COMO_ESTAS"),
    ("como te va", "S_COMO_ESTAS"),
    ("como te encuentras", "S_COMO_ESTAS"),
    ("que tal", "S_COMO_ESTAS"),
    ("buenos dias", "S_BUENOS_DIAS"),
    ("buen dia", "S_BUENOS_DIAS"),
    ("buenas tardes", "S_BUENAS_TARDES"),
    ("buenas noches", "S_BUENAS_NOCHES"),
    ("por favor", "S_POR_FAVOR"),
    ("mucho gusto", "S_MUCHO_GUSTO"),
    ("no entiendo", "S_NO_ENTIENDO"),
    ("no comprendo", "S_NO_ENTIENDO"),
    ("mas despacio", "S_DESPACIO"),
    ("mas o menos", "S_REGULAR"),
    ("por que", "S_POR_QUE"),
    ("hasta luego", "S_ADIOS"),
    ("muchas gracias", "S_GRACIAS"),
    ("de acuerdo", "S_SI"),
]

# Conectores gramaticales en español que no requieren deletreo manual en LSC
SPANISH_STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "los", "se", "del", "las", "un", "por",
    "con", "una", "su", "para", "es", "al", "lo", "le", "mas", "o", "pero",
    "sus", "ha", "me", "sin", "sobre", "este", "tambien", "era", "muy", "son",
    "estoy", "estas", "esta", "estamos", "estan", "soy", "eres", "somos", "te",
}


def _strip_accents_keep_ntilde(text: str) -> str:
    """Elimina tildes de vocales conservando la letra Ñ intacta."""
    placeholder = "__NTILDE__"
    s = text.replace("ñ", placeholder).replace("Ñ", placeholder.upper())
    s_norm = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return s_norm.replace(placeholder.lower(), "ñ").replace(placeholder.upper(), "Ñ")


def get_sign_3d_poses(
    sign_id: str,
    t_phase: float = 0.0
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Retorna (primary_pose_21x3, secondary_pose_21x3_or_None) para animar el Modelo 3D de Manos
    tanto para letras del Abecedario LSC (L_A..L_Z, L_NTILDE) como para las 46 señas
    conversacionales (unimanuales y bimanuales).
    """
    sid = sign_id.upper().strip()

    # 1. Si es una letra del Abecedario LSC
    if sid in LSC_ALPHABET_CATALOG:
        return get_lsc_letter_pose(sid, t_phase=t_phase), None

    # Helper para clonar y reflejar una mano derecha en mano izquierda (secundaria)
    def make_left_mirror(right_pose: np.ndarray, offset_x: float = -0.26, offset_y: float = 0.0) -> np.ndarray:
        left = right_pose.copy()
        # Reflejar respecto al centro de la propia mano
        cx = float(left[0, 0])
        left[:, 0] = cx - (left[:, 0] - cx) + offset_x
        left[:, 1] = left[:, 1] + offset_y
        return np.clip(left, 0.04, 0.96)

    wave_x = math.sin(t_phase * math.pi * 2.0) * 0.045 if t_phase > 0 else 0.0
    wave_y = math.sin(t_phase * math.pi * 2.0) * 0.040 if t_phase > 0 else 0.0

    # 2. Señas Conversacionales Bimanuales
    if sid == "S_POR_FAVOR":
        # Ambas palmas abiertas unidas en el centro del pecho
        r_pose = get_lsc_letter_pose("L_B", 0.0)
        r_pose[:, 0] += 0.04
        l_pose = make_left_mirror(r_pose, offset_x=-0.08, offset_y=wave_y * 0.4)
        return r_pose, l_pose

    if sid == "S_AYUDA":
        # Mano derecha en puño con pulgar arriba (L_A) descansando sobre palma izquierda plana
        r_pose = get_lsc_letter_pose("L_A", 0.0)
        r_pose[:, 0] += 0.02
        r_pose[:, 1] -= 0.05 + abs(wave_y) * 0.5
        l_pose = get_lsc_letter_pose("L_G", 0.0)
        l_pose[:, 0] = 1.0 - l_pose[:, 0] - 0.05
        l_pose[:, 1] += 0.05 - abs(wave_y) * 0.5
        return r_pose, l_pose

    if sid in ("S_COMO_ESTAS", "S_QUE", "S_FELIZ", "S_OCUPADO"):
        # Ambas manos abiertas separándose / oscilando
        r_pose = get_lsc_letter_pose("L_B", 0.0)
        div = math.sin(t_phase * math.pi) * 0.06 if t_phase > 0 else 0.03
        r_pose[:, 0] += 0.12 + div
        l_pose = make_left_mirror(get_lsc_letter_pose("L_B", 0.0), offset_x=-0.24 - div)
        return r_pose, l_pose

    if sid == "S_CASA":
        # Ambas manos inclinadas formando un techo en triángulo ^
        r_pose = get_lsc_letter_pose("L_B", 0.0)
        r_pose[:, 0] += 0.07
        # Inclinar puntas hacia el centro (x=0.50)
        for idx in (8, 12, 16, 20):
            r_pose[idx, 0] -= 0.06
        l_pose = make_left_mirror(r_pose, offset_x=-0.14)
        return r_pose, l_pose

    if sid == "S_TRABAJAR":
        # Ambos puños golpeándose suavemente
        r_pose = get_lsc_letter_pose("L_A", 0.0)
        r_pose[:, 0] += 0.06
        r_pose[:, 1] += wave_y * 0.6
        l_pose = make_left_mirror(get_lsc_letter_pose("L_A", 0.0), offset_x=-0.14, offset_y=-wave_y * 0.6)
        return r_pose, l_pose

    if sid in ("S_ESTUDIAR", "S_BUENOS_DIAS", "S_BUENAS_TARDES", "S_BUENAS_NOCHES"):
        # Mano base y mano dominante activa encima
        r_pose = get_lsc_letter_pose("L_B", 0.0)
        r_pose[:, 0] += 0.05 + wave_x * 0.5
        r_pose[:, 1] -= 0.04
        l_pose = make_left_mirror(get_lsc_letter_pose("L_B", 0.0), offset_x=-0.16, offset_y=0.06)
        return r_pose, l_pose

    if sid in ("S_ESPERA", "S_DESPACIO", "S_MUCHO_GUSTO", "S_AMIGO", "S_QUERER"):
        r_pose = get_lsc_letter_pose("L_B", 0.0)
        dy_shift = (t_phase * 0.08) if sid == "S_DESPACIO" else wave_y * 0.3
        r_pose[:, 0] += 0.11
        r_pose[:, 1] += dy_shift
        l_pose = make_left_mirror(get_lsc_letter_pose("L_B", 0.0), offset_x=-0.22, offset_y=dy_shift)
        return r_pose, l_pose

    if sid == "S_MEDICO":
        # Dedos de mano derecha tocando la muñeca de la mano izquierda
        r_pose = get_lsc_letter_pose("L_V", 0.0)
        r_pose[:, 0] -= 0.04
        l_pose = make_left_mirror(get_lsc_letter_pose("L_A", 0.0), offset_x=-0.12, offset_y=-0.14)
        return r_pose, l_pose

    if sid in ("S_DONDE", "S_HABLAR"):
        r_pose = get_lsc_letter_pose("L_D", 0.0)
        r_pose[:, 0] += 0.11 + wave_x * 0.6
        l_pose = make_left_mirror(get_lsc_letter_pose("L_D", 0.0), offset_x=-0.22 - wave_x * 0.6)
        return r_pose, l_pose

    # 3. Señas Conversacionales Unimanuales
    if sid in ("S_HOLA", "S_ADIOS", "S_GRACIAS", "S_REPETIR", "S_REGULAR", "S_CANSADO", "S_HOY"):
        p = get_lsc_letter_pose("L_B", 0.0)
        # Abrir pulgar también para palma abierta natural
        p[3] = [0.30, 0.56, -0.04]
        p[4] = [0.24, 0.49, -0.05]
        if sid in ("S_ADIOS", "S_HOLA", "S_REGULAR"):
            p[:, 0] += wave_x
        elif sid in ("S_REPETIR", "S_CANSADO", "S_HOY"):
            p[:, 1] += abs(wave_y) * 1.4
        return p, None

    if sid in ("S_SI", "S_YO", "S_TU", "S_EL", "S_IR", "S_CUANDO", "S_QUIEN"):
        p = get_lsc_letter_pose("L_D", 0.0)
        p[:, 1] += wave_y * 0.6
        return p, None

    if sid in ("S_NO", "S_NO_ENTIENDO", "S_AGUA"):
        p = get_lsc_letter_pose("L_L", 0.0)
        p[:, 0] += wave_x * 0.8
        return p, None

    if sid in ("S_BIEN", "S_MANANA"):
        p = get_lsc_letter_pose("L_A", 0.0)
        return p, None

    if sid == "S_MAL":
        p = get_lsc_letter_pose("L_A", 0.0)
        # Invertir pulgar hacia abajo
        p[3] = [0.40, 0.82, -0.04]
        p[4] = [0.40, 0.90, -0.05]
        return p, None

    if sid == "S_COMER":
        p = get_lsc_letter_pose("L_Q", 0.0)
        p[:, 1] -= 0.05 + abs(wave_y) * 0.5
        return p, None

    if sid == "S_UNIVERSIDAD":
        p = get_lsc_letter_pose("L_U", 0.0)
        p[:, 0] += wave_x * 0.5
        return p, None

    if sid in ("S_DISCULPA",):
        p = get_lsc_letter_pose("L_Y", 0.0)
        return p, None

    if sid in ("S_NECESITAR",):
        p = get_lsc_letter_pose("L_X", 0.0)
        p[:, 1] += abs(wave_y)
        return p, None

    if sid in ("S_CONTINUAR", "S_NOSOTROS", "S_POR_QUE"):
        p = get_lsc_letter_pose("L_V", 0.0)
        return p, None

    return get_lsc_letter_pose("L_B", 0.0), None


class ConversationEngine:
    """
    Motor central de traducción bidireccional y Abecedario LSC:
    - Persona Sorda (Señas LSC + Deletreo A-Z/Ñ -> Conjugación Gramatical -> Texto y TTS)
    - Oyente / Traductor Inverso (Frase hablada o escrita -> Modelo 3D de Manos Animado + Texto)
    """

    def __init__(self):
        self.sign_submode: str = "HYBRID"  # "CONVERSATION" | "ALPHABET_LSC" | "HYBRID"
        self.active_tokens: List[Dict[str, Any]] = []
        self.current_sentence: str = ""
        self.raw_gloss_sentence: str = ""
        self.chat_history: List[Dict[str, Any]] = []
        self.last_added_sign_id: Optional[str] = None
        self.last_added_ts: float = 0.0
        self.cooldown_sec: float = 1.05
        self.gesture_released: bool = True
        self.max_tokens: int = 18
        self.tts_queue: List[str] = []

        # Estado del Reproductor Visual de Manos 3D (Traducción de Frases -> Modelo de Manos)
        self.hand_animation_queue: List[Dict[str, Any]] = []
        self.current_animation_step: Optional[Dict[str, Any]] = None
        self.animation_step_start_ts: float = 0.0
        self.animation_phrase_text: str = ""
        self.animation_total_steps: int = 0
        self.animation_current_index: int = 0

        self._init_chat()

    def _init_chat(self) -> None:
        self.chat_history = [
            {
                "id": "msg_0",
                "sender": "SYSTEM",
                "sender_label": "SignBridge v4.0 LSC",
                "text": "Traductor de Lengua de Señas Colombiana (LSC) Activo: Reconoce las 27 letras del Abecedario LSC (A–Z + Ñ), +45 señas conversacionales y traduce frases habladas o escritas mediante el Modelo 3D de Manos.",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "sign_ids": [],
            }
        ]

    def set_submode(self, submode: str) -> str:
        sm = submode.upper().strip()
        if sm in ("CONVERSATION", "ALPHABET_LSC", "HYBRID"):
            self.sign_submode = sm
        return self.sign_submode

    def get_sign_meta(self, sign_id: str) -> Dict[str, Any]:
        """Obtiene la metadata de una seña conversacional o de una letra del Abecedario LSC."""
        if sign_id in CONVERSATIONAL_SIGNS_CATALOG:
            return CONVERSATIONAL_SIGNS_CATALOG[sign_id]
        if sign_id in LSC_ALPHABET_CATALOG:
            meta_l = LSC_ALPHABET_CATALOG[sign_id]
            return {
                "id": sign_id,
                "label": meta_l["letter"],
                "full_name": meta_l["full_name"],
                "emoji": meta_l["emoji"],
                "category": "Abecedario LSC",
                "bimanual": False,
                "default_phrase": f"Letra {meta_l['letter']}",
                "description": meta_l["description"],
                "color": meta_l["color"],
                "is_letter": True,
            }
        return {
            "id": sign_id,
            "label": sign_id,
            "emoji": "💬",
            "category": "General",
            "default_phrase": sign_id,
            "color": "#00F0FF",
        }

    def classify_bimanual_gesture(
        self,
        multi_hand: Dict[str, Any],
        motion: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evalúa relaciones inter-manuales y dinámicas cinemáticas si hay 2 manos en escena
        para reconocer señas bimanuales de LSC (Ayuda, Por favor, Casa, Trabajar, Estudiar,
        Espera, ¿Cómo estás?, ¿Qué?, ¿Dónde?, Mucho gusto, Más despacio, Médico).
        """
        if not multi_hand or multi_hand.get("hands_count", 0) < 2:
            return None

        inter = multi_hand.get("inter_hand")
        if not inter:
            return None

        p0 = multi_hand["primary"]
        p1 = multi_hand["secondary"]
        f0 = p0["telemetry"]["fingers"]
        f1 = p1["telemetry"]["fingers"]

        b_motion = motion.get("bimanual", {}) if motion else {}
        p_motion = motion.get("primary", {}) if motion else {}
        s_motion = motion.get("secondary", {}) if motion else {}

        # 1. Puño sobre palma -> AYUDA / ASISTENCIA SOS
        if inter.get("fist_on_palm_help"):
            return {
                "sign_id": "S_AYUDA",
                "confidence": 0.98,
                "note": "Bimanual LSC: Puño sobre palma plana (Ayuda)",
                "is_dynamic": False,
            }

        # 2. Ambos puños juntos -> TRABAJAR (S_TRABAJAR)
        if inter.get("fists_together_trabajar"):
            return {
                "sign_id": "S_TRABAJAR",
                "confidence": 0.96,
                "note": "Bimanual LSC: Puños unidos (Trabajar)",
                "is_dynamic": False,
            }

        # 3. Techo triangular con ambas manos -> CASA (S_CASA)
        if inter.get("roof_triangle_casa"):
            return {
                "sign_id": "S_CASA",
                "confidence": 0.96,
                "note": "Bimanual LSC: Techo triangular con ambas manos (Casa)",
                "is_dynamic": False,
            }

        # 4. Dedo índice tocando la muñeca de la otra mano -> MÉDICO / DOLOR
        wrist_dist = inter.get("wrist_dist", 1.0)
        idx_tip_dist = inter.get("index_tip_dist", 1.0)
        if inter.get("index_on_wrist") or (wrist_dist < 0.28 and (f0["index"] or f1["index"]) and idx_tip_dist < 0.28):
            return {
                "sign_id": "S_MEDICO",
                "confidence": 0.96,
                "note": "Bimanual LSC: Toque de pulso/muñeca (Médico/Dolor)",
                "is_dynamic": False,
            }

        # 5. Ambas palmas abiertas descendiendo con calma -> MÁS DESPACIO
        if (f0["index"] and f0["middle"] and f1["index"] and f1["middle"]) and (
            b_motion.get("both_moving_down") or
            (p_motion.get("is_moving_down") and s_motion.get("is_moving_down")) or
            p_motion.get("is_moving_down")
        ):
            return {
                "sign_id": "S_DESPACIO",
                "confidence": 0.97,
                "note": "Bimanual dinámico: Palmas descendiendo (Más despacio)",
                "is_dynamic": True,
            }

        # 6. Ambas manos abriéndose hacia los lados desde el centro -> ¿CÓMO ESTÁS?
        if (inter.get("both_question") or (f0["index"] and f0["middle"] and f1["index"] and f1["middle"])) and (
            b_motion.get("is_diverging") or (p_motion.get("is_moving_horiz") and s_motion.get("is_moving_horiz"))
        ):
            return {
                "sign_id": "S_COMO_ESTAS",
                "confidence": 0.97,
                "note": "Bimanual dinámico: Manos abriéndose (¿Cómo estás?)",
                "is_dynamic": True,
            }

        # 7. Ambas palmas abiertas hacia arriba oscilando -> ¿QUÉ?
        if inter.get("both_question") and (
            b_motion.get("both_oscillating") or
            p_motion.get("is_oscillating_x") or
            s_motion.get("is_oscillating_x") or
            p_motion.get("is_oscillating_y") or
            s_motion.get("is_oscillating_y")
        ):
            return {
                "sign_id": "S_QUE",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Palmas abiertas oscilando (¿Qué?)",
                "is_dynamic": True,
            }

        # 8. Índices de ambas manos apuntando -> ¿DÓNDE?
        if (f0["index"] and not f0["middle"] and not f0["ring"] and not f0["pinky"]) and \
           (f1["index"] and not f1["middle"] and not f1["ring"] and not f1["pinky"]):
            return {
                "sign_id": "S_DONDE",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Índices señalando en búsqueda (¿Dónde?)",
                "is_dynamic": True,
            }

        # 9. Manos convergiendo desde los costados hacia el centro -> MUCHO GUSTO
        if b_motion.get("is_converging") and not b_motion.get("is_diverging"):
            return {
                "sign_id": "S_MUCHO_GUSTO",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Manos encontrándose (Mucho gusto)",
                "is_dynamic": True,
            }
        if inter.get("hands_touching") and (p_motion.get("is_moving") or s_motion.get("is_moving")) and not b_motion.get("is_diverging"):
            return {
                "sign_id": "S_MUCHO_GUSTO",
                "confidence": 0.95,
                "note": "Bimanual dinámico: Manos encontrándose (Mucho gusto)",
                "is_dynamic": True,
            }

        # 10. Mano dominante saliendo del pecho y ascendiendo -> BUENOS DÍAS
        if (f0["index"] and f0["middle"] and f1["index"] and f1["middle"]) and (
            p_motion.get("is_moving_up") or b_motion.get("both_moving_up")
        ) and not inter.get("roof_triangle_casa"):
            return {
                "sign_id": "S_BUENOS_DIAS",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Mano ascendiendo como el sol naciente (Buenos días)",
                "is_dynamic": True,
            }

        # 11. Mano dominante deslizándose horizontalmente sobre el antebrazo -> BUENAS TARDES
        if (f0["index"] and f0["middle"]) and (
            b_motion.get("one_moving_horiz") or p_motion.get("is_moving_horiz") or p_motion.get("trace_h")
        ) and inter.get("wrist_dist", 1.0) < 0.42:
            return {
                "sign_id": "S_BUENAS_TARDES",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Mano deslizándose sobre antebrazo (Buenas tardes)",
                "is_dynamic": True,
            }

        # 12. Mano dominante descendiendo en arco frente al brazo base -> BUENAS NOCHES
        if (f0["index"] and f0["middle"]) and p_motion.get("is_moving_down") and inter.get("wrist_dist", 1.0) < 0.42:
            return {
                "sign_id": "S_BUENAS_NOCHES",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Mano descendiendo en arco (Buenas noches)",
                "is_dynamic": True,
            }

        # 13. Ambas manos ascendiendo frente al pecho -> FELIZ
        if (f0["index"] and f0["middle"] and f1["index"] and f1["middle"]) and (
            b_motion.get("both_moving_up") or (p_motion.get("is_moving_up") and s_motion.get("is_moving_up"))
        ):
            return {
                "sign_id": "S_FELIZ",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Ambas manos ascendiendo alegremente (Feliz)",
                "is_dynamic": True,
            }

        # 14. Dedos índices alternando movimiento frente al pecho -> HABLAR / CONVERSAR
        if (f0["index"] and not f0["middle"] and f1["index"] and not f1["middle"]) and (
            p_motion.get("is_moving") or s_motion.get("is_moving") or b_motion.get("both_oscillating")
        ):
            return {
                "sign_id": "S_HABLAR",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Índices en diálogo alternado (Hablar)",
                "is_dynamic": True,
            }

        # 15. Palmas juntas frente al pecho -> POR FAVOR
        if inter.get("palms_together"):
            return {
                "sign_id": "S_POR_FAVOR",
                "confidence": 0.96,
                "note": "Bimanual: Palmas unidas frente al pecho (Por favor)",
                "is_dynamic": False,
            }

        # 16. Mano plana y otra mano leyendo encima -> ESTUDIAR / APRENDER
        if inter.get("book_open_estudiar"):
            return {
                "sign_id": "S_ESTUDIAR",
                "confidence": 0.95,
                "note": "Bimanual LSC: Mano sobre palma base (Estudiar)",
                "is_dynamic": False,
            }

        # 17. Ambas manos abiertas hacia arriba estáticas -> ¿CÓMO ESTÁS?
        if inter.get("both_question"):
            return {
                "sign_id": "S_COMO_ESTAS",
                "confidence": 0.94,
                "note": "Bimanual: Palmas abiertas hacia arriba (¿Cómo estás?)",
                "is_dynamic": False,
            }

        # 18. Ambas manos abiertas hacia el frente -> ESPERA / PAUSA
        if inter.get("both_open_forward"):
            return {
                "sign_id": "S_ESPERA",
                "confidence": 0.95,
                "note": "Bimanual: Ambas palmas abiertas al frente (Espera)",
                "is_dynamic": False,
            }

        return None

    def classify_unimanual_gesture(
        self,
        multi_hand: Dict[str, Any],
        motion: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Clasifica señas conversacionales unimanuales e integra el Abecedario LSC (27 letras)
        según el sub-modo activo (`CONVERSATION`, `ALPHABET_LSC` o `HYBRID`).
        """
        if not multi_hand or not multi_hand.get("primary"):
            return None

        # A) Si el usuario seleccionó explícitamente el modo ABECEDARIO LSC (Deletreo)
        if self.sign_submode == "ALPHABET_LSC":
            alpha_match = classify_lsc_alphabet(multi_hand, motion=motion)
            if alpha_match:
                return alpha_match

        primary = multi_hand["primary"]
        telem = primary.get("telemetry", {})
        fingers = telem.get("fingers", {})
        fine = telem.get("fine", {})
        pts = primary.get("landmarks")

        thumb = bool(fingers.get("thumb", False))
        index = bool(fingers.get("index", False))
        middle = bool(fingers.get("middle", False))
        ring = bool(fingers.get("ring", False))
        pinky = bool(fingers.get("pinky", False))

        p_motion = motion.get("primary", {}) if motion else {}
        is_waving_x = bool(p_motion.get("is_oscillating_x"))
        is_waving_y = bool(p_motion.get("is_oscillating_y"))
        is_moving_down = bool(p_motion.get("is_moving_down"))
        is_moving_up = bool(p_motion.get("is_moving_up"))

        # B) Gestos dinámicos deliberados del Abecedario LSC (H, J, Z, Ñ, G, S)
        alpha_match = classify_lsc_alphabet(multi_hand, motion=motion)
        if alpha_match:
            is_alpha_dyn = bool(alpha_match.get("is_dynamic", False))
            if is_alpha_dyn:
                return alpha_match

        # C) Evaluaciones Dinámicas Conversacionales (Mano en movimiento activo)
        if is_waving_x:
            if index and middle and ring and pinky:
                return {
                    "sign_id": "S_ADIOS",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Mano abierta oscilando (Adiós)",
                    "is_dynamic": True,
                }
            if pts is not None and len(pts) > 8 and pts[8][1] < 0.38 and index and not middle:
                return {
                    "sign_id": "S_NO_ENTIENDO",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Dedo índice en la sien oscilando (No entiendo)",
                    "is_dynamic": True,
                }
            if index and not middle and not ring and not pinky:
                return {
                    "sign_id": "S_NO",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Dedo índice oscilando en negación (No)",
                    "is_dynamic": True,
                }
            if not index and not middle and thumb:
                return {
                    "sign_id": "S_REGULAR",
                    "confidence": 0.95,
                    "note": "Unimanual dinámico: Bamboleo horizontal (Más o menos)",
                    "is_dynamic": True,
                }

        if is_waving_y:
            if not index and not middle and not ring and not pinky:
                return {
                    "sign_id": "S_SI",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Puño asintiendo verticalmente (Sí)",
                    "is_dynamic": True,
                }
            if index and not middle and not ring and not pinky:
                return {
                    "sign_id": "S_SI",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Dedo índice asintiendo verticalmente (Sí)",
                    "is_dynamic": True,
                }

        if is_moving_down:
            if index and middle and ring and pinky:
                return {
                    "sign_id": "S_REPETIR",
                    "confidence": 0.96,
                    "note": "Unimanual dinámico: Mano abierta descendiendo (Repetir)",
                    "is_dynamic": True,
                }
            if not index and not middle and not ring and not pinky:
                return {
                    "sign_id": "S_NECESITAR",
                    "confidence": 0.96,
                    "note": "Unimanual dinámico: Puño descendiendo con firmeza (Necesitar)",
                    "is_dynamic": True,
                }

        if is_moving_up:
            if index and middle and ring and pinky:
                return {
                    "sign_id": "S_GRACIAS",
                    "confidence": 0.96,
                    "note": "Unimanual dinámico: Mano proyectándose desde el mentón (Gracias)",
                    "is_dynamic": True,
                }
            if index and not middle and not ring and not pinky:
                return {
                    "sign_id": "S_IR",
                    "confidence": 0.96,
                    "note": "Unimanual dinámico: Dedo índice proyectándose hacia adelante/arriba (Ir)",
                    "is_dynamic": True,
                }

        # D) Evaluación de Posturas Estáticas (Sin movimiento cinemático brusco)
        # 1. Pulgar abajo (S_MAL) vs Pulgar arriba (S_BIEN / Letra A)
        if thumb and not index and not middle and not ring and not pinky and pts is not None and len(pts) >= 5:
            thumb_y = pts[4][1]
            wrist_y = pts[0][1]
            if thumb_y > (wrist_y + 0.04):
                return {
                    "sign_id": "S_MAL",
                    "confidence": 0.97,
                    "note": "Unimanual: Pulgar apuntando hacia abajo (Mal)",
                    "is_dynamic": False,
                }
            d_thumb_idx = float(fine.get("d_thumb_idx", 0.35))
            if d_thumb_idx > 0.30 and self.sign_submode != "ALPHABET_LSC":
                return {
                    "sign_id": "S_BIEN",
                    "confidence": 0.97,
                    "note": "Unimanual: Pulgar arriba firme (Bien / OK)",
                    "is_dynamic": False,
                }
            elif self.sign_submode in ("HYBRID", "ALPHABET_LSC"):
                return {
                    "sign_id": "L_A",
                    "confidence": 0.97,
                    "note": "Abecedario LSC: Letra A (Puño cerrado con pulgar al costado del índice)",
                    "is_dynamic": False,
                }

        # 2. Mano abierta estática: S_HOLA (palma extendida con pulgar abierto) vs L_B (4 dedos juntos, pulgar en palma)
        if index and middle and ring and pinky:
            spread = float(fine.get("idx_mid_spread", 0.5))
            if thumb and spread >= 0.25 and self.sign_submode != "ALPHABET_LSC":
                return {
                    "sign_id": "S_HOLA",
                    "confidence": 0.96,
                    "note": "Unimanual: Palma abierta en saludo (Hola)",
                    "is_dynamic": False,
                }
            if self.sign_submode in ("HYBRID", "ALPHABET_LSC"):
                return {
                    "sign_id": "L_B",
                    "confidence": 0.96,
                    "note": "Abecedario LSC: Letra B (4 dedos unidos)",
                    "is_dynamic": False,
                }

        # 3. En sub-modos HYBRID y ALPHABET_LSC: priorizar el Abecedario LSC Completo (27 Letras)
        if self.sign_submode in ("HYBRID", "ALPHABET_LSC"):
            if alpha_match and alpha_match.get("confidence", 0.0) >= 0.82:
                return alpha_match

        # 4. En sub-modo CONVERSATION puro: evaluar señas estáticas clásicas
        if index and not middle and not ring and not pinky:
            if thumb:
                return {
                    "sign_id": "S_NO",
                    "confidence": 0.96,
                    "note": "Unimanual: Índice y pulgar en L (No)",
                    "is_dynamic": False,
                }
            return {
                "sign_id": "S_SI",
                "confidence": 0.96,
                "note": "Unimanual: Solo índice vertical (Sí)",
                "is_dynamic": False,
            }

        if index and middle and not ring and not pinky:
            return {
                "sign_id": "S_CONTINUAR",
                "confidence": 0.96,
                "note": "Unimanual: Paz / Victoria (Continuar)",
                "is_dynamic": False,
            }

        if not index and not middle and not ring and not pinky and not thumb:
            return {
                "sign_id": "S_ENTENDIDO",
                "confidence": 0.97,
                "note": "Unimanual: Puño cerrado (Entendido)",
                "is_dynamic": False,
            }

        if (index and middle and ring and not pinky) or (thumb and pinky and not index and not middle and not ring):
            return {
                "sign_id": "S_AYUDA",
                "confidence": 0.96,
                "note": "Unimanual: Señal Shaka o 3 dedos (Ayuda)",
                "is_dynamic": False,
            }

        return None

    def process_frame_sign(
        self,
        raw_gesture_id: str,
        confidence: float,
        multi_hand: Dict[str, Any],
        is_triggered: bool,
        motion: Optional[Dict[str, Any]] = None,
        is_online: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Evalúa el fotograma actual para la traducción conversacional o dactilológica LSC:
        - Si el modo es ONLINE (Gemini Multimodal Cloud) y hay una seña o letra reconocida por la nube,
          se toma directamente con máxima prioridad diagnóstica (sin ser sobreescrita por el modelo local).
        - En modo OFFLINE:
          Prioridad 1: Señas bimanuales (si hay 2 manos y el modo no es exclusivo de deletreo)
          Prioridad 2: Clasificador unimanual / Abecedario LSC (según sign_submode)
          Prioridad 3: Seña directa si raw_gesture_id es una seña conversacional o letra LSC.
        (Los comandos básicos G1..G5 de control OS están aislados y NO se mapean a señas).
        """
        sign_id = None
        source_note = ""

        # En modo Online con Gemini: la inferencia multimodal de la nube tiene prioridad absoluta
        if is_online and (raw_gesture_id in CONVERSATIONAL_SIGNS_CATALOG or raw_gesture_id in LSC_ALPHABET_CATALOG):
            sign_id = raw_gesture_id
            source_note = "Gemini Online Multimodal"
        else:
            if self.sign_submode != "ALPHABET_LSC":
                bimanual_match = self.classify_bimanual_gesture(multi_hand, motion=motion)
                if bimanual_match:
                    sign_id = bimanual_match["sign_id"]
                    confidence = max(confidence, bimanual_match["confidence"])
                    source_note = bimanual_match["note"]

            if not sign_id:
                unimanual_match = self.classify_unimanual_gesture(multi_hand, motion=motion)
                if unimanual_match:
                    sign_id = unimanual_match["sign_id"]
                    confidence = max(confidence, unimanual_match["confidence"])
                    source_note = unimanual_match["note"]
                elif raw_gesture_id in CONVERSATIONAL_SIGNS_CATALOG or raw_gesture_id in LSC_ALPHABET_CATALOG:
                    sign_id = raw_gesture_id
                    source_note = "Seña directa"

        if not sign_id or (sign_id not in CONVERSATIONAL_SIGNS_CATALOG and sign_id not in LSC_ALPHABET_CATALOG):
            self.gesture_released = True
            return None

        if sign_id != self.last_added_sign_id:
            self.gesture_released = True

        sign_meta = self.get_sign_meta(sign_id)

        now = time.perf_counter()
        can_trigger = False
        if is_triggered and (now - self.last_added_ts) > self.cooldown_sec:
            if sign_id != self.last_added_sign_id or self.gesture_released or (now - self.last_added_ts) > 2.8:
                can_trigger = True

        if can_trigger:
            self.last_added_ts = now
            self.last_added_sign_id = sign_id
            self.gesture_released = False
            is_letter = sign_id in LSC_ALPHABET_CATALOG
            token_entry = {
                "sign_id": sign_id,
                "label": sign_meta["label"],
                "emoji": sign_meta["emoji"],
                "default_phrase": sign_meta["default_phrase"],
                "is_letter": is_letter,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            self.active_tokens.append(token_entry)

            if len(self.active_tokens) > self.max_tokens:
                self.active_tokens = self.active_tokens[-self.max_tokens:]

            self._update_sentence_from_tokens()

            # Pronunciar letra o palabra agregada
            self.tts_queue.append(sign_meta["label"])

        return {
            "sign_id": sign_id,
            "label": sign_meta["label"],
            "emoji": sign_meta["emoji"],
            "category": sign_meta["category"],
            "default_phrase": sign_meta["default_phrase"],
            "confidence": round(confidence, 3),
            "source_note": source_note,
            "is_letter": sign_id in LSC_ALPHABET_CATALOG,
        }

    def add_manual_sign_or_letter(self, sign_id: str) -> Dict[str, Any]:
        """Permite insertar directamente una seña o letra LSC desde el panel interactivo."""
        sid = sign_id.upper().strip()
        if len(sid) == 1 and sid in CHAR_TO_LSC_ID:
            sid = CHAR_TO_LSC_ID[sid]
        if sid not in CONVERSATIONAL_SIGNS_CATALOG and sid not in LSC_ALPHABET_CATALOG:
            return {"added": False, "error": f"ID desconocido: {sid}"}

        meta = self.get_sign_meta(sid)
        token_entry = {
            "sign_id": sid,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "default_phrase": meta["default_phrase"],
            "is_letter": sid in LSC_ALPHABET_CATALOG,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        self.active_tokens.append(token_entry)
        if len(self.active_tokens) > self.max_tokens:
            self.active_tokens = self.active_tokens[-self.max_tokens:]
        self._update_sentence_from_tokens()
        self.tts_queue.append(meta["label"])
        return {
            "added": True,
            "token": token_entry,
            "sentence": self.current_sentence,
            "current_sentence": self.current_sentence,
        }

    def _update_sentence_from_tokens(self) -> None:
        """
        Construye una oración gramaticalmente fluida en español a partir de las glosas LSC
        y fusiona automáticamente las letras consecutivas del abecedario dactilológico en palabras.
        """
        if not self.active_tokens:
            self.current_sentence = ""
            self.raw_gloss_sentence = ""
            return

        # Paso 1: Agrupar letras consecutivas (ej. L_A + L_N + L_A -> "Ana")
        grouped_items: List[Tuple[str, str]] = []  # (sign_id_or_SPELLED, display_word)
        letter_buf: List[str] = []

        def flush_letters():
            if letter_buf:
                word = "".join(letter_buf).capitalize()
                grouped_items.append(("SPELLED_WORD", word))
                letter_buf.clear()

        for tok in self.active_tokens:
            sid = tok["sign_id"]
            if sid in LSC_ALPHABET_CATALOG:
                letter_buf.append(LSC_ALPHABET_CATALOG[sid]["letter"])
            else:
                flush_letters()
                grouped_items.append((sid, tok["label"]))
        flush_letters()

        self.raw_gloss_sentence = " + ".join(w for _, w in grouped_items)

        # Paso 2: Si solo hay 1 seña conversacional y no es letra deletreada, usar su frase natural completa
        if len(grouped_items) == 1 and grouped_items[0][0] in CONVERSATIONAL_SIGNS_CATALOG:
            sid0 = grouped_items[0][0]
            self.current_sentence = CONVERSATIONAL_SIGNS_CATALOG[sid0]["default_phrase"]
            return

        # Paso 3: Conjugación morfosintáctica LSC -> Español para secuencias de múltiples tokens
        subj: Optional[str] = None  # "1S", "2S", "3S", "1P"
        verb_conjugations = {
            "S_QUERER": {"1S": "quiero", "2S": "quieres", "3S": "quiere", "1P": "queremos", "DEF": "quiero"},
            "S_NECESITAR": {"1S": "necesito", "2S": "necesitas", "3S": "necesita", "1P": "necesitamos", "DEF": "necesito"},
            "S_COMER": {"1S": "quiero comer", "2S": "quieres comer", "3S": "quiere comer", "1P": "queremos comer", "DEF": "comer"},
            "S_AGUA": {"1S": "quiero agua", "2S": "quieres agua", "3S": "quiere agua", "1P": "queremos agua", "DEF": "agua"},
            "S_ESTUDIAR": {"1S": "estudio", "2S": "estudias", "3S": "estudia", "1P": "estudiamos", "DEF": "estudiar"},
            "S_TRABAJAR": {"1S": "trabajo", "2S": "trabajas", "3S": "trabaja", "1P": "trabajamos", "DEF": "trabajar"},
            "S_HABLAR": {"1S": "hablo", "2S": "hablas", "3S": "habla", "1P": "hablamos", "DEF": "hablar"},
            "S_IR": {"1S": "voy a", "2S": "vas a", "3S": "va a", "1P": "vamos a", "DEF": "ir a"},
            "S_ENTENDIDO": {"1S": "entiendo", "2S": "entiendes", "3S": "entiende", "1P": "entendemos", "DEF": "entendido"},
            "S_NO_ENTIENDO": {"1S": "no entiendo", "2S": "no entiendes", "3S": "no entiende", "1P": "no entendemos", "DEF": "no entiendo"},
        }

        words_out: List[str] = []
        for idx, (sid, lbl) in enumerate(grouped_items):
            if sid == "S_YO":
                subj = "1S"
                words_out.append("Yo")
            elif sid == "S_TU":
                subj = "2S"
                words_out.append("tú")
            elif sid == "S_EL":
                subj = "3S"
                words_out.append("él")
            elif sid == "S_NOSOTROS":
                subj = "1P"
                words_out.append("nosotros")
            elif sid in verb_conjugations:
                conj = verb_conjugations[sid].get(subj or "DEF", lbl.lower())
                words_out.append(conj)
            elif sid == "S_CASA":
                prev_sid = grouped_items[idx - 1][0] if idx > 0 else ""
                words_out.append("casa" if prev_sid == "S_IR" else "en casa")
            elif sid == "S_UNIVERSIDAD":
                prev_sid = grouped_items[idx - 1][0] if idx > 0 else ""
                words_out.append("la universidad" if prev_sid == "S_IR" else "en la universidad")
            elif sid in ("S_BIEN", "S_MAL", "S_FELIZ", "S_CANSADO", "S_OCUPADO"):
                state_word = lbl.split("/")[0].strip().lower()
                if subj == "1S":
                    words_out.append(f"estoy {state_word}")
                elif subj == "2S":
                    words_out.append(f"estás {state_word}")
                else:
                    words_out.append(state_word)
            elif sid == "SPELLED_WORD":
                words_out.append(lbl)
            else:
                clean_lbl = lbl.split("/")[0].strip()
                words_out.append(clean_lbl.lower() if idx > 0 and not clean_lbl.startswith("¿") else clean_lbl)

        sentence = " ".join(words_out).strip()
        if sentence:
            sentence = sentence[0].upper() + sentence[1:]
            if not sentence.endswith((".", "?", "!")):
                sentence += "."
        self.current_sentence = sentence

    def translate_phrase_to_hand_sequence(self, text: str) -> Dict[str, Any]:
        """
        TRADUCTOR INVERSO (Frases / Texto / Voz -> Modelo 3D de Manos):
        Recibe una frase en español, la descompone en una secuencia ordenada de señas
        conversacionales LSC (1 o 2 manos) y deletrea automáticamente con el Abecedario LSC
        cualquier nombre propio o palabra fuera del diccionario léxico.
        """
        clean_input = text.strip()
        if not clean_input:
            return {"started": False, "steps": [], "phrase": ""}

        norm_text = _strip_accents_keep_ntilde(clean_input.lower())
        # Reemplazar signos de puntuación por espacios manteniendo letras y ñ
        norm_text = re.sub(r"[^a-zñ0-9\s]", " ", norm_text)
        norm_text = re.sub(r"\s+", " ", norm_text).strip()

        # Reemplazar frases multi-palabra primero por tokens especiales __SIGN_ID__
        working = norm_text
        for phrase_pat, target_sid in SPANISH_MULTIWORD_PHRASES:
            working = re.sub(rf"\b{re.escape(phrase_pat)}\b", f" __{target_sid}__ ", working)

        raw_words = [w for w in working.split() if w]
        steps: List[Dict[str, Any]] = []

        for tok in raw_words:
            if tok.startswith("__S_") and tok.endswith("__"):
                sid = tok[2:-2]
                meta = self.get_sign_meta(sid)
                steps.append({
                    "sign_id": sid,
                    "label": meta["label"],
                    "subtitle": f"{meta['emoji']} {meta['label']}",
                    "description": meta.get("description", ""),
                    "bimanual": bool(meta.get("bimanual", False)),
                    "is_letter": False,
                    "source_word": meta["label"],
                    "duration_sec": 1.35,
                })
                continue

            if tok in SPANISH_WORD_TO_SIGN_ID:
                sid = SPANISH_WORD_TO_SIGN_ID[tok]
                meta = self.get_sign_meta(sid)
                steps.append({
                    "sign_id": sid,
                    "label": meta["label"],
                    "subtitle": f"{meta['emoji']} {meta['label']}",
                    "description": meta.get("description", ""),
                    "bimanual": bool(meta.get("bimanual", False)),
                    "is_letter": False,
                    "source_word": tok.capitalize(),
                    "duration_sec": 1.30,
                })
                continue

            # Ignorar conectores vacíos si hay más palabras en la frase
            if tok in SPANISH_STOPWORDS and len(raw_words) > 1:
                continue

            # Palabra o nombre propio fuera del diccionario -> Deletrear con el Abecedario LSC
            word_upper = tok.upper()
            for ch in word_upper:
                if ch in CHAR_TO_LSC_ID:
                    lid = CHAR_TO_LSC_ID[ch]
                    lmeta = LSC_ALPHABET_CATALOG[lid]
                    steps.append({
                        "sign_id": lid,
                        "label": f"Letra {ch}",
                        "subtitle": f"🔤 Deletreando \"{word_upper}\": [{ch}]",
                        "description": lmeta["description"],
                        "bimanual": False,
                        "is_letter": True,
                        "source_word": word_upper,
                        "letter": ch,
                        "duration_sec": 0.95,
                    })

        if not steps:
            # Si toda la frase eran stopwords (ej. "es un"), deletrear la primera palabra
            first_w = raw_words[0].upper() if raw_words else "A"
            for ch in first_w:
                if ch in CHAR_TO_LSC_ID:
                    lid = CHAR_TO_LSC_ID[ch]
                    lmeta = LSC_ALPHABET_CATALOG[lid]
                    steps.append({
                        "sign_id": lid,
                        "label": f"Letra {ch}",
                        "subtitle": f"🔤 Deletreando \"{first_w}\": [{ch}]",
                        "description": lmeta["description"],
                        "bimanual": False,
                        "is_letter": True,
                        "source_word": first_w,
                        "letter": ch,
                        "duration_sec": 0.95,
                    })

        self.hand_animation_queue = list(steps)
        self.animation_phrase_text = clean_input
        self.animation_total_steps = len(steps)
        self.animation_current_index = 0
        self.current_animation_step = self.hand_animation_queue.pop(0) if self.hand_animation_queue else None
        self.animation_step_start_ts = time.perf_counter()

        return {
            "started": True,
            "phrase": clean_input,
            "total_steps": len(steps),
            "steps": steps,
        }

    def get_active_hand_animation_frame(self) -> Optional[Dict[str, Any]]:
        """
        Avanza el reloj del Reproductor Visual de Manos 3D y retorna las poses 3D
        (primaria y secundaria) junto con el subtítulo sincronizado de la frase en curso.
        """
        if self.current_animation_step is None:
            return None

        now = time.perf_counter()
        elapsed = now - self.animation_step_start_ts
        duration = float(self.current_animation_step.get("duration_sec", 1.2))

        if elapsed >= duration:
            if self.hand_animation_queue:
                self.current_animation_step = self.hand_animation_queue.pop(0)
                self.animation_current_index += 1
                self.animation_step_start_ts = now
                elapsed = 0.0
                duration = float(self.current_animation_step.get("duration_sec", 1.2))
            else:
                self.current_animation_step = None
                return None

        t_phase = min(1.0, max(0.0, elapsed / max(0.1, duration)))
        step = self.current_animation_step
        p_pose, s_pose = get_sign_3d_poses(step["sign_id"], t_phase=t_phase)

        return {
            "active": True,
            "phrase": self.animation_phrase_text,
            "step_index": self.animation_current_index + 1,
            "total_steps": self.animation_total_steps,
            "sign_id": step["sign_id"],
            "label": step["label"],
            "subtitle": step["subtitle"],
            "description": step["description"],
            "bimanual": step["bimanual"],
            "is_letter": step["is_letter"],
            "source_word": step.get("source_word", ""),
            "progress": round(t_phase, 2),
            "primary_pose": p_pose,
            "secondary_pose": s_pose,
        }

    def commit_sentence(self, custom_phrase: Optional[str] = None) -> Dict[str, Any]:
        """
        Finaliza la oración en construcción generada por la persona sorda,
        la agrega al historial conversacional de chat y solicita reproducción TTS.
        """
        phrase = custom_phrase or self.current_sentence
        if not phrase and self.active_tokens:
            self._update_sentence_from_tokens()
            phrase = self.current_sentence

        if not phrase:
            return {"committed": False, "message": "Buffer vacío"}

        sign_ids = [t["sign_id"] for t in self.active_tokens]
        msg_id = f"msg_{len(self.chat_history)}"
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "id": msg_id,
            "sender": "DEAF",
            "sender_label": "Persona Sorda (Señas LSC)",
            "text": phrase,
            "timestamp": ts,
            "sign_ids": sign_ids,
        }
        self.chat_history.append(entry)
        self.tts_queue.append(phrase)

        self.active_tokens.clear()
        self.current_sentence = ""
        self.raw_gloss_sentence = ""
        self.last_added_sign_id = None
        self.gesture_released = True

        return {"committed": True, "entry": entry}

    def add_hearing_message(self, text: str, animate_hands: bool = True) -> Dict[str, Any]:
        """
        Registra un mensaje de voz transcripto (STT) o escrito por el oyente y,
        automáticamente, dispara la traducción al Modelo 3D de Manos para que la
        persona sorda vea tanto el texto como la secuencia de señas/letras en pantalla.
        """
        clean_text = text.strip()
        if not clean_text:
            return {"added": False}

        msg_id = f"msg_{len(self.chat_history)}"
        ts = datetime.now().strftime("%H:%M:%S")

        anim_info = None
        if animate_hands:
            anim_info = self.translate_phrase_to_hand_sequence(clean_text)

        entry = {
            "id": msg_id,
            "sender": "HEARING",
            "sender_label": "Oyente (Voz -> Modelo 3D LSC)",
            "text": clean_text,
            "timestamp": ts,
            "sign_ids": [s["sign_id"] for s in (anim_info.get("steps", []) if anim_info else [])],
        }
        self.chat_history.append(entry)
        return {"added": True, "entry": entry, "animation": anim_info}

    def backspace(self) -> Dict[str, Any]:
        """Elimina el último token del buffer."""
        if self.active_tokens:
            removed = self.active_tokens.pop()
            self._update_sentence_from_tokens()
            self.last_added_sign_id = self.active_tokens[-1]["sign_id"] if self.active_tokens else None
            self.gesture_released = True
            return {"removed": removed, "remaining": len(self.active_tokens)}
        return {"removed": None, "remaining": 0}

    def clear_tokens(self) -> None:
        """Limpia el buffer de construcción de oraciones."""
        self.active_tokens.clear()
        self.current_sentence = ""
        self.raw_gloss_sentence = ""
        self.last_added_sign_id = None
        self.gesture_released = True

    def pop_tts_queue(self) -> Optional[str]:
        """Obtiene y limpia el próximo mensaje a pronunciar por el sintetizador de voz."""
        if self.tts_queue:
            return self.tts_queue.pop(0)
        return None

    def get_state(self) -> Dict[str, Any]:
        """Retorna el estado completo del motor conversacional y del animador de manos 3D."""
        cur_step = self.current_animation_step or {}
        cur_sid = cur_step.get("sign_id", "")
        cur_meta = self.get_sign_meta(cur_sid) if cur_sid else {}
        anim_payload = {
            "active": self.current_animation_step is not None,
            "phrase": self.animation_phrase_text,
            "step_index": self.animation_current_index + 1 if self.current_animation_step else 0,
            "total_steps": self.animation_total_steps,
            "sign_id": cur_sid,
            "emoji": cur_meta.get("emoji", "🖐️"),
            "label": cur_step.get("label", ""),
            "subtitle": cur_step.get("subtitle", self.animation_phrase_text),
            "hands": 2 if cur_step.get("bimanual") else 1,
            "current_step": {
                k: v for k, v in cur_step.items()
                if k not in ("primary_pose", "secondary_pose")
            },
        }
        return {
            "sign_submode": self.sign_submode,
            "active_tokens": self.active_tokens,
            "current_sentence": self.current_sentence,
            "raw_gloss_sentence": self.raw_gloss_sentence,
            "token_count": len(self.active_tokens),
            "chat_history": self.chat_history[-15:],
            "catalog": CONVERSATIONAL_SIGNS_CATALOG,
            "alphabet_catalog": LSC_ALPHABET_CATALOG,
            "hand_animator": anim_payload,
            "hand_animation": anim_payload,
            "hand_animation_phrase": self.animation_phrase_text,
        }
