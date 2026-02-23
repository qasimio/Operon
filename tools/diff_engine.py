import re

def parse_search_replace(text: str):
    """
    Extracts SEARCH and REPLACE blocks from LLM output.
    Returns a list of tuples: (search_block, replace_block)
    """
    pattern = r"<<<<<<<\s*SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*REPLACE"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches

def _normalize_lines(text: str) -> list:
    """Helper to strip whitespace from ends of lines but keep internal structure."""
    return [line.strip() for line in text.strip().splitlines()]

def apply_patch(original_text: str, search_block: str, replace_block: str) -> str | None:
    """
    Applies the patch exactly once. Uses a smart line-by-line matcher 
    that ignores leading/trailing whitespace differences caused by LLMs.
    Now supports Appending and New File Creation.
    """
    # 0. The "Append / Create" Maneuver
    if not search_block.strip():
        # If the search block is empty, the LLM just wants to add new code.
        if original_text.strip():
            # Append to existing file
            return original_text.rstrip() + "\n\n" + replace_block.strip() + "\n"
        else:
            # File is completely new/empty
            return replace_block.strip() + "\n"

    # 1. Try exact match first (Fastest and safest)
    if search_block in original_text:
        return original_text.replace(search_block, replace_block, 1)

    # 2. Smart Whitespace Matcher
    orig_lines = original_text.splitlines()
    search_norm = _normalize_lines(search_block)
    search_len = len(search_norm)

    if search_len == 0:
        return None

    # Slide a window over the original file to find a matching block
    for i in range(len(orig_lines) - search_len + 1):
        window = orig_lines[i : i + search_len]
        window_norm = [line.strip() for line in window]
        
        if window_norm == search_norm:
            # We found a match! Now preserve the original indentation.
            original_indent = len(orig_lines[i]) - len(orig_lines[i].lstrip())
            
            replace_lines = replace_block.splitlines()
            if replace_lines and replace_lines[0].strip():
                replace_indent = len(replace_lines[0]) - len(replace_lines[0].lstrip())
                indent_diff = original_indent - replace_indent
                
                adjusted_replace = []
                for r_line in replace_lines:
                    if not r_line.strip():
                        adjusted_replace.append("")
                    elif indent_diff > 0:
                        adjusted_replace.append((" " * indent_diff) + r_line)
                    elif indent_diff < 0 and r_line.startswith(" " * abs(indent_diff)):
                        adjusted_replace.append(r_line[abs(indent_diff):])
                    else:
                        adjusted_replace.append(r_line)
            else:
                adjusted_replace = replace_lines

            before = orig_lines[:i]
            after = orig_lines[i + search_len:]
            final_lines = before + adjusted_replace + after
            
            return "\n".join(final_lines) + "\n"

    # 3. Fail safely if no match is found
    return None