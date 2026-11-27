import json

with open(r'W:\cuadros\painting_library.json', encoding='utf-8') as f:
    data = json.load(f)

painting = [p for p in data['paintings'] if 'Gótico Americano' in p.get('title', '')][0]
descriptions = painting['descriptions']['es']

print(f'Found {len(descriptions)} descriptions for American Gothic')
print('\nTimestamps:')
for i, desc in enumerate(descriptions, 1):
    print(f'{i}. {desc.get("generated_at", "No timestamp")} - {desc.get("description", "")[:80]}...')
