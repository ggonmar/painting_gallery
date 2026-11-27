"""
Ask the configured processing AI (Gemini or Ollama, see data_source / ai_settings.json) ONLY for the
period/theme tags of one painting: it receives the image plus title, artist and year.
Nothing is saved: the result is written to --result-json for the web editor, which shows the suggestion
so the user can review it and save. Runs on the NAS:

    .venv/bin/python tools/suggest_tags.py <painting_id> [--result-json FILE]
"""

import argparse
import json
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from config_manager import ConfigManager  # noqa: E402
from gemini_lookup import DailyLimitReached, lookup_tags_gemini  # noqa: E402
from library_manager import connect  # noqa: E402
from painting_lookup import lookup_tags_ollama  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('painting_id')
parser.add_argument('--result-json')
args = parser.parse_args()


def finish(status: str, **extra):
    if args.result_json:
        with open(args.result_json, 'w', encoding='utf-8') as f:
            json.dump({'results': [{'status': status, 'id': args.painting_id, **extra}]}, f, ensure_ascii=False)
    sys.exit(0 if status == 'processed' else 1)


config = ConfigManager()
conn = connect(config.get_path('database_path', '../data/cuadros.sqlite'))
row = conn.execute('SELECT * FROM paintings WHERE id = ?', (args.painting_id,)).fetchone()
if not row:
    print(f'Cuadro no encontrado: {args.painting_id}')
    finish('failed')
painting = dict(row)
image = config.get_path('library_path') / (painting.get('file_path') or '')

provider = [s.strip().lower() for s in config.get('data_source', 'gemini').split(',') if s.strip()][0]
print(f"Pidiendo tags para «{painting.get('title')}» de {painting.get('artist')} ({painting.get('year')})")
if provider == 'ollama':
    model = config.get('ollama_model', 'llama3.2')
    print(f'  IA: ollama:{model}')
    result = lookup_tags_ollama(painting, image, config.get('ollama_host'), config.get('ollama_api_key'), model)
else:
    model = config.get('gemini_model', 'gemini-2.5-flash')
    print(f'  IA: gemini:{model}')
    try:
        result = lookup_tags_gemini(painting, image, config.get('gemini_api_key'), model,
                                    config.get('gemini_requests_per_minute', 15))
    except DailyLimitReached as e:
        print(f'  ⚠ Gemini quota exceeded (429): {e}')
        finish('failed')

if not result or not (result[0] or result[1]):
    print('  ⚠ La IA no devolvió tags válidos')
    finish('failed')
periods, themes = result
print(f"  ✓ {', '.join(periods) or '—'} · {', '.join(themes) or '—'}")
finish('processed', periods=periods, themes=themes, provider=f'{provider}:{model}')
