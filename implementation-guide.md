# Sci-Hub CLI Implementation Guide

## Working Download Approach

The most reliable method for downloading papers from Sci-Hub uses direct URL access with curl:

```bash
curl -L -o [output_filename].pdf "https://sci-hub.se/downloads/[date]/[hash]/[doi].pdf?download=true"
```

### Example:
```bash
curl -L -o test_download.pdf "https://sci-hub.se/downloads/2020-09-16/b9/10.1038@s41586-020-2649-2.pdf?download=true"
```

### URL Pattern:
- Base domain: `sci-hub.se` (may need to use different mirrors depending on availability)
- Path format: `/downloads/[DATE]/[HASH]/[DOI].pdf`
- Parameter: `?download=true`
- Note: DOI format uses `@` instead of `/` (e.g., `10.1038@s41586-020-2649-2`)

## Implementation Steps

1. **Parse input file** to extract DOIs or full paper URLs
2. **For each DOI/URL**:
   - First visit the Sci-Hub website with the DOI to get the download link
   - Extract the direct download URL from the page
   - Use curl to download the PDF with the extracted URL
   - Save with appropriate filename

## Extraction Process

To get the download URL:
1. Visit `https://sci-hub.se/[DOI]` or `https://sci-hub.se/[full-paper-url]`
2. Parse the HTML response to find the download link
3. The download link is typically in an iframe or button element
4. Extract the complete URL and use it with curl for downloading

## Technical Considerations

- Need to handle HTTP redirects (use `-L` with curl)
- May need to implement user agent rotation or delays between requests
- Consider implementing mirror selection/rotation if one mirror becomes unavailable
- Error handling for papers not found in Sci-Hub
- Filename generation based on metadata or DOI as fallback

This approach should be more reliable than attempting to use libraries that might be detected and blocked by Sci-Hub. 