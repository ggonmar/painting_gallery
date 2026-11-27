"""
Register as "pending review" every image in paintings/ that has no entry in the database
(e.g. uploads whose processing failed before pending entries existed). Runs on the NAS:

    cd /share/CACHEDEV1_DATA/Web/cuadros/engine && .venv/bin/python tools/register_orphans.py
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_manager import ConfigManager  # noqa: E402
from image_utils import analyze_image, get_image_dimensions  # noqa: E402
from library_manager import LibraryManager  # noqa: E402
from painting_renamer import IMAGE_EXTENSIONS  # noqa: E402

config = ConfigManager()
paintings_dir = config.get_path('library_path')
library = LibraryManager(
    config.get_path('database_path', '../data/cuadros.sqlite'),
    paintings_dir=paintings_dir,
    export_path=paintings_dir / config.get('library_file', 'painting_library.json'),
)
known = {p.get('file_path') for p in library.paintings}
now = datetime.now(timezone.utc).isoformat()
added = 0
for file in sorted(paintings_dir.iterdir()):
    if not file.is_file() or file.suffix.lower() not in IMAGE_EXTENSIONS or file.name in known:
        continue
    width, height = get_image_dimensions(file)
    painting = {
        'id': uuid.uuid4().hex[:12],
        'title': file.stem,
        'file_path': file.name,
        'file_size': file.stat().st_size,
        'file_width': width,
        'file_height': height,
        'orientation': analyze_image(file),
        'status': 'pending',
        'confirmed': False,
        'added_to_library': now,
        'updated_on_library': now,
        'descriptions': {},
    }
    library.paintings.append(painting)
    print(f'  + pendiente: {file.name}')
    added += 1
if added:
    library.save()
print(f'Registradas {added} imágenes huérfanas como pendientes de revisión')
