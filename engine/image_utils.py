"""
Image Utilities Module
Handles image analysis such as determining orientation (landscape/portrait).
"""

from pathlib import Path
from PIL import Image
from typing import Tuple


def get_image_dimensions(file_path: Path) -> Tuple[int, int]:
    """
    Get image dimensions (width, height).
    
    Args:
        file_path: Path to the image file
        
    Returns:
        Tuple of (width, height)
    """
    try:
        with Image.open(file_path) as img:
            return img.size
    except Exception as e:
        print(f"  ⚠ Could not read image dimensions: {e}")
        return (0, 0)


def analyze_image(file_path: Path) -> str:
    """
    Analyze an image and determine its orientation.
    
    Args:
        file_path: Path to the image file
        
    Returns:
        'landscape', 'portrait', or 'square'
    """
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            
            if width > height:
                return 'landscape'
            elif height > width:
                return 'portrait'
            else:
                return 'square'
    except Exception as e:
        print(f"  Warning: Could not analyze image {file_path.name}: {e}")
        return 'unknown'


def get_image_dimensions(file_path: Path) -> tuple:
    """
    Get the dimensions of an image.
    
    Args:
        file_path: Path to the image file
        
    Returns:
        Tuple of (width, height) or (0, 0) if error
    """
    try:
        with Image.open(file_path) as img:
            return img.size
    except Exception as e:
        print(f"  Warning: Could not get dimensions for {file_path.name}: {e}")
        return (0, 0)
