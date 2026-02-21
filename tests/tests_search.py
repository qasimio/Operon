import os
import json
from tools.repo_search import search_repo # Adjust import based on your structure

def test_search_repo_finds_files(tmp_path):
    # Setup a dummy directory with a file
    test_dir = tmp_path / "test_repo"
    test_dir.mkdir()
    
    test_file = test_dir / "config.py"
    test_file.write_text("PORT = 8080\nURL = 'localhost'")
    
    # Run the search tool
    # Assuming search_repo takes (query, repo_path) or similar. Adjust to your signature!
    results = search_repo("8080", str(test_dir))
    
    # Verify it found our config.py
    assert "config.py" in results, "Search tool failed to find the target file."