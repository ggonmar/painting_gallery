"""
Configuration Manager Module
Handles loading and creating configuration files.
"""

import json
from pathlib import Path
from typing import Dict, Any


DEFAULT_CONFIG = {
    "ollama_host": "http://192.168.1.3:11434",
    "ollama_api_key": None,
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",  # Gemini model: "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash", etc.
    "gemini_requests_per_minute": 15,  # Rate limit for Gemini API to avoid hitting quotas
    "gemini_requests_per_day": 1000,  # Daily rate limit for Gemini API (set to -1 for unlimited)
    "ollama_requests_per_minute": 60,  # Rate limit for Ollama requests (default: 60/min)
    "ollama_requests_per_day": -1,  # Daily rate limit for Ollama (set to -1 for unlimited)
    "library_file": "painting_library.json",
    "library_path": ".",  # Centralized path for library.json (e.g., "W:\\cuadros")
    "ollama_model": "llama3.2",
    "default_folder": ".",
    "data_source": "gemini",  # Comma-separated priority: "gemini", "ollama", or combination
    "naming_format": "%artist% - %title% (%year%) %location% [%orientation%]",
    "language": "en",  # Language code: "en", "es", "fr", "de", "it", etc.
    "description_max_length": 500,  # Maximum words in description (roughly 3-4 paragraphs)
    "description_style": "engaging and informative"  # Style keywords: "funny", "serious", "technical", "ethereal", "poetic", "academic", etc.
}


class ConfigManager:
    """Manages configuration file for the painting renamer."""
    
    def __init__(self, config_path: Path = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_path: Path to the configuration file (default: config.json in script dir)
        """
        if config_path is None:
            # Use config.json in the same directory as the script
            self.config_path = Path(__file__).parent / "config.json"
        else:
            self.config_path = Path(config_path)
        
        self.config = self.load()
    
    def load(self) -> Dict[str, Any]:
        """
        Load configuration from file or create default if not exists.
        
        Returns:
            Dictionary with configuration settings
        """
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge with defaults to ensure all keys exist; ai_settings.json (chosen from the web) wins
                    return {**DEFAULT_CONFIG, **config, **self._ai_settings()}
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")
                print("Using default configuration.")
                return DEFAULT_CONFIG.copy()
        else:
            # Create default config file
            self.save(DEFAULT_CONFIG)
            print(f"Created default configuration file: {self.config_path}")
            return DEFAULT_CONFIG.copy()
    
    AI_SETTINGS_KEYS = ('data_source', 'ollama_model', 'gemini_model', 'description_style', 'description_max_length')

    def _ai_settings(self) -> Dict[str, Any]:
        """AI provider/model chosen by the superadmin in the web (api/settings.php)."""
        path = self.config_path.parent / 'ai_settings.json'
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return {k: v for k, v in data.items() if k in self.AI_SETTINGS_KEYS and v}
        except (OSError, ValueError):
            return {}

    def save(self, config: Dict[str, Any] = None):
        """
        Save configuration to file.
        
        Args:
            config: Configuration dictionary to save (uses current config if None)
        """
        if config is None:
            config = self.config
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save config file: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        return self.config.get(key, default)
    
    def get_path(self, key: str, default: str = '.') -> Path:
        """
        Get a configuration value as a path. Relative paths are resolved against the
        folder containing config.json, so the same config works on Windows and on the NAS.
        """
        path = Path(self.config.get(key) or default)
        if not path.is_absolute():
            path = self.config_path.parent / path
        return path.resolve()

    def set(self, key: str, value: Any):
        """
        Set a configuration value.
        
        Args:
            key: Configuration key
            value: Value to set
        """
        self.config[key] = value
    
    def update(self, updates: Dict[str, Any]):
        """
        Update multiple configuration values.
        
        Args:
            updates: Dictionary of key-value pairs to update
        """
        self.config.update(updates)
