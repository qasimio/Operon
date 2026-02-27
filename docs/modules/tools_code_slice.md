# `tools/code_slice.py`


## Overview

This file defines a function `load_function_slice` that takes a repository root, a function name, and an optional context size. It uses the `find_function` function from `tools.function_locator` to locate the function's position in the repository. If the function is found, it reads the file, extracts the lines surrounding the function based on the specified context, and returns a dictionary containing the file path, start and end line numbers, slice start and end line numbers, and the code snippet. If the function is not found or the file does not exist, it returns `None`.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 47 |
| Functions | 1 |
| Classes | 0 |
| Variables | 8 |
| Imports | 2 |


## Imports

- `pathlib:Path`
- `tools.function_locator:find_function`


## Dependencies (imports)

- [`tools/function_locator.py`](tools_function_locator.md)


## Functions


### `def load_function_slice(repo_root: str, func_name: str, context: int)`

- **Lines:** 5–47
- **Docstring:** Load only the lines surrounding a function/class.
    Returns:
        {
          file,
          start,
          end,
          slice_start,
          slice_end,
          code
        }
