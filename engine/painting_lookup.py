"""
Painting Lookup Module
Interfaces with Ollama LLM to search for painting information and generate descriptions.
"""

from tags import PERIODS as TAG_PERIODS, THEMES as TAG_THEMES, normalize_tags
import json
import re
import requests
import time
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timezone

# Rate limiting: store timestamps of recent requests
_ollama_request_timestamps: List[float] = []
_ollama_daily_request_count = 0
_ollama_daily_reset_date = None


class DailyLimitReached(Exception):
    """Exception raised when the daily API limit is reached."""
    pass


def _reset_daily_counter_if_needed():
    """Reset daily counter if we've moved to a new day."""
    global _ollama_daily_request_count, _ollama_daily_reset_date
    
    today = datetime.now(timezone.utc).date()
    if _ollama_daily_reset_date != today:
        _ollama_daily_request_count = 0
        _ollama_daily_reset_date = today


def _enforce_rate_limit(requests_per_minute: int, requests_per_day: int = -1):
    """
    Enforce rate limiting for Ollama requests.
    
    Args:
        requests_per_minute: Maximum number of requests allowed per minute
        requests_per_day: Maximum number of requests allowed per day (-1 for unlimited)
        
    Returns:
        True if request can proceed, False if daily limit reached
    """
    global _ollama_request_timestamps, _ollama_daily_request_count, _ollama_daily_reset_date
    
    # Check daily limit
    _reset_daily_counter_if_needed()
    if requests_per_day > 0 and _ollama_daily_request_count >= requests_per_day:
        print(f"  ⚠ Daily Ollama limit reached ({requests_per_day} requests/day). Stopping.")
        raise DailyLimitReached(f"Daily Ollama limit of {requests_per_day} requests reached")
    
    current_time = time.time()
    one_minute_ago = current_time - 60
    
    # Remove timestamps older than 1 minute
    _ollama_request_timestamps = [ts for ts in _ollama_request_timestamps if ts > one_minute_ago]
    
    # If we've hit the limit, wait until the oldest request is more than 1 minute old
    if len(_ollama_request_timestamps) >= requests_per_minute:
        oldest_timestamp = _ollama_request_timestamps[0]
        wait_time = 60 - (current_time - oldest_timestamp)
        if wait_time > 0:
            print(f"  ⏳ Ollama rate limit: waiting {wait_time:.1f}s (max {requests_per_minute} requests/min)")
            time.sleep(wait_time + 0.1)  # Add small buffer
            current_time = time.time()
    
    # Record this request
    _ollama_request_timestamps.append(current_time)
    _ollama_daily_request_count += 1
    return True


def get_language_name(language_code: str) -> str:
    """Get the full language name from language code."""
    language_map = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "ru": "Russian",
        "ja": "Japanese",
        "zh": "Chinese",
        "ko": "Korean"
    }
    return language_map.get(language_code.lower(), "English")


def get_example_title(language_code: str) -> str:
    """Get an example painting title in the specified language."""
    examples = {
        "en": "The Starry Night",
        "es": "La noche estrellada",
        "fr": "La Nuit étoilée",
        "de": "Die Sternennacht",
        "it": "La notte stellata",
        "pt": "A Noite Estrelada"
    }
    return examples.get(language_code.lower(), "The Starry Night")


