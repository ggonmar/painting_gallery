"""
Geocode every painting location that is not cached yet (for the gallery map). Runs on the NAS:

    cd /share/CACHEDEV1_DATA/Web/cuadros/engine && .venv/bin/python tools/geocode_locations.py [--retry-not-found | --all]

New paintings are geocoded automatically when the engine saves them; this is for the backlog,
or to retry the ones Nominatim did not find (e.g. after correcting a location).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_manager import ConfigManager  # noqa: E402
from geocoder import geocode_missing  # noqa: E402
from library_manager import connect  # noqa: E402

config = ConfigManager()
conn = connect(config.get_path('database_path', '../data/cuadros.sqlite'))
if '--all' in sys.argv:
    with conn:
        conn.execute('DELETE FROM locations')
names = [row[0] for row in conn.execute('SELECT DISTINCT location FROM paintings')]
looked_up = geocode_missing(conn, names, retry_not_found='--retry-not-found' in sys.argv)
summary = dict(conn.execute('SELECT status, COUNT(*) FROM locations GROUP BY status').fetchall())
print(f'Consultadas: {looked_up}. Estado de la caché: {summary}')
