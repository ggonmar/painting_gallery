"""
Fill in the period/theme tags of paintings that do not have them yet, asking Gemini ONLY for the tags
(title, artist, descriptions... are not touched). Runs on the NAS:

    cd /share/CACHEDEV1_DATA/Web/cuadros/engine && .venv/bin/python tools/tag_paintings.py [--all] [--limit N]

--all      re-tag every painting (replaces existing tags)
--limit N  stop after N paintings

Writes each painting as soon as it is tagged (no long lock: uploads keep working meanwhile).
"""

import argparse
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from config_manager import ConfigManager  # noqa: E402
from gemini_lookup import DailyLimitReached, lookup_tags_gemini  # noqa: E402
from library_manager import LibraryManager  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('--all', action='store_true')
parser.add_argument('--limit', type=int, default=0)
args = parser.parse_args()

config = ConfigManager()
paintings_dir = config.get_path('library_path')
library = LibraryManager(
    config.get_path('database_path', '../data/cuadros.sqlite'),
    paintings_dir=paintings_dir,
    export_path=paintings_dir / config.get('library_file', 'painting_library.json'),
)
conn = library.conn
api_key = config.get('gemini_api_key')
model = config.get('gemini_model', 'gemini-2.5-flash')
per_minute = config.get('gemini_requests_per_minute', 15)

tagged_ids = {row[0] for row in conn.execute('SELECT DISTINCT painting_id FROM painting_tags')}
pending = [p for p in library.paintings if args.all or p['id'] not in tagged_ids]
if args.limit:
    pending = pending[:args.limit]
print(f'Cuadros a etiquetar: {len(pending)} (máx. {per_minute} peticiones/min)')

done = failed = 0
for number, painting in enumerate(pending, 1):
    print(f"[{number}/{len(pending)}] {painting.get('title')} — {painting.get('artist')}")
    try:
        result = lookup_tags_gemini(painting, paintings_dir / (painting.get('file_path') or ''), api_key, model, per_minute)
    except DailyLimitReached as e:
        print(f'  ⛔ Cuota de Gemini agotada, se para aquí (vuelve a ejecutarlo cuando se reinicie): {e}')
        break
    if not result or not result[0] or not result[1]:
        print(f'  ⚠ Sin tags válidos: {result}')
        failed += 1
        continue
    periods, themes = result
    with conn:
        # Re-check: the painting may have been tagged/deleted from the web meanwhile
        exists = conn.execute('SELECT 1 FROM paintings WHERE id = ?', (painting['id'],)).fetchone()
        has_tags = conn.execute('SELECT 1 FROM painting_tags WHERE painting_id = ?', (painting['id'],)).fetchone()
        if not exists or (has_tags and not args.all):
            print('  (omitido: borrado o etiquetado mientras tanto)')
            continue
        conn.execute('DELETE FROM painting_tags WHERE painting_id = ?', (painting['id'],))
        for kind, values in (('period', periods), ('theme', themes)):
            for position, tag in enumerate(values):
                conn.execute('INSERT INTO painting_tags (painting_id, kind, tag, position) VALUES (?, ?, ?, ?)',
                             (painting['id'], kind, tag, position))
    print(f"  ✓ {', '.join(periods)} · {', '.join(themes)}")
    done += 1

LibraryManager(library.db_path, paintings_dir=paintings_dir, export_path=library.export_path).export_json()
print(f'Terminado: {done} etiquetados, {failed} sin resultado')