def validate_ollama_connection(ollama_host: str, model: str, ollama_api_key: str = None) -> bool:
    """
    Validate that Ollama is accessible and the specified model exists.
    
    Args:
        ollama_host: Ollama server URL
        model: Model name to validate
        ollama_api_key: Optional API key for authentication
        
    Returns:
        True if validation passes, False otherwise
    """
    print(f"Validating Ollama connection...")
    print(f"  Host: {ollama_host}")
    print(f"  Model: {model}")
    
    try:
        headers = {}
        if ollama_api_key:
            headers["Authorization"] = f"Bearer {ollama_api_key}"
        
        # Test 1: Check if Ollama server is reachable
        try:
            response = requests.get(f"{ollama_host}/api/tags", headers=headers, timeout=5)
            if response.status_code != 200:
                print(f"  ✗ Error: Ollama server returned status {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            print(f"  ✗ Error: Cannot connect to Ollama at {ollama_host}")
            print(f"     Make sure Ollama is running and the host URL is correct")
            return False
        except requests.exceptions.Timeout:
            print(f"  ✗ Error: Connection to Ollama timed out")
            return False
        
        # Test 2: Check if the model exists
        models_data = response.json()
        available_models = [m.get('name', '') for m in models_data.get('models', [])]
        
        # Model names might have tags like ':latest', so check both with and without
        model_exists = any(
            model == m or model == m.split(':')[0] or f"{model}:latest" == m
            for m in available_models
        )
        
        if not model_exists:
            print(f"  ✗ Error: Model '{model}' not found in Ollama")
            print(f"     Available models: {', '.join(available_models) if available_models else 'none'}")
            print(f"     Pull the model with: ollama pull {model}")
            return False
        
        # Test 3: Quick test generation to ensure model responds
        test_response = requests.post(
            f"{ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": "Test",
                "stream": False,
                "options": {"num_predict": 1}
            },
            headers=headers,
            timeout=180  # a local model not yet in memory needs time to load
        )
        
        if test_response.status_code != 200:
            print(f"  ✗ Error: Model test failed with status {test_response.status_code}")
            return False
        
        print(f"  ✓ Ollama connection validated successfully")
        return True
        
    except Exception as e:
        print(f"  ✗ Error validating Ollama: {e}")
        return False


