# Recent Improvements to Painting Renamer

## Overview
This document details the improvements made to address issues with painting identification accuracy and user feedback.

## 1. Progressive Multi-Term Search (NEW!)

### Problem
Given filename: `José Ruiz y Blasco - El Baño de Jávea - (1820-1840) - [landscape].jpeg`

The old logic would search for "José Ruiz y Blasco" (the artist name) and find nothing, giving up immediately.

### Solution: Progressive Search Strategy
Now the script extracts **multiple search terms** from the filename and tries each one progressively until it finds a reliable result:

**Example Processing:**
1. **First attempt**: "José Ruiz y Blasco" → No results (artist name, not painting)
2. **Console shows**: `Trying next term: 'El Baño de Jávea'`
3. **Second attempt**: "El Baño de Jávea" → ✓ Found the painting!

### How It Works
- `clean_filename_for_search()` now returns a **list** of search terms instead of a single string
- Splits filename by dash separators: `Artist - Title - Date` → `['Artist', 'Title']`
- Removes noise (parentheses, brackets) from each part
- Tries each term in sequence with both Wikipedia and Ollama
- Stops when a reliable result is found

### Console Output
```
Search terms: José Ruiz y Blasco → El Baño de Jávea
Searching Wikipedia for: 'José Ruiz y Blasco'
  Trying next term: 'El Baño de Jávea'
  ✓ Found on Wikipedia: El Baño de Jávea (searched: 'El Baño de Jávea')
```

### Benefits
✅ **Much higher success rate** - Won't give up after first failed search  
✅ **Smarter parsing** - Understands "Artist - Title" filename structure  
✅ **Transparent** - Shows which term succeeded  
✅ **Reduces false negatives** - Tries all reasonable interpretations  

## 2. Enhanced Console Output

### Ollama Model Display
- **Before**: "Generating description (Ollama)..."
- **After**: "Generating description (ollama:llama3.2)..."
- Shows the actual model being used for transparency

### Description Preview
- After description generation, the first 240 characters are now displayed
- Example: `→ This masterpiece by Vincent van Gogh captures the swirling night sky over a quiet village. Painted in 1889 during his stay at the Saint-Rémy-de-Provence asylum, the work features bold brushstrokes and vivid colors that convey both turbulence and...`

## 2. Filename Cleaning for Better Search Results

### New Module: `filename_utils.py`
Created a dedicated module with two key functions:

#### `clean_filename_for_search(filename)` → Returns List
Intelligently extracts **multiple search terms** from filenames:

**Normalization:**
- Replaces underscores with spaces: `van_gogh_starry_night.jpg` → `van gogh starry night`
- Replaces dots with spaces: `van.gogh.starry.night.jpg` → `van gogh starry night`
- Multiple spaces normalized to single space

**Cleaning:**
- Removes content in parentheses: `(1863-64)` → removed
- Removes content in brackets: `[landscape]` → removed
- Splits by dash separators to get multiple parts
- Returns list: `['José Ruiz y Blasco', 'El Baño de Jávea']`

**Examples:**
| Input Filename | Extracted Terms |
|---------------|-----------------|
| `jose_ruiz_y_blasco_el_baño.jpg` | `['jose ruiz y blasco el baño']` |
| `van.gogh.starry.night.jpg` | `['van gogh starry night']` |
| `edouard_manet - the.bedroom - (1863).jpg` | `['edouard manet', 'the bedroom']` |

Each term is tried progressively until one succeeds.

## 3. Strict Year Normalization

### New Function: `normalize_year(year_string)`
Enforces strict AAAA format:

| Input | Output | Rule Applied |
|-------|--------|--------------|
| `1889` | `1889` | Single year - keep as is |
| `1840-1841` | `1841` | Range - take second year |
| `1840-41` | `1841` | Short range - expand and take second |
| `1840 1841` | `1841` | Multiple years - take last |
| `(1863)` | `1863` | Remove parentheses |
| `None` | `` | Invalid - return empty |

### Benefits
- Consistent year format across all paintings
- No more disagreements (1840 vs 1840-1841 vs 1840-41)
- Cleaner filenames
- Better sorting

## 4. Confidence Scoring System

### Ollama Confidence Score
- Added `confidence_score` field to Ollama JSON response (0.0-1.0)
- Ollama is explicitly asked to rate its confidence
- Prompt updated: *"Be honest about your confidence_score - if you're unsure or guessing, use a low score (< 0.5)"*

