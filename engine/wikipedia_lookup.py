"""
Wikipedia Lookup Module
Uses Wikipedia API to search for painting information.
"""

import requests
from typing import Dict, Optional, List
import re


def search_wikipedia(query: str, language: str = "en") -> List[str]:
    """
    Search Wikipedia for articles matching the query.
    
    Args:
        query: Search query
        language: Language code (e.g., 'en', 'es', 'fr')
        
    Returns:
        List of article titles
    """
    try:
        url = f"https://{language}.wikipedia.org/w/api.php"
        params = {
            "action": "opensearch",
            "search": query,
            "limit": 5,
            "namespace": 0,
            "format": "json"
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json()
            # results[1] contains the list of article titles
            return results[1] if len(results) > 1 else []
        return []
    except Exception as e:
        print(f"  Warning: Wikipedia search failed: {e}")
        return []


def get_wikipedia_page(title: str, language: str = "en") -> Optional[Dict]:
    """
    Get detailed information from a Wikipedia page.
    
    Args:
        title: Wikipedia article title
        language: Language code (e.g., 'en', 'es', 'fr')
        
    Returns:
        Dictionary with page content and metadata
    """
    try:
        url = f"https://{language}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts|pageprops|info",
            "exintro": True,
            "explaintext": True,
            "inprop": "url",
            "format": "json"
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            
            # Get the first (and usually only) page
            page_id = list(pages.keys())[0]
            if page_id == "-1":  # Page not found
                return None
            
            page = pages[page_id]
            return {
                "title": page.get("title", ""),
                "extract": page.get("extract", ""),
                "url": page.get("fullurl", ""),
                "wiki_extract": page.get("extract", "")  # Keep full extract for description
            }
        return None
    except Exception as e:
        print(f"  Warning: Could not fetch Wikipedia page: {e}")
        return None


def extract_painting_info(page_data: Dict, filename: str) -> Optional[Dict]:
    """
    Extract painting metadata from Wikipedia page content.
    
    Args:
        page_data: Wikipedia page data
        filename: Original filename for context
        
    Returns:
        Dictionary with painting metadata
    """
    if not page_data:
        return None
    
    extract = page_data.get("extract", "")
    title = page_data.get("title", "")
    
    # Initialize result
    result = {
        "title": title,
        "artist": "Unknown",
        "year": "Unknown",
        "location": "",
        "source": "Wikipedia",
        "wiki_url": page_data.get("url", "")
    }
    
    # Extract artist name (look for "by [Artist Name]" or "Artist Name painted")
    artist_patterns = [
        r'by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:van|de|da|von|del)\s+[A-Z][a-z]+)?)',
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:van|de|da|von|del)\s+[A-Z][a-z]+)?)\s+painted',
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:van|de|da|von|del)\s+[A-Z][a-z]+)?)\s+created',
        r'artist\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:van|de|da|von|del)\s+[A-Z][a-z]+)?)'
    ]
    
    for pattern in artist_patterns:
        match = re.search(pattern, extract)
        if match:
            result["artist"] = match.group(1)
            break
    
    # Extract year (look for four-digit years or ranges)
    year_patterns = [
        r'\b(1[0-9]{3}(?:–|-)1[0-9]{3})\b',  # Year range
        r'\b(1[0-9]{3})\b'  # Single year
    ]
    
    for pattern in year_patterns:
        match = re.search(pattern, extract)
        if match:
            result["year"] = match.group(1)
            break
    
    # Extract museum/location (look for common museum names)
    location_patterns = [
        r'(?:located|housed|displayed|held)\s+(?:at|in)\s+(?:the\s+)?([^.]+(?:Museum|Gallery|Collection|Louvre|Uffizi|Prado|Hermitage)[^.]*)',
        r'((?:Museum|Gallery|Collection)\s+[^.]+)',
        r'(?:the\s+)?(Louvre|Uffizi|Prado|Hermitage|National Gallery|Metropolitan Museum)[^.]*'
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, extract, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            # Clean up the location
            location = re.sub(r'\s+', ' ', location)
            result["location"] = location[:100]  # Limit length
            break
    
    return result


def lookup_painting_wikipedia(filename: str, language: str = "en", search_terms: list = None) -> Optional[Dict]:
    """
    Lookup painting information using Wikipedia.
    
    Args:
        filename: The original filename (without extension)
        language: Language code for Wikipedia (e.g., 'en', 'es', 'fr')
        search_terms: List of cleaned search terms to try in order
        
    Returns:
        Dictionary with painting metadata or None if not found
    """
    # Use provided search terms, or create a simple one
    if not search_terms:
        search_terms = [filename.replace('_', ' ').replace('-', ' ')]
    
    # Try each search term until we find something
    for idx, search_query in enumerate(search_terms):
        if idx > 0:
            print(f"  Trying next term: '{search_query}'")
        
        print(f"  Searching Wikipedia for: '{search_query}'")
        
        # Search Wikipedia
        search_results = search_wikipedia(search_query + " painting", language)
        
        if not search_results:
            # Try without "painting"
            search_results = search_wikipedia(search_query, language)
        
        if not search_results:
            if idx < len(search_terms) - 1:
                continue  # Try next term
            else:
                print("  No Wikipedia results found for any term")
                return None
        
        # Try each search result
        for result_title in search_results[:3]:  # Check top 3 results
            page_data = get_wikipedia_page(result_title, language)
            if page_data:
                extract = page_data.get("extract", "").lower()
                # Check if it's actually about a painting
                if any(word in extract for word in ["painting", "painted", "artist", "canvas", "artwork", "pintura", "pintado", "obra"]):
                    painting_info = extract_painting_info(page_data, filename)
                    if painting_info and painting_info.get("artist") != "Unknown":
                        print(f"  ✓ Found on Wikipedia: {result_title} (searched: '{search_query}')")
                        return painting_info
        
        # This term didn't work, try next one if available
        if idx < len(search_terms) - 1:
            continue
    
    print("  Could not extract painting information from Wikipedia")
    return None