def lookup_painting_info(filename: str, image_path: Path = None, ollama_host: str = "http://192.168.1.3:11434", ollama_api_key: str = None, language: str = "en", context_info: dict = None, search_terms: list = None, description_style: str = "", description_max_length: int = 500, requests_per_minute: int = 60, requests_per_day: int = -1) -> Optional[Dict]:
    """
    Lookup painting information using Ollama LLM with vision support.
    
    Args:
        filename: The original filename (without extension)
        image_path: Path to the image file (for vision models)
        ollama_host: Ollama server URL
        ollama_api_key: Optional API key for authentication
        language: Language code for the response (e.g., 'en', 'es', 'fr')
        context_info: Optional context from previous data source (e.g., Wikipedia results)
        search_terms: List of search terms to try in order
        description_style: Style for the description (e.g., "engaging, funny and informative")
        description_max_length: Maximum length for description in characters
        requests_per_minute: Rate limit for requests (default: 60)
        requests_per_day: Daily rate limit (default: -1 for unlimited)
        
    Returns:
        Dictionary with painting metadata or None if not found (includes confidence_score)
    """
    # Enforce rate limiting
    if not _enforce_rate_limit(requests_per_minute, requests_per_day):
        return None
    # Use first search term if provided, otherwise use filename
    if search_terms and len(search_terms) > 0:
        search_filename = search_terms[0]  # Start with first term
    else:
        search_filename = filename
    
    # Build context string if we have previous information
    context_str = ""
    if context_info:
        context_str = f"""

CONTEXT: Previous data source provided this information:
- Title: {context_info.get('title', 'Unknown')}
- Artist: {context_info.get('artist', 'Unknown')}
- Year: {context_info.get('year', 'Unknown')}
- Location: {context_info.get('location', 'Not specified')}

Please verify, correct, or enhance this information if needed. If the information is accurate, you can use it. If you find errors or have better information, provide the corrected version."""
    
    language_name = get_language_name(language)
    
    prompt = f"""Given the filename "{search_filename}", identify the painting and provide information in JSON format.

HINT: The image filename is '{filename}'. Use this as a hint to help identify the painting's title, artist, or year.

The filename may contain the painting title, artist name, or both.
{context_str}

Please provide the following information:
- original_title: The full title of the painting in its ORIGINAL LANGUAGE (e.g., if it's a Spanish painting, keep it in Spanish)
- title: The full title of the painting translated to {language_name}
- artist: The full name of the artist/painter (keep original name, do not translate)
- year: The year the painting was created (SINGLE YEAR ONLY in YYYY format - if there's a range like 1840-1841, use the second year 1841)
- location: Current location/museum where the painting is held (keep in English/original language)
- periods: list of 1 or 2 periods/movements, ONLY from this Spanish list: {', '.join(TAG_PERIODS)}
- themes: list of 1 to 4 themes, ONLY from this Spanish list: {', '.join(TAG_THEMES)}
- confidence_score: A number between 0.0 and 1.0 indicating your confidence that this identification is correct
  * 1.0 = absolutely certain (you know this painting well)
  * 0.8 = very confident (strong evidence)
  * 0.6 = moderately confident (reasonable guess)
  * 0.4 = uncertain (weak evidence)
  * 0.2 = very uncertain (mostly guessing)

BE HONEST about confidence! If you're not sure, use a lower score. Do NOT default to 1.0 or 0.5 automatically.

IMPORTANT: Do not default to famous paintings like "Starry Night", "Mona Lisa", or "Guernica" unless you are absolutely certain from the filename. If uncertain, use a low confidence_score (< 0.5).

Example response format (DO NOT copy these exact values):
{{
  "original_title": "Title in Original Language",
  "title": "Title in {language_name}",
  "artist": "Artist Full Name",
  "year": "YYYY",
  "location": "Museum Name",
  "periods": ["barroco"],
  "themes": ["retrato", "religión"],
  "confidence_score": 0.0-1.0
}}"""

    try:
        headers = {}
        if ollama_api_key:
            headers["Authorization"] = f"Bearer {ollama_api_key}"
        
        # Get model from config or use default
        from config_manager import ConfigManager
        config = ConfigManager()
        model = config.get('ollama_model', 'llama3.2')
        
        print(f"  Querying ollama:{model}...")
        
        # Prepare the request payload
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        
        # If image_path is provided, add image data for vision models
        if image_path and image_path.exists():
            import base64
            try:
                with open(image_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                payload["images"] = [image_data]
                print(f"  → Sending image to vision model")
            except Exception as e:
                print(f"  ⚠ Could not read image file: {e}")
        
        response = requests.post(
            f"{ollama_host}/api/generate",
            json=payload,
            headers=headers,
            timeout=300  # local vision models are slow with large images
        )
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get('response', '{}')
            
            # Strip markdown code fences if present
            # Ollama sometimes wraps JSON in ```json ... ```
            if response_text.strip().startswith('```'):
                # Remove opening fence (```json or ```)
                response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text.strip())
                # Remove closing fence (```)
                response_text = re.sub(r'\n?```\s*$', '', response_text)
            
            # Extract JSON object from response text
            # LLMs often add explanatory text before/after the JSON
            # Find the first { and last } to extract just the JSON part
            first_brace = response_text.find('{')
            last_brace = response_text.rfind('}')
            
            if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                response_text = response_text[first_brace:last_brace + 1]
            
            try:
                painting_info = json.loads(response_text)
                
                # Validate that we got useful information
                if painting_info and painting_info.get('title') and painting_info.get('artist'):
                    # Mark source as Ollama with model name
                    periods, themes = normalize_tags(painting_info.get('periods'), painting_info.get('themes'))
                    info = {
                        'periods': periods,
                        'themes': themes,
                        'original_title': painting_info.get('original_title', painting_info.get('title', 'Unknown')),
                        'title': painting_info.get('title', 'Unknown'),
                        'artist': painting_info.get('artist', 'Unknown'),
                        'year': painting_info.get('year', 'Unknown'),
                        'location': painting_info.get('location', ''),
                        'confidence_score': float(painting_info.get('confidence_score', 0.5)),
                        'source': f'ollama:{model}'
                    }
                    return info
                else:
                    return None
            except json.JSONDecodeError as e:
                print(f"  Warning: Could not parse JSON response from Ollama")
                print(f"  Error: {e}")
                print(f"  Response was: {response_text}")
                return None
        else:
            print(f"  Warning: Ollama request failed with status {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Could not connect to Ollama: {e}")
        
        # Check if this is a timeout or connection error that might be temporary
        is_retryable = isinstance(e, (requests.exceptions.Timeout, 
                                     requests.exceptions.ConnectionError,
                                     requests.exceptions.ReadTimeout))
        
        if is_retryable:
            max_retries = 3
            retry_delay = 5  # seconds
            
            for retry in range(1, max_retries + 1):
                print(f"  → Retrying in {retry_delay} seconds... (attempt {retry}/{max_retries})")
                time.sleep(retry_delay)
                
                try:
                    print(f"  → Retry attempt {retry}: Sending request to Ollama...")
                    response = requests.post(
                        f"{ollama_host}/api/generate",
                        json=payload,
                        headers=headers,
                        timeout=60
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        response_text = result.get('response', '{}')
                        
                        # Strip markdown code fences if present
                        if response_text.strip().startswith('```'):
                            response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text.strip())
                            response_text = re.sub(r'\n?```\s*$', '', response_text)
                        
                        # Extract JSON object from response text
                        first_brace = response_text.find('{')
                        last_brace = response_text.rfind('}')
                        
                        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                            response_text = response_text[first_brace:last_brace + 1]
                        
                        painting_info = json.loads(response_text)
                        
                        if painting_info and painting_info.get('title') and painting_info.get('artist'):
                            info = {
                                'original_title': painting_info.get('original_title', painting_info.get('title', 'Unknown')),
                                'title': painting_info.get('title', 'Unknown'),
                                'artist': painting_info.get('artist', 'Unknown'),
                                'year': painting_info.get('year', 'Unknown'),
                                'location': painting_info.get('location', ''),
                                'confidence_score': float(painting_info.get('confidence_score', 0.5)),
                                'source': f'ollama:{model}'
                            }
                            print(f"  ✓ Retry successful!")
                            return info
                    
                    # Exponential backoff for next retry
                    retry_delay *= 2
                    
                except Exception as retry_error:
                    print(f"  ⚠ Retry {retry} failed: {retry_error}")
                    if retry < max_retries:
                        retry_delay *= 2  # Exponential backoff
                    continue
            
            print(f"  ✗ All retry attempts failed")
        
        return None
    except Exception as e:
        print(f"  ⚠ Error looking up painting info: {e}")
        return None


