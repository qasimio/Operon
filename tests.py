from tools.diff_engine import apply_patch

def test_diff_engine():
    original_file = """def calculate():
    x = 10
    y = 20
    return x + y
"""
    # LLM messed up the indentation in the search block (missing 4 spaces)
    search_block = """x = 10
y = 20"""
    
    # LLM's replacement
    replace_block = """x = 100
y = 200"""

    patched = apply_patch(original_file, search_block, replace_block)
    
    if patched and "x = 100" in patched and "    x = 100" in patched:
        print("✅ Diff Engine Test PASSED: Successfully handled LLM whitespace hallucination and preserved original indentation.")
    else:
        print("❌ Diff Engine Test FAILED.")
        print("Resulting code:\n", patched)

if __name__ == "__main__":
    test_diff_engine()