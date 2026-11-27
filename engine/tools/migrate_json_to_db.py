"""
One-off migration: import paintings/painting_library.json into data/cuadros.sqlite.
Must run on the NAS (SQLite over SMB is not safe):

    cd /share/CACHEDEV1_DATA/Web/cuadros/engine && .venv/bin/python tools/migrate_json_to_db.py

Keeps a copy of the original JSON as painting_library.pre-db-backup.json.
"""

import json
import shutil
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from config_manager import ConfigManager  # noqa: E402
from library_manager import LibraryManager  # noqa: E402

config = ConfigManager()
paintings_dir = config.get_path('library_path')
json_path = paintings_dir / config.get('library_file', 'painting_library.json')
db_path = config.get_path('database_path', '../data/cuadros.sqlite')

library = LibraryManager(db_path, paintings_dir=paintings_dir, export_path=json_path)
if library.paintings and '--force' not in sys.argv:
    sys.exit(f'La base de datos ya tiene {len(library.paintings)} cuadros. Usa --force para reimportar el JSON encima.')

data = json.loads(json_path.read_text(encoding='utf-8'))
backup = json_path.with_name(json_path.stem + '.pre-db-backup.json')
if not backup.exists():
    shutil.copy2(json_path, backup)

imported = []
for painting in data.get('paintings', []):
    descriptions = painting.get('descriptions') or {}
    painting['descriptions'] = {
        lang: entries if isinstance(entries, list) else [entries] for lang, entries in descriptions.items()
    }
    if painting.get('description') and not painting['descriptions']:
        lang = painting.get('language') or config.get('language', 'es')
        painting['descriptions'] = {lang: [{'description': painting.pop('description'), 'language': lang}]}
    imported.append(painting)

existing = {p['id']: i for i, p in enumerate(library.paintings)}
for painting in imported:
    if painting.get('id') in existing:
        library.paintings[existing[painting['id']]] = painting
    else:
        library.paintings.append(painting)
library.save()

# seen/favorites were created before the paintings table: rebuild them with foreign keys to paintings
conn = library.conn
conn.execute('PRAGMA foreign_keys = OFF')
schema = (ENGINE_DIR / 'schema.sql').read_text(encoding='utf-8')
for table in ('seen', 'favorites'):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
    if 'REFERENCES paintings' in sql:
        continue
    with conn:
        conn.execute(f'ALTER TABLE {table} RENAME TO {table}_old')
        conn.executescript(schema)
        conn.execute(
            f'INSERT INTO {table} (user_id, painting_id, created_at) '
            f'SELECT user_id, painting_id, created_at FROM {table}_old WHERE painting_id IN (SELECT id FROM paintings)'
        )
        conn.execute(f'DROP TABLE {table}_old')
    print(f'Tabla {table} reconstruida con claves foráneas')
conn.execute('PRAGMA foreign_keys = ON')

problems = conn.execute('PRAGMA foreign_key_check').fetchall()
counts = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('paintings', 'descriptions', 'users', 'seen', 'favorites')}
print('Importados:', counts)
if problems:
    sys.exit(f'Problemas de integridad: {problems}')
