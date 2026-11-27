"""
Filename Parsing Module
Extracts metadata from existing well-formatted filenames.
"""

import re
from typing import Dict, Optional


def parse_formatted_filename(filename: str) -> Optional[Dict]:
    """
    Parse a well-formatted filename to extract metadata.
    
    Assumes filename format like:
    - "Title - Artist (Year) [orientation].ext"
    - "Title - Artist (Year) Location [orientation].ext"
    - "Title - Artist [orientation].ext"
    - Or variations with these components
    
    Args:
        filename: Filename to parse
        
    Returns:
        Dictionary with extracted metadata or None if parsing fails
    """
    # Remove extension
    name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    
    # Initialize result
    result = {
        'title': 'Unknown',
        'artist': 'Unknown',
        'year': 'Unknown',
        'location': '',
        'orientation': 'landscape'
    }
    
    # Extract orientation from brackets [landscape], [portrait], [square]
    orientation_match = re.search(r'\[(landscape|portrait|square)\]', name, re.IGNORECASE)
    if orientation_match:
        result['orientation'] = orientation_match.group(1).lower()
        # Remove orientation from name
        name = re.sub(r'\s*\[(landscape|portrait|square)\]', '', name, flags=re.IGNORECASE)
    
    # Extract year from parentheses (1889), (1840-1841), etc.
    year_match = re.search(r'\((\d{4}(?:-\d{2,4})?)\)', name)
    if year_match:
        year_str = year_match.group(1)
        # Normalize year (take second if range)
        from filename_utils import normalize_year
        result['year'] = normalize_year(year_str)
        # Remove year from name
        name = re.sub(r'\s*\(\d{4}(?:-\d{2,4})?\)', '', name)
    
    # Split by dash to get parts
    parts = [p.strip() for p in name.split(' - ') if p.strip()]
    
    if len(parts) >= 2:
        # Format: Title - Artist [- Location]
        result['title'] = parts[0]
        result['artist'] = parts[1]
        
        # If there's a third part, it might be location
        if len(parts) >= 3:
            result['location'] = parts[2]
    elif len(parts) == 1:
        # Only one part - assume it's the title
        result['title'] = parts[0]
    else:
        # Unable to parse
        return None
    
    return result


def extract_metadata_from_filename(filename: str) -> Dict:
    """
    Extract metadata from existing filename, treating it as ground truth.
    
    Args:
        filename: Well-formatted filename
        
    Returns:
        Dictionary with metadata and high confidence score
    """
    parsed = parse_formatted_filename(filename)
    
    if not parsed:
        # Fallback: use whole filename as title
        name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        parsed = {
            'title': name,
            'artist': 'Unknown',
            'year': 'Unknown',
            'location': '',
            'orientation': 'landscape'
        }
    
    # Add source and confidence
    parsed['source'] = 'Filename (Ground Truth)'
    parsed['confidence_score'] = 1.0  # High confidence since it's user-curated
    
    return parsed
