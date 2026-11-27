# Configuration Examples

## Wikipedia First, Ollama Enhancement (Recommended)
```json
{
  "ollama_host": "http://192.168.1.3:11434",
  "api_key": null,
  "library_file": "painting_library.json",
  "ollama_model": "llama3.2",
  "default_folder": ".",
  "data_source": "wikipedia,ollama",
  "naming_format": "%artist% - %title% (%year%) [%orientation%]",
  "language": "es"
}
```
- Queries Wikipedia first for accurate facts
- Passes Wikipedia results to Ollama
- Ollama validates, translates, and generates rich descriptions with context
- Best of both worlds!

## Ollama First, Wikipedia Validation
```json
{
  "ollama_host": "http://192.168.1.3:11434",
  "api_key": "your_api_key_here",
  "library_file": "painting_library.json",
  "ollama_model": "llama3.2",
  "default_folder": ".",
  "data_source": "ollama,wikipedia",
  "naming_format": "%artist% - %title% (%year%) [%orientation%]",
  "language": "es"
}
```
- Queries Ollama first for initial identification
- Passes Ollama results to Wikipedia for validation
- Wikipedia adds references and confirms accuracy
- Good if you trust your LLM's knowledge

## Wikipedia Only (Free, No Auth)
```json
{
  "data_source": "wikipedia",
  "language": "es"
}
```
- No Ollama needed
- Wikipedia descriptions only

## Ollama Only
```json
{
  "data_source": "ollama",
  "ollama_host": "http://ai.ggonmar.com:11434",
  "api_key": "your_key",
  "ollama_model": "mistral"
}
```
- No Wikipedia
- Pure LLM approach

## Spanish Language with Wikipedia
```json
{
  "data_source": "wikipedia",
  "naming_format": "%artist% - %title% (%year%) [%orientation%]",
  "language": "es"
}
```
Result: `Vincent van Gogh - La noche estrellada (1889) [landscape].jpg`

## Different Ollama Models
```json
{
  "ollama_model": "mistral",
  "data_source": "ollama"
}
```
Or use `llama3.1`, `mixtral`, `codellama`, etc.

## English (Default)
```json
{
  "data_source": "wikipedia,ollama",
  "language": "en"
}
```

## Future: Multiple Data Sources
The comma-separated format allows for easy expansion:
```json
{
  "data_source": "wikipedia,ollama,google,custom_api"
}
```
Try sources in order until one succeeds!

## Custom Naming Formats

### Simple Format (Title - Artist)
```json
{
  "naming_format": "%painting% - %painter%"
}
```
Result: `The Starry Night - Vincent van Gogh.jpg`

### Year First
```json
{
  "naming_format": "(%year%) %title% by %artist%"
}
```
Result: `(1889) The Starry Night by Vincent van Gogh.jpg`

### Minimal (Just Title and Year)
```json
{
  "naming_format": "%title% (%year%)"
}
```
Result: `The Starry Night (1889).jpg`

### With Custom Separators
```json
{
  "naming_format": "%artist% · %title% · %year% · %location%"
}
```
Result: `Vincent van Gogh · The Starry Night · 1889 · Museum of Modern Art.jpg`

### Artist/Title Only (No Metadata)
```json
{
  "naming_format": "%painter% - %painting%"
}
```
Result: `Vincent van Gogh - The Starry Night.jpg`

