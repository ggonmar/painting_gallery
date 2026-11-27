"""
Google Gemini Vision Lookup Module
Uses Google Gemini's vision capabilities to identify paintings from images.
"""

import base64
import json
import time
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timezone
import requests

from tags import normalize_tags, prompt_fields

# Rate limiting: store timestamps of recent requests
_gemini_request_timestamps: List[float] = []
_gemini_daily_request_count = 0
_gemini_daily_reset_date = None


class DailyLimitReached(Exception):
    """Exception raised when the daily API limit is reached."""
    pass


def _reset_daily_counter_if_needed():
    """Reset daily counter if we've moved to a new day."""
    global _gemini_daily_request_count, _gemini_daily_reset_date
    
    today = datetime.now(timezone.utc).date()
    if _gemini_daily_reset_date != today:
        _gemini_daily_request_count = 0
        _gemini_daily_reset_date = today


def _enforce_rate_limit(requests_per_minute: int, requests_per_day: int = -1):
    """
    Enforce rate limiting for Gemini API requests.
    
    Args:
        requests_per_minute: Maximum number of requests allowed per minute
        requests_per_day: Maximum number of requests allowed per day (-1 for unlimited)
        
    Returns:
        True if request can proceed, False if daily limit reached
    """
    global _gemini_request_timestamps, _gemini_daily_request_count, _gemini_daily_reset_date
    
    # Check daily limit
    _reset_daily_counter_if_needed()
    if requests_per_day > 0 and _gemini_daily_request_count >= requests_per_day:
        print(f"  ⚠ Daily API limit reached ({requests_per_day} requests/day). Stopping.")
        raise DailyLimitReached(f"Daily API limit of {requests_per_day} requests reached")
    
    current_time = time.time()
    one_minute_ago = current_time - 60
    
    # Remove timestamps older than 1 minute
    _gemini_request_timestamps = [ts for ts in _gemini_request_timestamps if ts > one_minute_ago]
    
    # If we've hit the limit, wait until the oldest request is more than 1 minute old
    if len(_gemini_request_timestamps) >= requests_per_minute:
        oldest_timestamp = _gemini_request_timestamps[0]
        wait_time = 60 - (current_time - oldest_timestamp)
        if wait_time > 0:
            print(f"  ⏳ Rate limit: waiting {wait_time:.1f}s (max {requests_per_minute} requests/min)")
            time.sleep(wait_time + 0.1)  # Add small buffer
            current_time = time.time()
    
    # Record this request
    _gemini_request_timestamps.append(current_time)
    _gemini_daily_request_count += 1
    return True