def generate_description(painting_info: Dict, ollama_host: str = "http://192.168.1.3:11434", ollama_api_key: str = None, language: str = "en", description_style: str = "", description_max_length: int = 500) -> str:
    """
    Generate a rich description and memorabilia about the painting using Ollama LLM.
    
    Args:
        painting_info: Dictionary containing painting metadata
        ollama_host: Ollama server URL
        ollama_api_key: Optional API key for authentication
        language: Language code for the description (e.g., 'en', 'es', 'fr')
        description_style: Style for the description (e.g., "engaging, funny and informative")
        description_max_length: Maximum length for description in characters
        
    Returns:
        Generated description text
    """
    title = painting_info.get('title', 'Unknown')
    artist = painting_info.get('artist', 'Unknown')
    year = painting_info.get('year', 'Unknown')
    location = painting_info.get('location', '')
    
    # Get config values
    from config_manager import ConfigManager
    config = ConfigManager()
    model = config.get('ollama_model', 'llama3.2')
    # Use parameters if provided, otherwise fall back to config
    max_length = description_max_length if description_max_length else config.get('description_max_length', 500)
    style = description_style if description_style else config.get('description_style', 'engaging and informative')
    
    print(f"  Generating description (ollama:{model})...")
    
    prompt = f"""Write a {style} description of the painting "{title}" by {artist} (painted in {year}).

Write the ENTIRE description in {get_language_name(language)}.

Include interesting details such as:
- The artistic style and technique used
- The historical context and what was happening when it was painted
- Interesting facts or stories about the painting's creation
- Its significance in art history
- Any notable features or symbolism

Keep the description to a MAXIMUM of {max_length} characters (approximately {max_length // 7} words). Write in a {style} style.

IMPORTANT FORMATTING RULES:
- The description must not exceed {max_length} characters in total length
- Start directly with the description content about the painting itself
- Do not include a title or heading, just the description text in {get_language_name(language)}

Just provide the description text in {get_language_name(language)}."""

    try:
        headers = {}
        if ollama_api_key:
            headers["Authorization"] = f"Bearer {ollama_api_key}"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(
            f"{ollama_host}/api/generate",
            json=payload,
            headers=headers,
            timeout=300
        )
        
        data = response.json()
        description = data.get('response', '').strip()
        
        # Show preview of description (first 240 characters)
        preview = description[:240] + '...' if len(description) > 240 else description
        print(f"  → {preview}")
        
        return description
    
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Could not connect to Ollama for description: {e}")
        
        # Check if this is a timeout or connection error that might be temporary
        is_retryable = isinstance(e, (requests.exceptions.Timeout, 
                                     requests.exceptions.ConnectionError,
                                     requests.exceptions.ReadTimeout))
        
        if is_retryable:
            max_retries = 3
            retry_delay = 5  # seconds
            
            for retry in range(1, max_retries + 1):
                print(f"  → Retrying in {retry_delay} seconds... (attempt {retry}/{max_retries})")
                time.sleep(retry_delay)
                
                try:
                    print(f"  → Retry attempt {retry}: Generating description...")
                    response = requests.post(
                        f"{ollama_host}/api/generate",
                        json=payload,
                        headers=headers,
                        timeout=300
                    )
                    
                    data = response.json()
                    description = data.get('response', '').strip()
                    
                    preview = description[:240] + '...' if len(description) > 240 else description
                    print(f"  ✓ Retry successful!")
                    print(f"  → {preview}")
                    
                    return description
                    
                except Exception as retry_error:
                    print(f"  ⚠ Retry {retry} failed: {retry_error}")
                    if retry < max_retries:
                        retry_delay *= 2  # Exponential backoff
                    continue
            
            print(f"  ✗ All retry attempts failed")
        
        return ""
    
    except Exception as e:
        print(f"  ⚠ Error generating description: {str(e)}")
        return ""

