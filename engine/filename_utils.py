"""
Filename Cleaning Utilities
Extracts searchable terms from painting filenames.
"""

import re


def clean_filename_for_search(filename: str) -> list:
    """
    Clean a filename to extract multiple search terms in priority order.
    
    Removes:
    - File extensions
    - Content in parentheses (dates, etc.)
    - Content in square brackets [orientation, etc.]
    - Leading/trailing dashes and underscores
    
    Normalizes:
    - Underscores to spaces
    - Dots (periods) to spaces
    - Multiple spaces to single space
    
    Strategy:
    - Split by dash separator to get multiple parts
    - Return list of search terms in order (artist, title, etc.)
    - Each part is a potential search query
    
    Args:
        filename: Original filename
        
    Returns:
        List of cleaned search queries to try in order
    """
    # Remove file extension
    name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    
    # Replace underscores and dots with spaces (normalize separators)
    name = name.replace('_', ' ')
    name = name.replace('.', ' ')
    
    # Remove content in parentheses and brackets
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    
    # Split by dash separator to get parts
    parts = [p.strip() for p in name.split(' - ') if p.strip()]
    
    # Clean each part
    search_terms = []
    for part in parts:
        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', part)
        # Remove leading/trailing dashes and spaces
        cleaned = cleaned.strip(' -_')
        
        # Only add if it's substantial enough (at least 3 characters)
        if len(cleaned) >= 3:
            search_terms.append(cleaned)
    
    # If no parts found (no dashes), use the whole cleaned name
    if not search_terms:
        cleaned = re.sub(r'\s+', ' ', name)
        cleaned = cleaned.strip(' -_')
        if len(cleaned) >= 3:
            search_terms.append(cleaned)
    
    return search_terms if search_terms else [filename]


def normalize_year(year_string: str) -> str:
    """
    Normalize year to strict AAAA format.
    
    Rules:
    - Single year: keep as is (1889)
    - Range (1840-1841): take second year (1841)
    - Range (1840-41): expand and take second (1841)
    - Multiple options (1840 1841): take second (1841)
    - Invalid/None: return empty string
    
    Args:
        year_string: Year string to normalize
        
    Returns:
        Normalized year (AAAA) or empty string
    """
    if not year_string or year_string == 'Unknown':
        return ''
    
    # Convert to string and clean
    year_str = str(year_string).strip()
    
    # Remove parentheses
    year_str = re.sub(r'[()]', '', year_str)
    
    # Find all 4-digit years
    years = re.findall(r'\b(1[0-9]{3}|2[0-9]{3})\b', year_str)
    
    if not years:
        # Try to find partial years like "40" in "1840-41"
        match = re.search(r'(\d{4})-(\d{2})\b', year_str)
        if match:
            century = match.group(1)[:2]
            short_year = match.group(2)
            second_year = century + short_year
            return second_year
        
        return ''
    
    # If multiple years, take the last one (end of range)
    return years[-1]
