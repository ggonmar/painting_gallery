#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Read the HTML file
with open('L:/painting_renamer/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix all corrupted emojis and special characters
replacements = {
    r'Ã°Å¸â€œÂ': '\U0001F504',  # 🔄
    r'Ã°Å¸Å½Â¨': '\U0001F3A8',  # 🎨
    r'Ã°Å¸â€': '\U0001F50D',  # 🔍
    r'Ã°Å¸â€œâ€¦': '\U0001F4C5',  # 📅
    r'Ã°Å¸â€"Â¼Ã¯Â¸Â': '\U0001F5BC\uFE0F',  # 🖼️
    "Ã°Å¸â€�'": '\U0001F512',  # 🔒
    r'Ã°Å¸â€˜Â': '\U0001F3AF',  # 🎯
    "Ã°Å¸â€Æ'": '\U0001F53D',  # 🔽
    r'Ã°Å¸â€œÅ ': '\U0001F4CA',  # 📊
    r'GalerÃƒÂ­a': 'Galería',
    r'tÃƒÂ­tulo': 'título',
    r'aÃƒÂ±o': 'año',
    r'ubicaciÃƒÂ³n': 'ubicación',
    r'PerÃƒÂ­odo': 'Período',
    r'OrientaciÃƒÂ³n': 'Orientación',
    r'SÃƒÂ­': 'Sí',
    r'Ãƒâ€°poca': 'Época',
    r'mÃƒÂ¡s': 'más',
    r'TÃƒÂ­tulo': 'Título',
    r'InformaciÃƒÂ³n': 'Información',
    r'TÃƒÂ©cnica': 'Técnica',
    r'Ãƒâ€"': '×',
    r'TamaÃƒÂ±o': 'Tamaño',
    r'âœ"': '\u2713',  # ✓
}

for old, new in replacements.items():
    content = content.replace(old, new)

# Remove seen-live related lines
lines = content.split('\n')
filtered_lines = []
skip_next = 0

for i, line in enumerate(lines):
    # Skip seen-live related lines
    if any(pattern in line for pattern in ['saveSeenLiveStatus', 'getSeenLiveStatus', 'handleSeenLiveChange', 'seenLiveCheckbox', 'seen-live-container', 'seen-live-checkbox']):
        continue
    # Skip if this is part of a multi-line seen-live block
    if i > 0 and 'La he visto en vivo' in line:
        continue
    filtered_lines.append(line)

# Write fixed version
with open('L:/painting_renamer/index.html', 'w', encoding='utf-8') as f:
    f.write('\n'.join(filtered_lines))

print("Fixed successfully!")
print(f"Processed {len(lines)} lines")
print(f"Output {len(filtered_lines)} lines")
print(f"Removed {len(lines) - len(filtered_lines)} lines")
