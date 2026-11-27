"""
File Manager Module
Handles file operations including renaming and duplicate detection.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Set


def parse_naming_format(format_string: str, title: str, artist: str, year: str, 
                        location: str, orientation: str, is_duplicate: bool = False) -> str:
    """
    Parse a naming format string and replace placeholders with actual values.
    
    Supported placeholders:
    - %title% or %painting%: Painting title
    - %artist% or %painter%: Artist name
    - %year%: Year painted
    - %location%: Current location/museum
    - %orientation%: Image orientation
    
    Args:
        format_string: Format template string
        title: Painting title
        artist: Artist name
        year: Year painted
        location: Current location/museum
        orientation: Image orientation
        is_duplicate: Whether this is a duplicate
        
    Returns:
        Formatted filename string
    """
    # Sanitize all values first
    title = sanitize_filename(title)
    artist = sanitize_filename(artist)
    year = sanitize_filename(str(year))
    location = sanitize_filename(location)
    orientation = sanitize_filename(orientation)
    
    # Replace placeholders (case-insensitive)
    result = format_string
    
    # Title/Painting
    result = re.sub(r'%title%', title, result, flags=re.IGNORECASE)
    result = re.sub(r'%painting%', title, result, flags=re.IGNORECASE)
    
    # Artist/Painter
    result = re.sub(r'%artist%', artist, result, flags=re.IGNORECASE)
    result = re.sub(r'%painter%', artist, result, flags=re.IGNORECASE)
    
    # Year
    result = re.sub(r'%year%', year if year != "Unknown" else "", result, flags=re.IGNORECASE)
    
    # Location
    result = re.sub(r'%location%', location, result, flags=re.IGNORECASE)
    
    # Orientation
    result = re.sub(r'%orientation%', orientation if orientation != "unknown" else "", result, flags=re.IGNORECASE)
    
    # Clean up multiple spaces and empty parentheses/brackets
    result = re.sub(r'\s+', ' ', result)  # Multiple spaces to single
    result = re.sub(r'\(\s*\)', '', result)  # Empty parentheses
    result = re.sub(r'\[\s*\]', '', result)  # Empty brackets
    result = re.sub(r'\s+-\s+-', ' -', result)  # Multiple dashes
    result = result.strip()
    result = result.strip('-').strip()  # Remove leading/trailing dashes
    
    # Add duplicate prefix if needed
    if is_duplicate:
        result = f"CHECK_DUPE - {result}"
    
    return result


def sanitize_filename(text: str) -> str:
    """
    Sanitize text to be safe for use in filenames.
    
    Args:
        text: Text to sanitize
        
    Returns:
        Sanitized text safe for filenames
    """
    # Replace problematic characters with safe alternatives
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text)
    # Trim whitespace
    text = text.strip()
    return text


def create_new_filename(title: str, artist: str, year: str, location: str, 
                       orientation: str, extension: str, is_duplicate: bool = False, 
                       naming_format: str = None, is_low_confidence: bool = False) -> str:
    """
    Create a new filename from painting metadata using a configurable format.
    
    Default format: [Artist] - [Title] ([Year]) [Location] [Orientation][.ext]
    Or if duplicate: CHECK_DUPE - [Artist] - [Title] ([Year]) [Location] [Orientation][.ext]
    Or if low confidence: CHECK UNKNOWN - [Artist] - [Title] ([Year]) [Location] [Orientation][.ext]
    
    Args:
        title: Painting title
        artist: Artist name
        year: Year painted
        location: Current location/museum
        orientation: Image orientation (landscape/portrait/square)
        extension: File extension (including dot)
        is_duplicate: Whether this is a smaller duplicate
        naming_format: Custom naming format string (uses default if None)
        is_low_confidence: Whether the identification has low confidence
        
    Returns:
        New filename string
    """
    # Use custom format if provided, otherwise use default
    if naming_format:
        filename = parse_naming_format(
            naming_format, title, artist, year, location, orientation, is_duplicate
        )
    else:
        # Default legacy format
        # Sanitize all components
        artist = sanitize_filename(artist)
        title = sanitize_filename(title)
        year = sanitize_filename(str(year))
        location = sanitize_filename(location)
        orientation = sanitize_filename(orientation)
        
        # Build filename components
        parts = []
        
        parts.append(artist)
        parts.append(title)
        
        # Add year in parentheses
        if year and year != "Unknown":
            parts.append(f"({year})")
        
        # Add location if available
        if location:
            parts.append(location)
        
        # Add orientation
        if orientation and orientation != "unknown":
            parts.append(f"[{orientation}]")
        
        # Join with " - " separator
        filename = " - ".join(parts)
    
    # Add low confidence prefix if needed (takes priority)
    if is_low_confidence:
        filename = f"CHECK UNKNOWN - {filename}"
    # Add duplicate prefix if needed
    elif is_duplicate:
        filename = f"CHECK_DUPE - {filename}"
    
    # Ensure filename isn't too long (Windows has 260 char path limit)
    max_length = 200
    if len(filename) > max_length:
        filename = filename[:max_length].rsplit(' ', 1)[0]  # Trim at word boundary
    
    return filename + extension


def rename_file(file_path: Path, new_filename: str) -> Path:
    """
    Rename a file safely, handling conflicts.
    
    Args:
        file_path: Current file path
        new_filename: New filename (not full path)
        
    Returns:
        Path to renamed file or None if failed
    """
    try:
        new_path = file_path.parent / new_filename
        
        # Handle filename conflicts
        if new_path.exists() and new_path != file_path:
            # Add a number suffix
            counter = 1
            name_without_ext = new_path.stem
            ext = new_path.suffix
            
            while new_path.exists():
                new_filename_with_counter = f"{name_without_ext} ({counter}){ext}"
                new_path = file_path.parent / new_filename_with_counter
                counter += 1
        
        # Perform rename
        file_path.rename(new_path)
        return new_path
        
    except Exception as e:
        print(f"  Error renaming file: {e}")
        return None


def detect_duplicates(paintings: List[Dict]) -> List[Set[int]]:
    """
    Detect duplicate paintings (same title and artist) and identify smaller files.
    
    Args:
        paintings: List of painting metadata dictionaries
        
    Returns:
        List of sets, where each set contains indices of duplicate paintings
    """
    # Group paintings by (title, artist)
    groups = {}
    
    for idx, painting in enumerate(paintings):
        key = (
            painting.get('title', '').lower().strip(),
            painting.get('artist', '').lower().strip()
        )
        
        if key not in groups:
            groups[key] = []
        groups[key].append(idx)
    
    # Find groups with duplicates
    duplicate_sets = []
    for key, indices in groups.items():
        if len(indices) > 1:
            # Sort by file size to identify smaller duplicates
            indices_sorted = sorted(indices, key=lambda i: paintings[i].get('file_size', 0))
            
            # Mark all but the largest as duplicates
            for idx in indices_sorted[:-1]:
                paintings[idx]['is_duplicate'] = True
            
            duplicate_sets.append(set(indices))
            
            # Print duplicate info
            print(f"\n  ⚠ Found duplicates for: {paintings[indices[0]].get('title', 'Unknown')}")
            for idx in indices_sorted:
                size_mb = paintings[idx].get('file_size', 0) / (1024 * 1024)
                status = "(smaller - will be marked)" if idx in indices_sorted[:-1] else "(largest - keep)"
                print(f"    - {paintings[idx].get('original_filename', 'Unknown')} "
                      f"- {size_mb:.2f} MB {status}")
    
    return duplicate_sets
