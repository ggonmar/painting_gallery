"""
Housekeeping after a painting is edited from the web (api/painting.php):
geocode any location that is not cached yet (for the map) and regenerate the painting_library.json copy.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_manager import ConfigManager  # noqa: E402
from geocoder import geocode_missing  # noqa: E402
from library_manager import LibraryManager  # noqa: E402

config = ConfigManager()
paintings_dir = config.get_path('library_path')
library = LibraryManager(
    config.get_path('database_path', '../data/cuadros.sqlite'),
    paintings_dir=paintings_dir,
    export_path=paintings_dir / config.get('library_file', 'painting_library.json'),
)
geocode_missing(library.conn, {p.get('location') for p in library.paintings}, retry_not_found='--retry-not-found' in sys.argv)
library.export_json()
