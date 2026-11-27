"""
Ask one of the configured AIs for a NEW description of a painting and store it as the newest version
(previous descriptions are kept). Used by the web (api/painting.php); runs on the NAS:

    .venv/bin/python tools/generate_description.py <painting_id> <gemini|ollama> [--style "..."] [--result-json FILE]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from config_manager import ConfigManager  # noqa: E402
from gemini_lookup import generate_description_gemini  # noqa: E402
from library_lock import library_lock  # noqa: E402
from library_manager import LibraryManager  # noqa: E402
from painting_lookup import generate_description  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('painting_id')
parser.add_argument('provider', choices=['gemini', 'ollama'])
parser.add_argument('--style')
parser.add_argument('--max-length', type=int)
parser.add_argument('--result-json')
args = parser.parse_args()


def finish(status: str, **extra):
    if args.result_json:
        with open(args.result_json, 'w', encoding='utf-8') as f:
            json.dump({'results': [{'status': status, 'id': args.painting_id, **extra}]}, f, ensure_ascii=False)
    sys.exit(0 if status == 'processed' else 1)


config = ConfigManager()
language = config.get('language', 'es')
style = args.style or config.get('description_style', 'engaging and informative')
max_length = args.max_length or int(config.get('description_max_length', 1000))

with library_lock():
    paintings_dir = config.get_path('library_path')
    library = LibraryManager(
        config.get_path('database_path', '../data/cuadros.sqlite'),
        paintings_dir=paintings_dir,
        export_path=paintings_dir / config.get('library_file', 'painting_library.json'),
    )
    painting = next((p for p in library.paintings if p.get('id') == args.painting_id), None)
    if not painting:
        print(f'Cuadro no encontrado: {args.painting_id}')
        finish('failed')

    print(f"Nueva descripción para «{painting.get('title')}» de {painting.get('artist')} ({args.provider}, estilo: {style})")
    if args.provider == 'gemini':
        model = config.get('gemini_model', 'gemini-2.5-flash')
        creator = f'gemini:{model}'
        text = generate_description_gemini(
            painting, paintings_dir / painting.get('file_path', ''), config.get('gemini_api_key'),
            model, language, style, max_length,
        )
    else:
        creator = f"ollama:{config.get('ollama_model', 'llama3.2')}"
        text = generate_description(
            painting, config.get('ollama_host'), config.get('ollama_api_key'), language, style, max_length,
        )

    if not text or text.strip().lower().startswith('description not available'):
        print('No se obtuvo ninguna descripción')
        finish('failed')

    painting.setdefault('descriptions', {}).setdefault(language, []).insert(0, {
        'description': text.strip(),
        'language': language,
        'description_style': style,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'comment_creator': creator,
        'max_length': max_length,
    })
    library.save()
    print('Descripción guardada')
    finish('processed', title=painting.get('title'), artist=painting.get('artist'), year=painting.get('year'),
           file_path=painting.get('file_path'))
