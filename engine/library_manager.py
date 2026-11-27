"""
Library Manager Module
Manages the painting library stored in the gallery SQLite database (data/cuadros.sqlite).
painting_library.json is only a human-readable export, regenerated after every save.

The rest of the engine works with painting dicts (same shape as the old JSON entries);
load() builds them from the database and save() writes back only the ones that changed.
"""

import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from collections import Counter

from geocoder import geocode_missing

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    print("Warning: rapidfuzz not available. Location normalization will be disabled.")
    print("Install with: pip install rapidfuzz")

SCHEMA_FILE = Path(__file__).parent / 'schema.sql'

# Painting fields stored in their own column; anything else goes to the JSON "extra" column
COLUMNS = [
    'id', 'title', 'original_title', 'artist', 'year', 'location', 'orientation', 'confidence_score',
    'confirmed', 'info_data_source', 'file_path', 'file_size', 'file_width', 'file_height',
    'added_to_library', 'updated_on_library', 'status',
]
TAG_KINDS = {'periods': 'period', 'themes': 'theme'}  # painting dict key -> painting_tags.kind
DESCRIPTION_FIELDS = ['description', 'language', 'description_style', 'generated_at', 'comment_creator', 'max_length']


def ensure_runs_on_nas():
    """SQLite locking is not reliable over SMB, so the database must only be written on the NAS itself."""
    if os.name == 'nt':
        sys.exit(
            "ERROR: la biblioteca vive en una base de datos SQLite y no se puede escribir a través de la red (SMB).\n"
            "Ejecuta el motor en el NAS: subiendo cuadros desde la web o por SSH:\n"
            "  ssh ggonmar@192.168.1.2\n"
            "  cd /share/CACHEDEV1_DATA/Web/cuadros/engine && .venv/bin/python painting_renamer.py [opciones]"
        )


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the gallery database and make sure the schema exists."""
    ensure_runs_on_nas()
    os.umask(0o007)  # DB and journal stay writable for both the web user and ggonmar (SSH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        if db_path.stat().st_uid == os.getuid() and db_path.stat().st_mode & 0o660 != 0o660:
            os.chmod(db_path, 0o660)
    except OSError:
        pass
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 30000')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(paintings)')}
    if columns and 'status' not in columns:
        conn.execute("ALTER TABLE paintings ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'")
    conn.executescript(SCHEMA_FILE.read_text(encoding='utf-8'))
    return conn


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class LibraryManager:
    """Manages the painting library stored in SQLite."""
    
    def __init__(self, db_path: Path, paintings_dir: Path, export_path: Optional[Path] = None):
        """
        Args:
            db_path: Path to the SQLite database (data/cuadros.sqlite)
            paintings_dir: Folder with the images; file_path values are relative to it
            export_path: Optional JSON file regenerated after each save (read-only copy for humans)
        """
        self.db_path = Path(db_path)
        self.paintings_dir = Path(paintings_dir)
        self.export_path = Path(export_path) if export_path else None
        self.conn = connect(self.db_path)
        self.paintings: List[Dict] = []
        self._snapshots: Dict[str, str] = {}
        self.load()
    
    @staticmethod
    def _serialize(painting: Dict) -> str:
        return json.dumps(painting, sort_keys=True, ensure_ascii=False, default=str)

    def load(self):
        """Load all paintings (with their descriptions, newest first) from the database."""
        descriptions: Dict[str, Dict[str, List[Dict]]] = {}
        for row in self.conn.execute(
            'SELECT * FROM descriptions ORDER BY painting_id, language, generated_at DESC, id ASC'
        ):
            entry = {field: row[field] for field in DESCRIPTION_FIELDS}
            descriptions.setdefault(row['painting_id'], {}).setdefault(row['language'], []).append(entry)

        tags: Dict[str, Dict[str, List[str]]] = {}
        for row in self.conn.execute('SELECT painting_id, kind, tag FROM painting_tags ORDER BY painting_id, kind, position'):
            tags.setdefault(row['painting_id'], {}).setdefault(row['kind'], []).append(row['tag'])

        self.paintings = []
        for row in self.conn.execute('SELECT * FROM paintings ORDER BY added_to_library, id'):
            painting = {column: row[column] for column in COLUMNS}
            painting['confirmed'] = bool(painting['confirmed'])
            if row['extra']:
                painting.update(json.loads(row['extra']))
            for key, kind in TAG_KINDS.items():
                painting[key] = tags.get(row['id'], {}).get(kind, [])
            painting['descriptions'] = descriptions.get(row['id'], {})
            self.paintings.append(painting)

        self._snapshots = {p['id']: self._serialize(p) for p in self.paintings}
        print(f"Loaded library with {len(self.paintings)} painting(s) from {self.db_path.name}")

    def relative_path(self, file_path) -> str:
        """
        Return file_path relative to the paintings folder, using '/' separators so the value
        is valid on the NAS and as a URL. Falls back to the absolute path for files outside it.
        """
        path = Path(file_path)
        try:
            return path.resolve().relative_to(self.paintings_dir.resolve()).as_posix()
        except ValueError:
            return str(path)

    def save(self):
        """Write new/changed paintings and their descriptions to the database, then refresh the JSON export."""
        changed = 0
        changed_locations = set()
        try:
            with self.conn:
                for painting in self.paintings:
                    if not painting.get('id'):
                        painting['id'] = uuid.uuid4().hex[:12]
                    serialized = self._serialize(painting)
                    if self._snapshots.get(painting['id']) == serialized:
                        continue
                    self._write_painting(painting)
                    self._snapshots[painting['id']] = serialized
                    changed_locations.add(painting.get('location'))
                    changed += 1
        except Exception as e:
            print(f"  ⚠ Error saving library: {e}")
            raise
        if changed:
            self.export_json()
        if changed_locations:
            try:
                geocode_missing(self.conn, changed_locations)
            except Exception as e:  # the map is a nice-to-have: never break saving because of it
                print(f"  ⚠ Geocoding skipped: {e}")

    def _write_painting(self, painting: Dict):
        values = {column: painting.get(column) for column in COLUMNS}
        values['confirmed'] = 1 if painting.get('confirmed') else 0
        values['status'] = painting.get('status') or 'ready'
        if values['year'] is not None:
            values['year'] = str(values['year'])
        extra = {k: v for k, v in painting.items() if k not in COLUMNS and k != 'descriptions' and k not in TAG_KINDS}
        values['extra'] = json.dumps(extra, ensure_ascii=False, default=str) if extra else None

        columns = list(values)
        updates = ', '.join(f'{c} = excluded.{c}' for c in columns if c != 'id')
        self.conn.execute(
            f"INSERT INTO paintings ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [values[c] for c in columns],
        )

        if any(key in painting for key in TAG_KINDS):
            self.conn.execute('DELETE FROM painting_tags WHERE painting_id = ?', (painting['id'],))
            for key, kind in TAG_KINDS.items():
                for position, tag in enumerate(painting.get(key) or []):
                    self.conn.execute(
                        'INSERT OR IGNORE INTO painting_tags (painting_id, kind, tag, position) VALUES (?, ?, ?, ?)',
                        (painting['id'], kind, tag, position),
                    )

        for language, entries in (painting.get('descriptions') or {}).items():
            for entry in entries if isinstance(entries, list) else [entries]:
                if not entry.get('description'):
                    continue
                self.conn.execute(
                    'INSERT OR IGNORE INTO descriptions '
                    '(painting_id, language, description, description_style, generated_at, comment_creator, max_length) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (painting['id'], entry.get('language') or language, entry['description'],
                     entry.get('description_style'), entry.get('generated_at'),
                     entry.get('comment_creator'), _to_int(entry.get('max_length'))),
                )

    def export_json(self):
        """Regenerate the human-readable JSON copy (nothing reads it; the database is the source of truth)."""
        if not self.export_path:
            return
        data = {
            'metadata': {
                'note': 'Copia generada automáticamente desde data/cuadros.sqlite. No editar: los cambios se pierden.',
                'last_updated': datetime.now().isoformat(),
                'total_paintings': len(self.paintings),
            },
            'paintings': self.paintings,
        }
        tmp = self.export_path.with_suffix('.json.tmp')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, self.export_path)
        except Exception as e:
            print(f"  ⚠ Could not export {self.export_path.name}: {e}")

    def normalize_location(self, new_location: str, threshold: float = 85.0) -> Tuple[str, bool]:
        """
        Normalize a location string to match existing library locations.
        Uses fuzzy matching to find similar locations and returns the best match.
        
        Args:
            new_location: The location string to normalize
            threshold: Minimum similarity score (0-100) to consider a match
            
        Returns:
            Tuple of (normalized_location, was_normalized)
        """
        if not RAPIDFUZZ_AVAILABLE or not new_location or not new_location.strip():
            return new_location, False
        
        # Get all existing unique locations (excluding None/empty)
        existing_locations = [
            p.get('location') 
            for p in self.paintings 
            if p.get('location') and p.get('location').strip()
        ]
        
        if not existing_locations:
            return new_location, False
        
        # Find the best match using fuzzy matching
        best_match = None
        best_score = 0.0
        
        for existing_loc in existing_locations:
            # Use token_sort_ratio for better matching (handles word order differences)
            score = fuzz.token_sort_ratio(new_location.lower(), existing_loc.lower())
            
            if score > best_score:
                best_score = score
                best_match = existing_loc
        
        # If best match is above threshold, use it
        if best_score >= threshold and best_match:
            if best_match != new_location:
                print(f"\nLocation normalized:")
                print(f"  From: '{new_location}'")
                print(f"  To:   '{best_match}'")
                print(f"  (Similarity: {best_score:.1f}%)")
                return best_match, True
        
        return new_location, False
    
    def add_painting(self, painting_data: Dict):
        """
        Add a painting to the library or update if it already exists.
        
        Args:
            painting_data: Dictionary containing painting metadata
        """
        # Normalize location before adding/updating
        if painting_data.get('location'):
            normalized_location, was_normalized = self.normalize_location(painting_data['location'])
            painting_data['location'] = normalized_location
        
        # Check if painting already exists (by file_path first, then by title + artist)
        existing_idx = None
        new_file_path = painting_data.get('file_path')
        
        # First: check by file_path (same file = same entry)
        if new_file_path:
            for idx, p in enumerate(self.paintings):
                if p.get('file_path') == new_file_path:
                    existing_idx = idx
                    break
        
        # Fallback: check by title + artist (for retrocompatibility with old entries)
        if existing_idx is None:
            for idx, p in enumerate(self.paintings):
                if (p.get('title') == painting_data.get('title') and
                    p.get('artist') == painting_data.get('artist')):
                    existing_idx = idx
                    break
        
        if existing_idx is not None:
            # Update existing entry
            existing_painting = self.paintings[existing_idx]
            painting_data['id'] = existing_painting.get('id') or uuid.uuid4().hex[:12]
            for key in TAG_KINDS:
                if not painting_data.get(key) and existing_painting.get(key):
                    painting_data[key] = existing_painting[key]
            painting_data['updated_on_library'] = datetime.now().isoformat()
            # Preserve added_to_library from existing entry
            painting_data['added_to_library'] = existing_painting.get('added_to_library', datetime.now().isoformat())
            # Preserve confirmed field from existing entry
            is_confirmed = existing_painting.get('confirmed', False)
            painting_data['confirmed'] = is_confirmed
            # Handle file_path: preserve old path if confirmed=True, otherwise use new path
            if is_confirmed:
                # Confirmed entry - keep original file_path
                painting_data['file_path'] = existing_painting.get('file_path', painting_data.get('file_path'))
            # else: confirmed=False, keep new file_path from painting_data (already set)
            
            # Merge descriptions: for each language, append new descriptions to array and sort by date
            existing_descriptions = existing_painting.get('descriptions', {})
            new_descriptions = painting_data.get('descriptions', {})
            merged_descriptions = dict(existing_descriptions)  # Copy existing
            
            for lang, new_desc_list in new_descriptions.items():
                if lang in merged_descriptions:
                    # Language exists - append new descriptions to array
                    existing_desc_list = merged_descriptions[lang]
                    # Ensure existing is a list (migration from old format)
                    if not isinstance(existing_desc_list, list):
                        existing_desc_list = [existing_desc_list]
                    # Ensure new is a list
                    if not isinstance(new_desc_list, list):
                        new_desc_list = [new_desc_list]
                    # Append new descriptions
                    combined = existing_desc_list + new_desc_list
                    # Remove duplicates: if all fields are identical, keep only one
                    deduplicated = []
                    seen = set()
                    for desc in combined:
                        # Create a hashable representation of the description
                        desc_key = (
                            desc.get('description', ''),
                            desc.get('generated_at', ''),
                            desc.get('comment_creator', ''),
                            desc.get('description_style', ''),
                            desc.get('max_length', '')
                        )
                        if desc_key not in seen:
                            seen.add(desc_key)
                            deduplicated.append(desc)
                    # Sort by generated_at descending (newest first)
                    deduplicated.sort(key=lambda x: x.get('generated_at', ''), reverse=True)
                    merged_descriptions[lang] = deduplicated
                else:
                    # New language - ensure it's a list
                    merged_descriptions[lang] = new_desc_list if isinstance(new_desc_list, list) else [new_desc_list]
            
            painting_data['descriptions'] = merged_descriptions
            self.paintings[existing_idx] = painting_data
        else:
            # Add new entry
            painting_data['id'] = uuid.uuid4().hex[:12]
            painting_data['added_to_library'] = datetime.now().isoformat()
            painting_data['updated_on_library'] = datetime.now().isoformat()
            self.paintings.append(painting_data)
    
    def update_painting_path(self, painting_data: Dict, new_path: str):
        """
        Update the file_path for an existing painting in the library.
        
        Args:
            painting_data: Dictionary containing painting metadata
            new_path: The new file path after renaming
        """
        # Find the painting in the library (by id; title + artist only for entries without id)
        title = painting_data.get('title')
        artist = painting_data.get('artist')
        painting_id = painting_data.get('id')
        
        for painting in self.paintings:
            if (painting.get('id') == painting_id) if painting_id else (painting.get('title') == title and painting.get('artist') == artist):
                painting['file_path'] = self.relative_path(new_path)
                break
    
    def get_painting_by_title_artist(self, title: str, artist: str) -> Dict:
        """
        Get a painting by its title and artist.
        
        Args:
            title: Painting title
            artist: Artist name
            
        Returns:
            Painting dictionary or None if not found
        """
        for painting in self.paintings:
            if painting.get('title') == title and painting.get('artist') == artist:
                return painting
        return None
    
    def get_paintings_by_artist(self, artist: str) -> List[Dict]:
        """
        Get all paintings by a specific artist.
        
        Args:
            artist: Artist name to search for
            
        Returns:
            List of painting dictionaries
        """
        artist_lower = artist.lower().strip()
        results = []
        for painting in self.paintings:
            if painting.get('artist', '').lower().strip() == artist_lower:
                results.append(painting)
        return results
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about the library.
        
        Returns:
            Dictionary with library statistics
        """
        stats = {
            'total_paintings': len(self.paintings),
            'artists': len(set(p.get('artist', 'Unknown') for p in self.paintings)),
            'orientations': {},
            'decades': {},
            'duplicates': 0
        }
        
        # Count by orientation
        for painting in self.paintings:
            orientation = painting.get('orientation', 'unknown')
            stats['orientations'][orientation] = stats['orientations'].get(orientation, 0) + 1
            
            # Count duplicates
            if painting.get('is_duplicate', False):
                stats['duplicates'] += 1
            
            # Count by decade
            year = painting.get('year', '')
            if year and year != 'Unknown':
                try:
                    year_num = int(str(year).split('-')[0])  # Handle ranges
                    decade = f"{(year_num // 10) * 10}s"
                    stats['decades'][decade] = stats['decades'].get(decade, 0) + 1
                except (ValueError, AttributeError):
                    pass
        
        return stats