def lookup_painting_gemini(image_path: Path, api_key: str, language: str = "en", 
                          requests_per_minute: int = 15, requests_per_day: int = -1,
                          description_style: str = "", description_max_length: int = 500,
                          model: str = "gemini-2.5-flash") -> Optional[Dict]:
    """
    Use Google Gemini Vision to identify a painting from its image.
    
    Args:
        image_path: Path to the image file
        api_key: Google Gemini API key
        language: Language for the response
        requests_per_minute: Rate limit for API requests (default: 15)
        requests_per_day: Daily rate limit (default: -1 for unlimited)
        description_style: Style for the description (e.g., "engaging, funny and informative")
        description_max_length: Maximum length for description in characters
        model: Gemini model to use (default: "gemini-2.5-flash")
        
    Returns:
        Dictionary with painting information or None if lookup fails
    """
    if not api_key:
        print("  ⚠ Gemini API key not configured")
        return None
    
    # Enforce rate limiting
    if not _enforce_rate_limit(requests_per_minute, requests_per_day):
        return None
    
    try:
        # Read and encode image
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Determine image mime type
        ext = image_path.suffix.lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.gif': 'image/gif'
        }
        mime_type = mime_types.get(ext, 'image/jpeg')
        
        # Construct prompt based on language
        style_instruction = f" with a {description_style} style" if description_style else ""
        length_instruction = f" (maximum {description_max_length} characters)" if description_max_length else ""
        filename_hint = f"\n\nHINT: The image filename is '{image_path.name}'. This may help identify the painting."
        
        if language == 'es':
            prompt = f"""Analiza esta imagen de una pintura y proporciona la siguiente información en formato JSON:
{{
  "original_title": "título original de la pintura en su idioma original",
  "title": "título de la pintura en español",
  "artist": "nombre del artista",
  "year": "año de creación (solo AAAA, sin rangos)",
  "location": "ubicación actual (museo/colección) si es conocida",
{prompt_fields('es')}  "description": "descripción detallada de la pintura {style_instruction}",
  "confidence": número entre 0.0 y 1.0 indicando tu confianza en la identificación
}}

IMPORTANTE: 
- El "original_title" debe ser el título en el idioma original de la obra (francés, inglés, holandés, etc.)
- El "title" debe ser la traducción al español del título
- La descripción debe ser concisa.{length_instruction}
- Si no estás seguro, indica una confianza baja (< 0.5)
- Para el año, usa solo el formato AAAA (ejemplo: 1889)
- Si no conoces algún dato, usa "Unknown" o "" según corresponda
- Sé honesto sobre tu nivel de certeza{filename_hint}"""
        else:
            prompt = f"""Analyze this painting image and provide the following information in JSON format:
{{
  "original_title": "original title of the painting in its original language",
  "title": "painting title in English",
  "artist": "artist name",
  "year": "year of creation (YYYY format only, no ranges)",
  "location": "current location (museum/collection) if known",
{prompt_fields('en')}  "description": "detailed description of the painting {style_instruction}",
  "confidence": number between 0.0 and 1.0 indicating your confidence in the identification
}}

IMPORTANT:
- The "original_title" should be in the painting's original language (French, Dutch, Italian, etc.)
- The "title" should be the English translation
- The description should be concise.{length_instruction}
- If you're uncertain, indicate low confidence (< 0.5)
- For year, use only YYYY format (example: 1889)
- If you don't know some information, use "Unknown" or "" as appropriate
- Be honest about your level of certainty{filename_hint}"""
        
        # Call Gemini API with configured model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_data
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "topK": 32,
                "topP": 1,
                "maxOutputTokens": 2048,
            }
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"  ⚠ Gemini API error: {response.status_code}")
            if response.status_code == 400:
                error_data = response.json()
                print(f"  Error details: {error_data.get('error', {}).get('message', 'Unknown error')}")
            return None
        
        result = response.json()
        
        # Extract text from response
        if 'candidates' not in result or not result['candidates']:
            print("  ⚠ No response from Gemini")
            return None
        
        text = result['candidates'][0]['content']['parts'][0]['text']
        
        # Try to extract JSON from response
        # Gemini might wrap JSON in markdown code blocks
        text = text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        
        # Parse JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(f"  ⚠ Could not parse Gemini response as JSON")
            print(f"  Response preview: {text[:200]}")
            return None
        
        # Extract confidence score
        confidence = float(data.get('confidence', 0.8))
        
        periods, themes = normalize_tags(data.get('periods'), data.get('themes'))

        # Build result
        painting_info = {
            'periods': periods,
            'themes': themes,
            'original_title': data.get('original_title', data.get('title', 'Unknown')),
            'title': data.get('title', 'Unknown'),
            'artist': data.get('artist', 'Unknown'),
            'year': data.get('year', 'Unknown'),
            'location': data.get('location', ''),
            'description': data.get('description', ''),
            'source': f'gemini:{model}',
            'confidence_score': confidence
        }
        
        print(f"  Source: gemini:{model} (confidence: {confidence:.2f})")
        print(f"  Found: {painting_info['title']} by {painting_info['artist']}")
        
        return painting_info
        
    except FileNotFoundError:
        print(f"  ⚠ Image file not found: {image_path}")
        return None
    except requests.exceptions.Timeout:
        print("  ⚠ Gemini API timeout")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Gemini API request failed: {e}")
        return None
    except Exception as e:
        print(f"  ⚠ Unexpected error with Gemini: {e}")
        return None