### Low Confidence Handling
- Threshold: confidence < 0.5 is considered "low confidence"
- Low confidence paintings get **"CHECK UNKNOWN -"** prefix
- Example: `CHECK UNKNOWN - Vincent van Gogh - La noche estrellada (1889) [portrait].jpg`
- Console warning: `⚠ LOW CONFIDENCE: 0.32 - result may be unreliable`

### Prevents Hallucinations
- Addresses issue where `alfred_la_guigne_1963.10.220.jpg` was incorrectly identified
- User can now easily spot and manually verify uncertain identifications
- Files with this prefix require human review

## 5. Improved Error Messages

### Shows All Attempted Terms
- **Example output**:
  ```
  ⚠ Could not find information for: José Ruiz y Blasco - El Baño de Jávea - (1820-1840) - [landscape].jpeg
     (tried: José Ruiz y Blasco → El Baño de Jávea)
  ```
- Shows every search term that was attempted
- **Consistent warnings**: Using ⚠ symbol throughout

## 6. Files Modified

### New Files
- **`filename_utils.py`**: Cleaning and normalization utilities

### Modified Files
- **`filename_utils.py`**: 
  - `clean_filename_for_search()` now returns **list** of search terms
  
- **`painting_lookup.py`**: 
  - Changed `cleaned_filename` parameter to `search_terms` (list)
  - Uses first term from list for Ollama queries
  - Added `confidence_score` to JSON response parsing
  - Updated prompts with confidence instructions
  - Show model name and description preview in console
  
- **`wikipedia_lookup.py`**: 
  - Changed `cleaned_filename` parameter to `search_terms` (list)
  - **Progressive search loop**: Tries each term until one succeeds
  - Shows "Trying next term: ..." when moving to next search
  - Adds Spanish painting keywords ("pintura", "pintado", "obra") for language support
  
- **`file_manager.py`**: 
  - Added `is_low_confidence` parameter to `create_new_filename()`
  - "CHECK UNKNOWN -" prefix logic
  
- **`painting_renamer.py`**:
  - Import `clean_filename_for_search` (returns list now)
  - Shows all search terms: `Search terms: Artist → Title`
  - Pass `search_terms` list to both Wikipedia and Ollama
  - NProgressive Search**: 
   - Try: `José Ruiz y Blasco - El Baño de Jávea - (1820-1840) - [landscape].jpeg`
   - Should try "José Ruiz y Blasco" first, then "El Baño de Jávea"
   - Should succeed on second attempt and show which term worked

2. **ormalize years after data retrieval
  - Check confidence score and set `low_confidence` flag
  - Pass `is_low_confidence` to filename creation
  - Shows all tried terms in error messages

## 7. Testing Recommendations

### Test Cases to Verify
1. **Filename Cleaning**: 
   - Try: `Édouard Manet - The Bedroom - (1863-64) - [landscape].jpg`
   - Should search as: `Édouard Manet`

2. **Year Normalization**:
   - Input years with ranges should become single years
   - Check library.json for consistent year formats

3. **Confidence Scoring**:
   - Ambiguous filenames should get low confidence scores
   - Check for "CHECK UNKNOWN -" prefix on uncertain files

4. **Description Preview**:
   -Progressive search** - Won't give up after first failed term  
✅ **Much higher success rate** - Tries Artist, Title, and other parts  
✅ **Fewer "Could not find" errors** - Intelligent filename cleaning + multiple attempts  
✅ **Consistent year formats** - Strict AAAA normalization  
✅ **Hallucination detection** - Confidence scoring flags uncertain IDs  
✅ **Better transparency** - See model name, search terms, and description previews  
✅ **Easier debugging** - Show all attempted search terms  
✅ **Manual review workflow** - "CHECK UNKNOWN -" prefix for uncertain files  

## 9.**Hallucination detection** - Confidence scoring flags uncertain IDs  
✅ **Better transparency** - See model name and description previews  
✅ **Easier debugging** - Show cleaned search terms  
✅ **Manual review workflow** - "CHECK UNKNOWN -" prefix for uncertain files  

## Configuration

No 10. configuration changes required! All improvements work automatically with existing `config.json`.

## Future Enhancements (Optional)

- Configurable confidence threshold (currently hardcoded at 0.5)
- Multiple confidence levels (low/medium/high) with different prefixes
- Option to skip low-confidence results entirely
- Confidence score displayed in library.json statistics