def lookup_tags_ollama(painting: Dict, image_path: Optional[Path], ollama_host: str, ollama_api_key: str = None,
                       model: str = "llama3.2"):
    """
    Ask Ollama ONLY for the period/theme tags of an already identified painting (image attached when available).
    Returns (periods, themes) normalized to the vocabulary, or None on failure.
    """
    facts = ', '.join(f'{k}: {painting.get(k)}' for k in ('title', 'original_title', 'artist', 'year') if painting.get(k))
    prompt = (
        f"Classify this painting ({facts}). Answer ONLY with JSON:\n{{\n"
        f'  "periods": [1 or 2 periods/movements, ONLY from: {", ".join(TAG_PERIODS)}],\n'
        f'  "themes": [1 to 4 themes, ONLY from: {", ".join(TAG_THEMES)}]\n}}'
    )
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    if image_path and Path(image_path).exists():
        import base64
        with open(image_path, 'rb') as f:
            payload["images"] = [base64.b64encode(f.read()).decode('utf-8')]
    headers = {"Authorization": f"Bearer {ollama_api_key}"} if ollama_api_key else {}
    try:
        response = requests.post(f"{ollama_host}/api/generate", json=payload, headers=headers, timeout=300)
        if response.status_code != 200:
            print(f"  ⚠ Ollama error: {response.status_code} {response.text[:200]}")
            return None
        text = response.json().get('response', '')
        start, end = text.find('{'), text.rfind('}')
        data = json.loads(text[start:end + 1])
        return normalize_tags(data.get('periods'), data.get('themes'))
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"  ⚠ Ollama tags failed: {e}")
        return None
