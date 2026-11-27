#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re

# Read the file
with open('L:/painting_renamer/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix remaining corrupted characters
replacements = [
    (r'Ã¢Å¡â„¢Ã¯Â¸Â', '⚙️'),  # Settings icon before "Avanzado"
    (r'Ã¢â€"Â¼', '▼'),  # Triangle for collapse
    (r'Ã°Å¸â€"Â¼Ã¯Â¸Â OrientaciÃƒÂ³n', '🖼️ Orientación'),  # Frame icon + Orientación
    (r'Ã°Å¸â€"Â¼Ã¯Â¸Â', '🖼️'),  # Frame icon alone
    (r'Ã°Å¸â€', '🔍'),  # Search icon
    (r'Ã°Å¸â€˜Â', '🎯'),  # Target icon
    (r'Ã°Å¸â€Æ', '🔽'),  # Down arrow
    (r'Ã°Å¸Å½Â¨', '🎨'),  # Art palette
    (r'Ã°Å¸â€œâ€¦', '📅'),  # Calendar
    (r'Ã°Å¸â€œÂ', '🔄'),  # Refresh icon
    (r'Ã°Å¸â€œÅ\s*', '📊 '),  # Chart icon
    (r'Ã°Å¸â€â€ž', '🗑️'),  # Trash icon
    (r'Ã¢â€žÂ¹Ã¯Â¸Â', 'ℹ️'),  # Info icon
    (r'Ã¢Å"â€œ', '✓'),  # Checkmark
    (r'Ã¢Å"â€Ã¯Â¸Â', '✔️'),  # Checkmark with variation selector
    (r'Ã¢â‚¬Â¢', '•'),  # Bullet point
    (r'tÃƒÂ­tulo', 'título'),
    (r'aÃƒÂ±o', 'año'),
    (r'AÃƒÂ±o', 'Año'),
    (r'ubicaciÃƒÂ³n', 'ubicación'),
    (r'OrientaciÃƒÂ³n', 'Orientación'),
    (r'descripciÃƒÂ³n', 'descripción'),
    (r'colecciÃƒÂ³n', 'colección'),
    (r'InformaciÃƒÂ³n', 'Información'),
    (r'TÃƒÂ­tulo', 'Título'),
    (r'mÃƒÂ¡s', 'más'),
    (r'mÃƒÂ¡xima', 'máxima'),
    (r'Ãƒâ€"', '×'),
]

for pattern, replacement in replacements:
    content = re.sub(pattern, replacement, content)

# Write back
with open('L:/painting_renamer/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed all remaining characters!")