def generate_description_gemini(painting: Dict, image_path: Optional[Path], api_key: str,
                                model: str = "gemini-2.5-flash", language: str = "es",
                                description_style: str = "", description_max_length: int = 1000) -> str:
    """
    Write a new description for an already identified painting (title/artist/year are taken as ground truth).
    The image is attached when available so the text can refer to what is actually painted.
    Returns the description text, or '' on failure.
    """
    if not api_key:
        print("  ⚠ Gemini API key not configured")
        return ''
    language_names = {'es': 'español', 'en': 'English', 'fr': 'français', 'de': 'Deutsch', 'it': 'italiano', 'pt': 'português'}
    lang_name = language_names.get(language, language)
    style = description_style or 'engaging and informative'
    facts = ', '.join(f'{k}: {painting.get(k)}' for k in ('title', 'original_title', 'artist', 'year', 'location') if painting.get(k))
    prompt = (
        f"Write a {style} description of this painting ({facts}).\n"
        f"Write it ENTIRELY in {lang_name}. Maximum {description_max_length} characters.\n"
        "Talk about technique, historical context, curious facts and symbolism. "
        "Start directly with the text: no title, no headings, no markdown."
    )
    parts = [{"text": prompt}]
    if image_path and Path(image_path).exists():
        mime = {'.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}.get(Path(image_path).suffix.lower(), 'image/jpeg')
        with open(image_path, 'rb') as f:
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(f.read()).decode('utf-8')}})
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048}},
            timeout=60,
        )
        if response.status_code != 200:
            print(f"  ⚠ Gemini API error: {response.status_code} {response.text[:300]}")
            return ''
        text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        print(f"  → {text[:240]}{'...' if len(text) > 240 else ''}")
        return text
    except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"  ⚠ Gemini description failed: {e}")
        return ''

def lookup_tags_gemini(painting: Dict, image_path: Optional[Path], api_key: str,
                       model: str = "gemini-2.5-flash", requests_per_minute: int = 15):
    """
    Ask Gemini ONLY for the period/theme tags of an already identified painting.
    Returns (periods, themes) normalized to the vocabulary, or None on API failure.
    """
    if not api_key:
        print("  ⚠ Gemini API key not configured")
        return None
    _enforce_rate_limit(requests_per_minute, -1)
    facts = ', '.join(f'{k}: {painting.get(k)}' for k in ('title', 'original_title', 'artist', 'year') if painting.get(k))
    prompt = (
        f"Clasifica esta pintura ({facts}). Responde SOLO con JSON:\n{{\n"
        + prompt_fields('es').rstrip().rstrip(',') + "\n}"
    )
    parts = [{"text": prompt}]
    if image_path and Path(image_path).exists():
        mime = {'.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}.get(Path(image_path).suffix.lower(), 'image/jpeg')
        with open(image_path, 'rb') as f:
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(f.read()).decode('utf-8')}})
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            json={"contents": [{"parts": parts}],
                  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512, "responseMimeType": "application/json"}},
            timeout=60,
        )
        if response.status_code == 429:
            # Quota exhausted (the free tier has a small daily limit): retrying now only wastes time
            raise DailyLimitReached(response.json().get('error', {}).get('message', 'Gemini quota exceeded')[:300])
        if response.status_code != 200:
            print(f"  ⚠ Gemini API error: {response.status_code} {response.text[:200]}")
            return None
        text = response.json()['candidates'][0]['content']['parts'][0]['text']
        start, end = text.find('{'), text.rfind('}')
        data = json.loads(text[start:end + 1])
        return normalize_tags(data.get('periods'), data.get('themes'))
    except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"  ⚠ Gemini tags failed: {e}")
        return None
