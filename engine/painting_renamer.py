#!/usr/bin/env python3
"""
Painting Renamer - Main Script
Renames painting image files with complete metadata and builds a JSON library.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List
from datetime import datetime, timezone

from image_utils import analyze_image, get_image_dimensions
from painting_lookup import lookup_painting_info, generate_description, DailyLimitReached as OllamaDailyLimitReached, validate_ollama_connection
from gemini_lookup import lookup_painting_gemini, DailyLimitReached as GeminiDailyLimitReached
from file_manager import create_new_filename, rename_file, detect_duplicates
from library_manager import LibraryManager, ensure_runs_on_nas
from config_manager import ConfigManager
from filename_utils import clean_filename_for_search, normalize_year
from filename_parser import extract_metadata_from_filename
from library_lock import library_lock


def merge_painting_info(existing: dict, new: dict, prefer_source: str = 'new') -> dict:
    """
    Merge two painting info dictionaries, with preference for one source.
    
    Args:
        existing: Existing painting info
        new: New painting info to merge
        prefer_source: Which source to prefer for conflicts ('existing' or 'new')
        
    Returns:
        Merged dictionary
    """
    merged = existing.copy()
    
    # Define which fields to prefer from which source
    for key in ['title', 'artist', 'year', 'location']:
        # Use new value if existing is empty/unknown, or if we prefer new source
        if key in new:
            new_val = new[key]
            existing_val = merged.get(key, '')
            
            # Replace if existing is empty/unknown
            if not existing_val or existing_val == 'Unknown':
                merged[key] = new_val
            # Or if new is not empty and we prefer new source
            elif new_val and new_val != 'Unknown' and prefer_source == 'new':
                merged[key] = new_val
    
    # Combine descriptions if both exist
    if 'description' in new and new['description']:
        if 'description' in merged and merged['description']:
            # Keep both descriptions separate
            merged['description_combined'] = f"{merged['description']}\n\n[Additional info]: {new['description']}"
        else:
            merged['description'] = new['description']
    
    # Tags: a later source only replaces them if it actually returned some
    for key in ('periods', 'themes'):
        if new.get(key):
            merged[key] = new[key]

    # Keep wiki_extract if from Wikipedia
    if 'wiki_extract' in new:
        merged['wiki_extract'] = new['wiki_extract']
    
    # Keep wiki_url if from Wikipedia
    if 'wiki_url' in new:
        merged['wikipedia_url'] = new['wiki_url']
    
    # Track sources used
    existing_source = merged.get('source', '')
    new_source = new.get('source', '')
    if existing_source and new_source:
        merged['sources_used'] = f"{existing_source},{new_source}"
    elif new_source:
        merged['source'] = new_source
    
    return merged


# Supported image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif', '.webp'}


def get_image_files(folder_path: Path) -> List[Path]:
    """
    Get all image files from the specified folder.
    
    Args:
        folder_path: Path to the folder containing images
        
    Returns:
        List of Path objects for image files
    """
    image_files = []
    for file in folder_path.iterdir():
        if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(file)
    return image_files


def process_painting(file_path: Path, library: LibraryManager, ollama_host: str = "http://192.168.1.3:11434", ollama_api_key: str = None, update_only: bool = False, no_description: bool = False, only_location: bool = False, only_comment: bool = False) -> dict:
    """
    Process a single painting file: lookup info, analyze image, and prepare metadata.
    
    Args:
        file_path: Path to the image file
        library: LibraryManager instance
        ollama_host: Ollama server URL
        ollama_api_key: Optional API key for authentication
        update_only: If True, parse filename as ground truth and only query for descriptions
        only_location: If True, only lookup and update location field
        only_comment: If True, only generate descriptions for existing library entries
        
    Returns:
        Dictionary with painting metadata
    """
    print(f"\nProcessing: {file_path.name}")
    
    # Get configuration
    config = ConfigManager()
    data_source_config = config.get('data_source', 'wikipedia,ollama')
    language = config.get('language', 'en')
    naming_format = config.get('naming_format')
    
    # ONLY-LOCATION MODE: Process like normal but skip descriptions
    if only_location:
        print(f"  Mode: Full metadata lookup (location only, no descriptions)")
        # Force no description generation
        no_description = True
        # Continue to normal processing below
        # (will do LLM lookup for title, artist, year, location but skip description)
    
    # ONLY-COMMENT MODE: Generate descriptions only for existing library entries
    if only_comment:
        print(f"  Mode: Generate description only (existing library entry)")
        
        # Try to find the painting in the library by filename
        painting = None
        for entry in library.paintings:
            if entry.get('file_path', '').endswith(file_path.name) or entry.get('original_filename') == file_path.name:
                painting = entry
                break
        
        if not painting:
            print(f"  ⚠ Painting not found in library. Skipping.")
            return None
        
        print(f"  Found in library: {painting.get('title', 'Unknown')} by {painting.get('artist', 'Unknown')}")
        
        # Generate description using existing metadata
        description = ""
        description_max_length = config.get('description_max_length', 500)
        if 'ollama' in data_source_config:
            description_style = config.get('description_style', '')
            description_context = {
                'title': painting.get('title', 'Unknown'),
                'artist': painting.get('artist', 'Unknown'),
                'year': painting.get('year', ''),
                'location': painting.get('location', '')
            }
            print(f"  Generating description...")
            description = generate_description(description_context, ollama_host, ollama_api_key, language, description_style, description_max_length)
        
        # Update only the description field in library
        if description and description.strip() and description.strip().lower() not in ['description not available.', 'description not available']:
            ollama_model = config.get('ollama_model', 'kimi-k2.5:cloud')
            description_entry = {
                'description': description,
                'language': language,
                'description_style': config.get('description_style', 'engaging and informative'),
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'comment_creator': f'ollama:{ollama_model}',
                'max_length': description_max_length
            }
            
            # Initialize descriptions dict if it doesn't exist
            if 'descriptions' not in painting:
                painting['descriptions'] = {}
            
            # Handle both old format (dict) and new format (list)
            if language not in painting['descriptions']:
                painting['descriptions'][language] = []
            elif not isinstance(painting['descriptions'][language], list):
                # Convert old format to new format
                painting['descriptions'][language] = [painting['descriptions'][language]]
            
            # Add new description at the beginning (most recent first)
            painting['descriptions'][language].insert(0, description_entry)
            
            # Save library
            library.save()
            print(f"  ✓ Description added to library")
        else:
            print(f"  ⚠ No valid description generated")
        
        # Return None to skip further processing
        return None
    
    # UPDATE-ONLY MODE: Parse filename as ground truth
    if update_only:
        print(f"  Mode: Update library only (filename as ground truth)")
        
        # Get orientation
        orientation = analyze_image(file_path)
        print(f"  Orientation: {orientation}")
        
        # Parse filename to extract metadata
        parsed_metadata = extract_metadata_from_filename(file_path.name)
        parsed_metadata['orientation'] = orientation  # Use detected orientation
        
        print(f"  Parsed from filename:")
        print(f"    Artist: {parsed_metadata['artist']}")
        print(f"    Title: {parsed_metadata['title']}")
        print(f"    Year: {parsed_metadata['year']}")
        
        # Lookup additional metadata (like location) from Ollama if configured
        # Location is never in the filename, so always lookup if Ollama is available
        enriched_location = ''
        if 'ollama' in data_source_config and parsed_metadata['artist'] != 'Unknown' and parsed_metadata['title'] != 'Unknown':
            print(f"  Looking up additional metadata (location)...")
            # Use filename as search term, pass context with parsed metadata, and send image
            lookup_result = lookup_painting_info(file_path.name, file_path, ollama_host, ollama_api_key, language, context_info=parsed_metadata)
            if lookup_result and lookup_result.get('location'):
                enriched_location = lookup_result['location']
                print(f"    Found location: {enriched_location}")
        
        # Generate description based on parsed metadata (unless --no-description)
        description = ""
        description_max_length = config.get('description_max_length', 500)
        if not no_description and 'ollama' in data_source_config and parsed_metadata['artist'] != 'Unknown' and parsed_metadata['title'] != 'Unknown':
            description_style = config.get('description_style', '')
            # Include enriched location in description generation context
            description_context = {**parsed_metadata, 'location': enriched_location}
            description = generate_description(description_context, ollama_host, ollama_api_key, language, description_style, description_max_length)
        
        # Determine data_sources string based on data_source_config
        if 'ollama' in data_source_config:
            # Format Ollama model name nicely (capitalize, handle special cases)
            model_display = ollama_model.replace(':', ' ').title()
            data_sources_str = f'Ollama {model_display} LLM'
        else:
            data_sources_str = 'Filename (Ground Truth)'
        
        # Return metadata without modifying filename
        # Confidence is 1.0 for parsed filenames (ground truth)
        metadata = {
            'original_title': parsed_metadata['title'],  # Use title as original_title when parsing from filename
            'title': parsed_metadata['title'],
            'artist': parsed_metadata['artist'],
            'year': parsed_metadata['year'],
            'location': enriched_location,  # Use enriched location from lookup
            'orientation': orientation,
            'original_filename': file_path.name,
            'file_size': file_path.stat().st_size,
            'info_data_source': data_sources_str,
            'cached': False,
            'language': language,
            'naming_format_used': naming_format,
            'data_sources_config': data_source_config,
            'confidence_score': 1.0,
            'file_path': library.relative_path(file_path),
            'confirmed': False,
            'descriptions': {}  # Descriptions last for easier debugging
        }
        
        # Only add description if it's valid (not empty and not a placeholder)
        if description and description.strip() and description.strip().lower() not in ['description not available.', 'description not available']:
            ollama_model = config.get('ollama_model', 'kimi-k2.5:cloud')
            description_entry = {
                'description': description,
                'language': language,
                'description_style': config.get('description_style', 'engaging and informative'),
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'comment_creator': f'ollama:{ollama_model}',
                'max_length': description_max_length
            }
            metadata['descriptions'][language] = [description_entry]
        
        return metadata
    
    # NORMAL MODE: Continue with existing logic
    data_sources = [source.strip().lower() for source in data_source_config.split(',')]
    
    # Check if we have this painting cached in the library (check by potential title/artist from filename)
    cached_entry = None  # Caching disabled for now since we identify by title+artist not filename
    
    # Get force reprocess flag from main
    force_reprocess = config.get('_force_reprocess', False)
    
    if cached_entry and not force_reprocess:
        should_reprocess = library.should_reprocess(
            cached_entry, 
            language, 
            naming_format, 
            data_source_config
        )
        
        if not should_reprocess:
            print(f"  ✓ Using cached data (language: {language}, no changes detected)")
            
            # Analyze orientation (quick, always do this)
            orientation = analyze_image(file_path)
            
            # Return cached data with updated orientation
            metadata = {
                'title': cached_entry.get('title', 'Unknown'),
                'artist': cached_entry.get('artist', 'Unknown'),
                'year': cached_entry.get('year', 'Unknown'),
                'location': cached_entry.get('location', ''),
                'orientation': orientation,
                'description': cached_entry.get('description', ''),
                'original_filename': file_path.name,
                'file_size': file_path.stat().st_size,
                'data_sources': cached_entry.get('data_sources', 'Cached'),
                'cached': True,
                'language': language,
                'naming_format_used': naming_format,
                'data_sources_config': data_source_config
            }
            
            # Keep Wikipedia URL if available
            if cached_entry.get('wikipedia_url'):
                metadata['wikipedia_url'] = cached_entry['wikipedia_url']
            
            return metadata
        else:
            print(f"  ⟳ Reprocessing (language or config changed)")
    
    # Not cached or needs reprocessing - do full lookup
    # Clean filename for better search results - returns list of terms to try
    search_terms = clean_filename_for_search(file_path.name)
    print(f"  Search terms: {' -> '.join(search_terms)}")
    
    # Process each data source in sequence, each enhancing the previous
    painting_info = None
    
    # Get Gemini API key from config if gemini is in data sources
    gemini_api_key = config.get('gemini_api_key', '') if 'gemini' in data_sources else None
    gemini_rate_limit = config.get('gemini_requests_per_minute', 15)
    
    # Analyze image
    orientation = analyze_image(file_path)
    print(f"  Orientation: {orientation}")
    width, height = get_image_dimensions(file_path)
    
    for idx, source in enumerate(data_sources):
        if source == "gemini":
            print(f"  {'Querying' if idx == 0 else 'Enhancing with'} Gemini Vision...")
            description_style = config.get('description_style', '') if not no_description else ''
            description_max_length = config.get('description_max_length', 500) if not no_description else 0
            gemini_model = config.get('gemini_model', 'gemini-2.5-flash')
            gemini_daily_limit = config.get('gemini_requests_per_day', -1)
            gemini_result = lookup_painting_gemini(
                file_path, gemini_api_key, language, gemini_rate_limit, gemini_daily_limit,
                description_style, description_max_length, gemini_model
            )
            
            if gemini_result:
                if painting_info:
                    # Merge/enhance existing info with Gemini data
                    painting_info = merge_painting_info(painting_info, gemini_result, prefer_source='gemini')
                else:
                    painting_info = gemini_result
            elif idx == 0:
                print("  ⚠ No results from Gemini")
                
        elif source == "ollama":
            print(f"  {'Querying' if idx == 0 else 'Enhancing with'} Ollama...")
            
            # Get description settings and rate limits
            description_style = config.get('description_style', '')
            description_max_length = config.get('description_max_length', 500)
            ollama_rate_limit = config.get('ollama_requests_per_minute', 60)
            ollama_daily_limit = config.get('ollama_requests_per_day', -1)
            
            # If we have previous info, pass it to Ollama for enhancement
            context_info = painting_info if painting_info else None
            ollama_result = lookup_painting_info(
                file_path.stem,
                file_path,  # Pass image path for vision analysis
                ollama_host, 
                ollama_api_key, 
                language,
                context_info=context_info,
                search_terms=search_terms,
                description_style=description_style,
                description_max_length=description_max_length,
                requests_per_minute=ollama_rate_limit,
                requests_per_day=ollama_daily_limit
            )
            
            if ollama_result:
                if painting_info:
                    # Merge/enhance existing info with Ollama data
                    painting_info = merge_painting_info(painting_info, ollama_result, prefer_source='ollama')
                else:
                    painting_info = ollama_result
            elif idx == 0:
                print("  ⚠ No results from Ollama")
        else:
            print(f"  ⚠ Warning: Unknown data source '{source}'")
    
    if not painting_info:
        print(f"  ⚠ Could not find information for: {file_path.name}")
        print(f"     (tried: {' → '.join(search_terms)})")
        return None
    
    # Normalize year to strict AAAA format
    if painting_info.get('year') and painting_info['year'] != 'Unknown':
        normalized_year = normalize_year(painting_info['year'])
        if normalized_year:
            painting_info['year'] = normalized_year
            print(f"  Normalized year to: {normalized_year}")
        else:
            painting_info['year'] = 'Unknown'
    
    # Check confidence score
    confidence = painting_info.get('confidence_score', 1.0)
    
    if confidence < 0.5:
        print(f"  ⚠ LOW CONFIDENCE: {confidence:.2f} - result may be unreliable")
    elif confidence < 0.8:
        print(f"  ⚠ MODERATE CONFIDENCE: {confidence:.2f}")
    
    print(f"  Found: {painting_info.get('title', 'Unknown')} by {painting_info.get('artist', 'Unknown')}")
    
    # Generate description using Ollama if it's in the data sources list (unless --no-description)
    description = ""
    if not no_description and "ollama" in data_sources:
        description_style = config.get('description_style', '')
        description_max_length = config.get('description_max_length', 500)
        description = generate_description(painting_info, ollama_host, ollama_api_key, language, description_style, description_max_length)
    elif painting_info.get('wiki_extract'):
        # Use Wikipedia extract as description
        description = painting_info.get('wiki_extract', 'Description not available.')
    else:
        description = painting_info.get('description', 'Description not available.')
    
    # Use combined description if available
    if painting_info.get('description_combined'):
        description = painting_info['description_combined']
    
    # Combine all metadata with new structure
    # Priority: generated description > combined > painting_info description
    description_text = ""
    if description:  # Use newly generated description first
        description_text = description
    elif painting_info.get('description_combined'):
        description_text = painting_info['description_combined']
    elif painting_info.get('description'):
        description_text = painting_info['description']
    
    # Determine creator based on data source
    data_source = painting_info.get('source', 'Unknown')
    
    metadata = {
        'original_title': painting_info.get('original_title', painting_info.get('title', 'Unknown')),
        'title': painting_info.get('title', 'Unknown'),
        'artist': painting_info.get('artist', 'Unknown'),
        'year': painting_info.get('year', 'Unknown'),
        'location': painting_info.get('location', ''),
        'confidence_score': confidence,
        'orientation': orientation,
        'info_data_source': painting_info.get('sources_used', painting_info.get('source', 'Unknown')),
        'file_size': file_path.stat().st_size,
        'file_width': width,
        'file_height': height,
        'file_path': library.relative_path(file_path),
        'confirmed': False,
        'periods': painting_info.get('periods', []),
        'themes': painting_info.get('themes', []),
        'status': 'ready',
        'descriptions': {}  # Descriptions last for easier debugging
    }
    
    # Only add description if it's valid (not empty and not a placeholder)
    if description_text and description_text.strip() and description_text.strip().lower() not in ['description not available.', 'description not available']:
        new_description_entry = {
            'description': description_text,
            'language': language,
            'description_style': config.get('description_style', 'engaging and informative'),
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'comment_creator': data_source,
            'max_length': config.get('description_max_length', 500)
        }
        metadata['descriptions'][language] = [new_description_entry]
    
    return metadata


def main():
    """Main execution function."""
    ensure_runs_on_nas()
    # Load configuration
    config = ConfigManager()
    
    parser = argparse.ArgumentParser(
        description='Rename painting images with complete metadata and build a library.'
    )
    parser.add_argument(
        'folder',
        nargs='?',
        default=str(config.get_path('default_folder')),
        help='File or folder containing painting image(s) (default: from config.json or current folder)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually renaming files'
    )
    parser.add_argument(
        '--force-reprocess',
        action='store_true',
        help='Force reprocessing all files, ignoring cache'
    )
    parser.add_argument(
        '--update-library-only',
        action='store_true',
        help='Update library only - parse existing filenames as ground truth, query for descriptions, do not rename files'
    )
    parser.add_argument(
        '--no-description',
        action='store_true',
        help='Skip description generation - only collect metadata (title, artist, year, etc.)'
    )
    parser.add_argument(
        '--only-location',
        action='store_true',
        help='Only update location field for existing paintings in library (no renaming, no descriptions)'
    )
    parser.add_argument(
        '--only-comment',
        action='store_true',
        help='Generate only descriptions for existing library entries (no identification, no renaming)'
    )
    parser.add_argument(
        '--result-json',
        metavar='FILE',
        help='Write a JSON summary of the processed files (used by the web upload API)'
    )
    
    args = parser.parse_args()
    
    # Validate path (can be file or folder)
    target_path = Path(args.folder).resolve()
    if not target_path.exists():
        print(f"Error: Path '{target_path}' does not exist.")
        sys.exit(1)
    
    # Determine if processing single file or folder
    if target_path.is_file():
        # Single file mode
        print(f"Processing single file: {target_path.name}")
        image_files = [target_path]
        folder_path = target_path.parent
    elif target_path.is_dir():
        # Folder mode
        print(f"Scanning folder: {target_path}")
        folder_path = target_path
        image_files = get_image_files(folder_path)
        if not image_files:
            print("No image files found in the specified folder.")
            sys.exit(0)
    else:
        print(f"Error: '{target_path}' is neither a file nor a directory.")
        sys.exit(1)
    
    # Get force reprocess flag
    if args.force_reprocess:
        print("⚠ Force reprocess enabled - ignoring cache")
    
    # Get update-only mode flag
    if args.update_library_only:
        print("📚 Update Library Only mode - filenames are ground truth, no renaming")
        print("   Will query for descriptions and update library JSON only")
    
    print(f"Found {len(image_files)} image file(s).")
    
    # Initialize library manager with centralized path
    config = ConfigManager()
    
    # Validate Ollama connection if it's in data sources
    data_sources = [s.strip().lower() for s in config.get('data_source', 'gemini').split(',')]
    if 'ollama' in data_sources:
        ollama_host = config.get('ollama_host', 'http://192.168.1.3:11434')
        ollama_model = config.get('ollama_model', 'llama3.2')
        ollama_api_key = config.get('ollama_api_key')
        if not validate_ollama_connection(ollama_host, ollama_model, ollama_api_key):
            print("\n⚠ Ollama validation failed. Cannot proceed with processing.")
            print("   Fix the issues above and try again.")
            sys.exit(1)
        print()  # Empty line for spacing
    
    # Continue with library initialization
    library_path = config.get_path('library_path')
    library_file = config.get('library_file', 'painting_library.json')
    library = LibraryManager(
        config.get_path('database_path', '../data/cuadros.sqlite'),
        paintings_dir=library_path,
        export_path=library_path / library_file,
    )
    
    # Set confidence to 1.0 for all confirmed entries
    updated_count = 0
    for painting in library.paintings:
        if painting.get('confirmed', False) and painting.get('confidence_score', 0) != 1.0:
            painting['confidence_score'] = 1.0
            updated_count += 1
    
    if updated_count > 0:
        library.save()
        print(f">> Updated confidence to 1.0 for {updated_count} confirmed painting(s)")
    
    # Smart file ordering when processing folders:
    # 1. Files not in library (priority)
    # 2. Files with oldest description timestamps
    # 3. Files with recent descriptions
    if target_path.is_dir():
        def get_file_priority(file_path):
            """Return tuple for sorting: (has_entry, oldest_timestamp_or_inf)"""
            # Check if file exists in library by checking all possible titles
            painting = None
            for entry in library.paintings:
                # Simple check: if any description mentions file name parts
                if entry.get('title', '').lower() in file_path.stem.lower():
                    painting = entry
                    break
            
            if painting is None:
                # File not in library - highest priority (process first)
                return (0, 0)
            
            # File exists - check oldest description timestamp
            descriptions = painting.get('descriptions', {})
            if not descriptions:
                return (1, 0)  # Has entry but no descriptions
            
            # Find oldest timestamp (descriptions are now arrays)
            oldest_timestamp = float('inf')
            for lang_desc_list in descriptions.values():
                # Handle both old format (dict) and new format (list)
                if isinstance(lang_desc_list, list):
                    # New format: array of descriptions
                    for desc_entry in lang_desc_list:
                        generated_at = desc_entry.get('generated_at')
                        if generated_at:
                            try:
                                ts = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
                                oldest_timestamp = min(oldest_timestamp, ts.timestamp())
                            except:
                                pass
                else:
                    # Old format: single dict (for retrocompatibility)
                    generated_at = lang_desc_list.get('generated_at')
                    if generated_at:
                        try:
                            ts = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
                            oldest_timestamp = min(oldest_timestamp, ts.timestamp())
                        except:
                            pass
            
            return (1, oldest_timestamp if oldest_timestamp != float('inf') else 0)
        
        # Sort files: not in library first, then by oldest description
        image_files = sorted(image_files, key=get_file_priority)
        print(">> Files prioritized: new files first, then by oldest descriptions")
    
    # Pass force_reprocess flag through config (temporary)
    config.set('_force_reprocess', args.force_reprocess)
    
    # Process and rename each image immediately
    reviewed_count = 0
    renamed_count = 0
    skipped_confirmed_count = 0
    daily_limit_reached = False
    ollama_host = config.get('ollama_host', 'http://192.168.1.3:11434')
    ollama_api_key = config.get('ollama_api_key')
    
    # Check if we should process confirmed paintings
    # Skip confirmed paintings in normal mode to save API calls
    # Process them only with special modifiers
    process_confirmed = args.update_library_only or args.only_location or args.only_comment
    results = []
    
    for file_path in image_files:
        # Check if painting is already in library and confirmed
        if not process_confirmed:
            existing_painting = None
            for entry in library.paintings:
                if entry.get('file_path', '').endswith(file_path.name) or entry.get('original_filename') == file_path.name:
                    existing_painting = entry
                    break
            
            if existing_painting and existing_painting.get('confirmed', False):
                print(f"\nSkipping: {file_path.name}")
                print(f"  [LOCKED] Entry confirmed - no processing needed (use --only-location, --only-comment, or --update-library-only to update)")
                skipped_confirmed_count += 1
                results.append({'file': file_path.name, 'status': 'skipped_confirmed',
                                'id': existing_painting.get('id'),
                                'file_path': existing_painting.get('file_path')})
                continue
        
        try:
            metadata = process_painting(
                file_path,
                library,
                ollama_host,
                ollama_api_key,
                update_only=args.update_library_only,
                no_description=args.no_description,
                only_location=args.only_location,
                only_comment=args.only_comment
            )
        except (GeminiDailyLimitReached, OllamaDailyLimitReached) as e:
            daily_limit_reached = True
            print(f"\n⚠ Daily API limit reached. Stopping processing.")
            print(f"   Remaining files will be processed when the limit resets (UTC midnight).")
            results.append({'file': file_path.name, 'status': 'daily_limit'})
            break
        
        if not metadata and not args.only_comment:
            results.append({'file': file_path.name, 'status': 'failed'})
        
        if metadata:
            # Add to library
            library.add_painting(metadata)
            library.save()
            print(f"  [OK] Library updated")
            reviewed_count += 1
            
            # Rename file immediately (unless in update-only mode, only-comment, or dry-run)
            # Also skip if entry is marked as confirmed (user-verified)
            is_confirmed = metadata.get('confirmed', False)
            if not args.update_library_only and not args.only_comment and not args.dry_run and not is_confirmed:
                naming_format = config.get('naming_format')
                is_low_confidence = metadata.get('low_confidence', False)
                
                # Prepare data for filename generation
                title = metadata.get('title', 'Unknown')
                artist = metadata.get('artist', 'Unknown')
                year = metadata.get('year', 'Unknown')
                orientation = metadata.get('orientation', 'landscape')
                extension = file_path.suffix
                location = ""  # Location field removed from new library structure
                
                new_filename = create_new_filename(
                    title, artist, year, location, orientation, extension,
                    is_duplicate=False, naming_format=naming_format, 
                    is_low_confidence=is_low_confidence
                )
                
                if file_path.name == new_filename:
                    print(f"  [OK] Filename already correct: {file_path.name}")
                else:
                    new_path = rename_file(file_path, new_filename)
                    if new_path:
                        print(f"  [OK] Renamed: {file_path.name}")
                        print(f"    To: {new_path.name}")
                        # Update file_path in metadata to reflect new name
                        metadata['file_path'] = library.relative_path(new_path)
                        library.update_painting_path(metadata, str(new_path))
                        library.save()  # Save again after updating path
                        renamed_count += 1
            elif is_confirmed:
                print(f"  [OK] Skipped rename (entry confirmed by user)")
            
            results.append({
                'file': file_path.name,
                'status': 'processed',
                'id': metadata.get('id'),
                'file_path': metadata.get('file_path'),
                'title': metadata.get('title'),
                'artist': metadata.get('artist'),
                'year': metadata.get('year'),
                'confidence_score': metadata.get('confidence_score'),
            })
    
    if args.result_json:
        with open(args.result_json, 'w', encoding='utf-8') as f:
            json.dump({'results': results, 'daily_limit_reached': daily_limit_reached}, f, indent=2, ensure_ascii=False)
    
    # Summary message
    print(f"\n[DONE] Reviewed {reviewed_count} painting(s)")
    if skipped_confirmed_count > 0:
        print(f"       Skipped {skipped_confirmed_count} confirmed painting(s)")
    if renamed_count > 0:
        print(f"       Renamed {renamed_count} file(s)")


if __name__ == '__main__':
    try:
        with library_lock():
            main()
    except KeyboardInterrupt:
        print("\n\n⚠ Process interrupted by user (Ctrl+C)")
        print("Library has been saved up to the last processed painting.")
        print("Exiting gracefully...")
        sys.exit(0)

