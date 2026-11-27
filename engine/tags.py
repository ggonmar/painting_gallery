"""
Painting tags: period (época) and theme (temática), from a controlled vocabulary so the same concept
is always written the same way ("religión", never "Religioso"/"religion"). The format tag
(horizontal/vertical/cuadrado) is not stored here: it is the `orientation` column, computed from the image.

Rules: 1 format + at least 1 period + at least 1 theme, 6 tags at most in total.
"""

import json
import unicodedata
from pathlib import Path
from typing import Iterable, List

# Shared with the PHP API (api/painting.php) so the web editor offers exactly the same tags
VOCABULARY = json.loads((Path(__file__).parent / 'tags_vocabulary.json').read_text(encoding='utf-8'))
PERIODS = VOCABULARY['periods']
THEMES = VOCABULARY['themes']
MAX_PERIODS = VOCABULARY['max_periods']
MAX_TAGS = VOCABULARY['max_tags']  # including the format tag

# Frequent variants the AI may answer with -> canonical tag
SYNONYMS = {
    'paisaje': 'paisajista', 'paisajismo': 'paisajista', 'marina': 'mar', 'marino': 'mar', 'religioso': 'religión',
    'religiosa': 'religión', 'religion': 'religión', 'sacro': 'religión', 'mitologico': 'mitología',
    'mitologica': 'mitología', 'historia': 'histórico', 'historica': 'histórico', 'alegorico': 'alegoría',
    'alegorica': 'alegoría', 'naturaleza muerta': 'bodegón', 'escena de genero': 'costumbrista',
    'costumbrismo': 'costumbrista', 'noche': 'nocturno', 'guerra': 'bélico', 'batalla': 'bélico',
    'flor': 'flores', 'animal': 'animales', 'oscuro': 'sombrío', 'melancolico': 'sombrío', 'sueño': 'onírico',
    'renacentista': 'renacimiento', 'gotico': 'gótico', 'barroca': 'barroco', 'rococo': 'rococó',
    'neoclasico': 'neoclasicismo', 'neoclasica': 'neoclasicismo', 'romantico': 'romanticismo',
    'romantica': 'romanticismo', 'realista': 'realismo', 'impresionista': 'impresionismo',
    'postimpresionista': 'postimpresionismo', 'posimpresionismo': 'postimpresionismo',
    'simbolista': 'simbolismo', 'modernista': 'modernismo', 'expresionista': 'expresionismo',
    'cubista': 'cubismo', 'surrealista': 'surrealismo', 'arte moderno': 'moderno', 'modernidad': 'moderno',
    'arte contemporaneo': 'contemporáneo', 'contemporaneo': 'contemporáneo', 'edad media': 'medieval',
}


def _key(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text).strip().lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


_LOOKUP = {}
for _tag in PERIODS + THEMES:
    _LOOKUP[_key(_tag)] = _tag
for _variant, _tag in SYNONYMS.items():
    _LOOKUP.setdefault(_key(_variant), _tag)


def _normalize(values, allowed: List[str]) -> List[str]:
    if isinstance(values, str):
        values = [v for v in values.replace(';', ',').split(',')]
    result = []
    for value in values or []:
        tag = _LOOKUP.get(_key(value))
        if tag in allowed and tag not in result:
            result.append(tag)
    return result


def normalize_tags(periods: Iterable, themes: Iterable):
    """Map the AI answer to the vocabulary and apply the limits. Returns (periods, themes)."""
    periods = _normalize(periods, PERIODS)[:MAX_PERIODS]
    themes = _normalize(themes, THEMES)[:MAX_TAGS - 1 - len(periods)]
    return periods, themes


def prompt_fields(language: str = 'es') -> str:
    """Extra JSON fields to request from the AI."""
    if language == 'es':
        return (
            f'  "periods": lista de 1 o 2 épocas/movimientos, elegidos SOLO de: {", ".join(PERIODS)},\n'
            f'  "themes": lista de 1 a 4 temáticas, elegidas SOLO de: {", ".join(THEMES)},\n'
        )
    return (
        f'  "periods": list of 1 or 2 periods/movements, ONLY from this Spanish list: {", ".join(PERIODS)},\n'
        f'  "themes": list of 1 to 4 themes, ONLY from this Spanish list: {", ".join(THEMES)},\n'
    )
