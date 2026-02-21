import re

def parse_search_replace(text: str):
    """
    Extracts SEARCH and REPLACE blocks from LLM output.
    Returns a list of tuples: (search_block, replace_block)
    """
    pattern = r"<<<<<<<\s*SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*REPLACE"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches

def apply_patch(original_text: str, search_block: str, replace_block: str) -> str | None:
    """
    Applies the patch exactly once. Returns None if the search block isn't found.
    """
    # Small models sometimes add an extra newline at the end of the block.
    # We strip trailing whitespace to make matching slightly more robust, 
    # but we MUST preserve leading whitespace (Python indentation).
    
    if search_block not in original_text:
        # Fallback: try stripping trailing whitespace from lines
        search_lines = [line.rstrip() for line in search_block.splitlines()]
        orig_lines = [line.rstrip() for line in original_text.splitlines()]
        
        # If strict matching fails, we return None to trigger a retry
        # (A more advanced fuzzy matcher can be added here later)
        return None

    return original_text.replace(search_block, replace_block, 1)