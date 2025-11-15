# Scopus ID Extractor

## Overview

This Python script automates the process of extracting **Scopus IDs** (EIDs) from DOIs or article titles. It uses the **Scopus Developer API** as the primary source with **OpenAlex** as a fallback to retrieve titles and DOIs when Scopus data is unavailable.

The script is designed for users who:

* have a list of DOIs or titles and want to map them to Scopus internal IDs (EIDs)
* need a free, automated solution (Scopus API offers 5,000 requests/week on the free tier)
* want an automated, reproducible CSV output with checkpoints

---

## Features

- **Dual search modes**: Search by DOI or by title
- **Primary source**: Scopus Developer API (free tier: 5,000 requests/week)
- **Fallback source**: OpenAlex API (for title and DOI lookup only)
- **Data validation**: DOI format check and title length validation
- **Duplicate detection**: Finds and optionally removes duplicates
- **Response caching**: Stores successful results to avoid re-querying
- **Batch processing**: Parallel requests with rate limiting protection
- **Checkpoint saving**: Progress saved every 10 items with resume capability
- **Interrupt handling**: Graceful Ctrl+C support with data preservation
- **Secure API key storage**: API key stored locally in `.scopus_api_key` file
- **API key testing**: Verify your key works before processing

---

## Requirements

- Python 3.7+
- Required packages:

```bash
pip install pandas requests
```

