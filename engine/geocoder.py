"""
Geocoding of painting locations (museum names) with OpenStreetMap Nominatim.
Results are cached in the `locations` table, so each distinct location is looked up only once.
Nominatim usage policy: max 1 request/second, identifying User-Agent, cache results.
"""

import re
import sqlite3
import time
from typing import Iterable, List, Optional, Tuple

import requests

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'cuadros-gallery/1.0 (personal painting gallery on a home NAS)'
MIN_INTERVAL = 1.1

# Values the engine uses for "no location"; not worth geocoding
NOT_A_PLACE = re.compile(
    r'^\s*(unknown|desconocid[oa]|n/?a|none|private collection|colecci[oó]n privada|'
    r'colecci[oó]n particular|various|varios|multiple)\s*\.?\s*$',
    re.IGNORECASE,
)

_last_request = 0.0

GENERIC_WORDS = re.compile(
    r'\b(the|of|de|del|la|le|des|degli|national|nacional|art|arte|arts|gallery|galleria|galería|galeria|'
    r'museum|museo|musée|museu|collection|colección)\b',
    re.IGNORECASE,
)
CULTURE_CATEGORIES = {'tourism', 'historic', 'building'}
CULTURE_AMENITIES = {'art_gallery', 'arts_centre', 'place_of_worship', 'library', 'university', 'townhall'}
CITY_TYPES = {'city', 'town', 'village', 'administrative', 'municipality'}


def _is_culture_place(result: dict) -> bool:
    category, kind = result.get('category'), result.get('type')
    if category in CULTURE_CATEGORIES:
        return kind not in {'hotel', 'hostel', 'guest_house', 'apartment', 'camp_site', 'information'}
    return category == 'amenity' and kind in CULTURE_AMENITIES


def _candidates(name: str) -> List[str]:
    """Progressively simpler queries: full text, without notes in parentheses, museum + city, museum alone,
    museum name without generic words ("Uffizi Gallery" -> "Uffizi")."""
    cleaned = re.sub(r'\s*\([^)]*\)', '', name).strip(' ,.')
    parts = [p.strip() for p in cleaned.split(',') if p.strip()]
    candidates = [name, cleaned]
    if len(parts) > 2:
        candidates.append(f'{parts[0]}, {parts[1]}')
    if parts:
        candidates.append(parts[0])
        core = re.sub(r'\s+', ' ', GENERIC_WORDS.sub(' ', parts[0])).strip(' -,')
        if core and core.lower() != parts[0].lower():
            candidates.append(core)
    seen = set()
    return [c for c in candidates if c and not (c in seen or seen.add(c))]


def _query(text: str) -> List[dict]:
    global _last_request
    wait = MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()
    response = requests.get(
        NOMINATIM_URL,
        params={'q': text, 'format': 'jsonv2', 'limit': 5},
        headers={'User-Agent': USER_AGENT, 'Accept-Language': 'es,en'},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def geocode(name: str) -> Tuple[str, Optional[float], Optional[float], Optional[str]]:
    """Return (status, lat, lon, display_name). Raises requests exceptions on network errors.
    Only museum-like places are accepted (a random street with a similar name is worse than nothing);
    as a last resort the city part of the location ("..., Florence") is used."""
    if not name or NOT_A_PLACE.match(name):
        return 'not_a_place', None, None, None
    for candidate in _candidates(name):
        for result in _query(candidate):
            if _is_culture_place(result):
                return 'ok', float(result['lat']), float(result['lon']), result.get('display_name')
    parts = [p.strip() for p in re.sub(r'\s*\([^)]*\)', '', name).split(',') if p.strip()]
    if len(parts) > 1:
        for result in _query(parts[-1]):
            if result.get('type') in CITY_TYPES:
                return 'ok', float(result['lat']), float(result['lon']), result.get('display_name')
    return 'not_found', None, None, None


def geocode_missing(conn: sqlite3.Connection, names: Iterable[str], retry_not_found: bool = False) -> int:
    """Geocode the given location names that are not cached yet. Returns how many were looked up."""
    names = sorted({n for n in names if n and n.strip()})
    if retry_not_found:
        cached = {r[0] for r in conn.execute("SELECT name FROM locations WHERE status != 'not_found'")}
    else:
        cached = {r[0] for r in conn.execute('SELECT name FROM locations')}
    pending = [n for n in names if n not in cached]
    for name in pending:
        try:
            status, lat, lon, display = geocode(name)
        except requests.RequestException as e:
            print(f"  ⚠ Geocoding failed for '{name}' (will retry next time): {e}")
            continue
        with conn:
            conn.execute(
                'INSERT INTO locations (name, lat, lon, display_name, status, geocoded_at) '
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                'ON CONFLICT(name) DO UPDATE SET lat = excluded.lat, lon = excluded.lon, '
                'display_name = excluded.display_name, status = excluded.status, geocoded_at = excluded.geocoded_at',
                (name, lat, lon, display, status),
            )
        icon = {'ok': '📍', 'not_found': '❓', 'not_a_place': '·'}[status]
        print(f"  {icon} {name}" + (f" → {display}" if display else f" ({status})"))
    return len(pending)
