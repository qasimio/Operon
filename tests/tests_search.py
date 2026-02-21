import os
from tools.repo_search import search_repo 

def test_search_repo_finds_files(tmp_path):
    # Setup a dummy directory with a file
    test_dir = tmp_path / "test_repo"
    test_dir.mkdir()
    
    test_file = test_dir / "config.py"
    test_file.write_text("PORT = 8080\nURL = 'localhost'", encoding="utf-8")
    
    # Run the search tool with the CORRECT argument order: (repo_root, query)
    results = search_repo(str(test_dir), "8080")
    
    # Verify it found our config.py
    assert "config.py" in results, f"Search tool failed. Results were: {results}"