- **Scopus API Key** (free): Register at [https://dev.elsevier.com](https://dev.elsevier.com)

---

## Scopus API Key Setup

### Getting Your Free API Key

1. Visit [https://dev.elsevier.com](https://dev.elsevier.com)
2. Create an account or log in
3. Navigate to "My API Key" section
4. Generate a new API key
5. Copy the key (you'll need it when running the script)

### First Run

The script will automatically prompt you for the API key on first run:

```bash
python scopus_id_extractor.py --doi
```

The key will be saved to `.scopus_api_key` and automatically added to `.gitignore`.

### Resetting Your API Key

```bash
python scopus_id_extractor.py --reset-key
```

---

## Input Files

Create one or both input files in the same directory as the script:

### For DOI Search: `dois.txt`

One DOI per line:

```
10.1016/j.celrep.2020.01.001
10.1109/CVPR.2016.90
10.1038/nature12345
```

### For Title Search: `titles.txt`

One title per line:

```
Deep Residual Learning for Image Recognition
CRISPR-Cas9 gene editing in human embryos
Machine learning applications in healthcare
```

---

## Usage

### Basic Commands

#### Search by DOI
```bash
python scopus_id_extractor.py --doi
```

#### Search by Title
```bash
python scopus_id_extractor.py --title
```

### Advanced Options

#### Limit Number of Items
```bash
python scopus_id_extractor.py --doi --limit 50
```

#### Resume from Last Checkpoint
```bash
python scopus_id_extractor.py --doi --resume
```

#### Skip Duplicate Entries
```bash
python scopus_id_extractor.py --doi --skip-duplicates
```

#### Parallel Processing (3 workers by default)
```bash
python scopus_id_extractor.py --doi --workers 5
```

#### Disable Cache
```bash
python scopus_id_extractor.py --doi --no-cache
```

#### Dry Run (Validation Only)
```bash
python scopus_id_extractor.py --doi --dry-run
```

### Utility Commands

#### Test API Key
```bash
python scopus_id_extractor.py --test-key
```

#### Reset API Key
```bash
python scopus_id_extractor.py --reset-key
```

#### Cache Statistics
```bash
python scopus_id_extractor.py --cache-stats
```

#### Clear Cache
```bash
python scopus_id_extractor.py --clear-cache
```

---

## Output

### Main Output: `scopus_results.csv`

#### For DOI searches:

| doi | title | scopus_id |
|-----|-------|-----------|
| 10.1016/... | Gene expression in XYZ | 2-s2.0-85012345678 |

#### For Title searches:

| search_title | found_title | scopus_id | doi |
|--------------|-------------|-----------|-----|
| Deep Learning... | Deep Residual Learning... | 2-s2.0-84986281884 | 10.1109/... |

### Checkpoint File: `checkpoint.json`

Enhanced JSON format with metadata:
```json
{
  "metadata": {
    "search_mode": "doi",
    "total_items": 100,
    "last_processed_index": 25,
    "timestamp": "2024-11-15T10:30:00"
  },
  "results": [...]
}
```

Automatically saved every 10 items. Use `--resume` to continue from checkpoint.

### Validation Report: `validation_report.txt`

Generated when invalid entries or duplicates are detected:
```
============================================================
VALIDATION REPORT
============================================================
Search mode: DOI
Total items: 100
Valid items: 95
Invalid items: 3
Unique items: 92
Duplicates: 3

INVALID ITEMS:
------------------------------------------------------------
Line 15: Invalid DOI format: 10.invalid
  → 10.invalid

DUPLICATE ITEMS:
------------------------------------------------------------
Line 45: Duplicate of line 12
  → 10.1016/j.cell.2020.01.001
```

### Cache File: `.scopus_cache.json`

Stores successful API responses:
```json
{
  "10.1016/j.cell.2020.01.001": {
    "title": "Gene expression...",
    "scopus_id": "2-s2.0-85012345678",
    "source": "scopus",
    "cached_at": "2024-11-15T10:30:00"
  }
}
```

---

## Workflow

### Standard Workflow

1. **Preparation**: Create `dois.txt` or `titles.txt` with your items
2. **Validation**: Script validates format and detects duplicates
3. **Processing**: Queries Scopus API (with OpenAlex fallback)
4. **Caching**: Successful results cached for future use
5. **Checkpoint**: Progress saved every 10 items
6. **Output**: Results saved to `scopus_results.csv`

### With Resume

1. Run script normally
2. If interrupted (Ctrl+C or error), checkpoint is saved
3. Run with `--resume` flag to continue from last position
4. Previously processed items are loaded from checkpoint
5. Only remaining items are processed

### Data Validation Process

**For DOI Search:**
1. Check DOI matches pattern: `10.XXXX/...`
2. Skip empty or malformed DOIs
3. Detect duplicates (case-insensitive)
4. Generate validation report if issues found

**For Title Search:**
1. Check title length (minimum 10 characters)
2. Skip empty titles
3. Detect duplicates (case-insensitive)
4. Generate validation report if issues found

---

## Console Output Example

```
============================================================
DOI/Title to Scopus ID Extractor
============================================================
Mode: DOI
Primary: Scopus API (FREE tier)
Fallback: OpenAlex (title/DOI lookup only)
Cache: Enabled
Workers: 3

✅ Loaded 100 items

🔍 Validating input...
   Valid: 97/100
   Invalid: 2
   Duplicates: 1
📝 Validation report saved to validation_report.txt
   ⚠️ 2 invalid items will be skipped
   ✅ Using 96 unique items (removed 1 duplicate)

🚀 Processing 96 items...

[1/96] DOI: 10.1016/j.celrep.2020.01.001
    🔍 Scopus API...
    ✅ Title: Gene expression dynamics in XYZ...
    ✅ Scopus ID: 2-s2.0-85012345678

[2/96] DOI: 10.1016/j.cell.2019.12.001
    💾 Cached result
    ✅ Title: CRISPR applications...
    ✅ Scopus ID: 2-s2.0-85012345679

[10/96] DOI: 10.1234/unknown.doi
    🔍 Scopus API...
    🔄 Fallback to OpenAlex (title only)...
    ✅ Title: Unknown article title...
    ⚠️ Scopus ID not found

    💾 Checkpoint: 10/96 | Found: 8/10

...

✅ Results saved to scopus_results.csv

============================================================
SUMMARY
============================================================
Search mode: DOI
Total: 96 | Found: 87 | Not found: 9
Success rate: 90.6%
API requests: 150
Cache hits: 25
Errors: 9
============================================================
```

---

## Error Handling

- **401 Unauthorized**: Check your Scopus API key
- **429 Rate Limited**: Script automatically waits and retries
- **Connection errors**: Logged and counted (see summary)
- **Ctrl+C interrupt**: Results saved automatically
- **Missing files**: Clear error message with file path

---

## Rate Limits

- **Scopus API**: 5,000 requests/week (free tier)
- **OpenAlex API**: No rate limit (polite requests recommended)
- **Script delay**: 1 second between requests (configurable via `DELAY_BETWEEN_REQUESTS`)

---

## Security Notes

- API key stored in `.scopus_api_key` with restricted permissions (chmod 600)
- File automatically added to `.gitignore`
- Never commit `.scopus_api_key` to version control
- Use `--reset-key` to remove stored key

---

## Best Practices

### Before Running

1. **Test your API key first**: `python scopus_id_extractor.py --test-key`
2. **Start with a small batch**: Use `--limit 10` to verify everything works
3. **Check validation**: Run with `--dry-run` to see validation results
4. **Review validation report**: Check `validation_report.txt` for issues

### During Processing

1. **Use resume for large batches**: If interrupted, restart with `--resume`
2. **Monitor cache hits**: Higher cache hits = faster processing
3. **Adjust workers if needed**: Increase `--workers` for faster processing (watch for rate limits)
4. **Keep checkpoint files**: Don't delete `checkpoint.json` until job completes

### After Completion

1. **Check success rate**: Low rates may indicate input data issues
2. **Review validation report**: Understand why items failed
3. **Clean up**: Delete `checkpoint.json` and optionally `validation_report.txt`
4. **Keep cache**: `.scopus_cache.json` speeds up future runs

### Optimizing Performance

- **Small datasets (<100)**: Use default settings
- **Medium datasets (100-1000)**: Use `--workers 5` and cache
- **Large datasets (>1000)**: 
  - Process in batches with `--limit 500`
  - Use `--resume` between batches
  - Monitor API quota (5000/week)
  - Keep cache enabled

---

## Troubleshooting

### "Scopus API key is required"
Run the script and enter your API key when prompted, or use `--reset-key` to re-enter.

### "Unauthorized - check Scopus API key"
Your API key may be invalid or expired. Use `--reset-key` and enter a new key, or test it with `--test-key`.

### "Invalid DOI format" errors
Check `validation_report.txt` for problematic DOIs. Valid format: `10.XXXX/...`

### Low success rates
- Verify DOIs/titles are correctly formatted in input files
- Check if items exist in Scopus database (try searching manually)
- OpenAlex fallback provides titles/DOIs but not Scopus IDs
- Some papers may not be indexed in Scopus

### High error count
- Check internet connection
- Verify Scopus API service status
- Consider increasing `DELAY_BETWEEN_REQUESTS` in script
- Check if you've hit API quota (5000/week)

### Cache not working
- Check `.scopus_cache.json` exists and is readable
- Try `--cache-stats` to verify cache status
- Use `--clear-cache` and retry if cache is corrupted

### Resume not working
- Ensure `checkpoint.json` exists in script directory
- Check checkpoint file is valid JSON
- If corrupted, delete and restart without `--resume`

### Duplicate detection issues
- Use `--skip-duplicates` to automatically remove duplicates
- Check `validation_report.txt` for duplicate details
- Duplicates are detected case-insensitively

---

## Files Generated

- `scopus_results.csv` - Final results with Scopus IDs (and titles/DOIs when available)
- `checkpoint.json` - Enhanced checkpoint with metadata (JSON format)
- `validation_report.txt` - Validation issues report (created only if issues found)
- `.scopus_cache.json` - Response cache (speeds up repeated queries)
- `.scopus_api_key` - Stored API key (git-ignored)
- `.gitignore` - Auto-created/updated with sensitive file entries

### Cache Management

The cache persists between runs to speed up processing:
- **View stats**: `python scopus_id_extractor.py --cache-stats`
- **Clear cache**: `python scopus_id_extractor.py --clear-cache`
- **Bypass cache**: Use `--no-cache` flag

Cache is stored in `.scopus_cache.json` and automatically managed.