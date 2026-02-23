# tools/semantic_memory.py
import os
import hashlib
from pathlib import Path
import lancedb
import pyarrow as pa
from fastembed import TextEmbedding
from tools.universal_parser import extract_symbols
from agent.logger import log

# Initialize the ONNX Embedding Model (Downloads a tiny ~100MB model on first run)
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

def get_db_path(repo_root: str) -> str:
    db_path = Path(repo_root) / ".operon" / "lancedb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)

def _hash_file(file_path: Path) -> str:
    """Returns MD5 hash of a file to detect changes."""
    hasher = hashlib.md5()
    hasher.update(file_path.read_bytes())
    return hasher.hexdigest()

def index_repo(repo_root: str):
    """Scans the repo, hashes files, and updates the vector database."""
    log.info("[bold cyan]🧠 Booting Semantic Memory... Scanning repo.[/bold cyan]")
    db = lancedb.connect(get_db_path(repo_root))
    
    # Define the schema
    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("file_path", pa.string()),
        pa.field("content", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 384)), # BGE-Small dimension size
    ])

    if "code_index" not in db.table_names():
        table = db.create_table("code_index", schema=schema)
        indexed_hashes = {}
    else:
        table = db.open_table("code_index")
        # In a full prod version, we'd load hashes from a local sqlite or json cache.
        # For Phase 2, we will just wipe and re-index for perfect sync.
        db.drop_table("code_index")
        table = db.create_table("code_index", schema=schema)

    repo = Path(repo_root)
    ignore_dirs = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}
    valid_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".txt"}

    documents = []
    metadata = []

    for p in repo.rglob("*"):
        if any(i in p.parts for i in ignore_dirs) or not p.is_file() or p.suffix not in valid_exts:
            continue
            
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            if not content.strip(): continue
            
            # Use our Universal Parser to extract function context
            symbols = extract_symbols(content, str(p))
            funcs = [f["name"] for f in symbols.get("functions", [])]
            func_meta = f"Functions inside: {', '.join(funcs)}" if funcs else ""

            # Chunking: Store the file path and a snippet + function names
            doc_text = f"File: {p.name}\n{func_meta}\nCode Snippet:\n{content[:1500]}"
            
            documents.append(doc_text)
            metadata.append({
                "id": str(p.relative_to(repo)),
                "file_path": str(p.relative_to(repo)),
                "content": doc_text
            })
        except Exception:
            pass

    if documents:
        log.info(f"Generating vectors for {len(documents)} files (Zero-PyTorch ONNX)...")
        embeddings = list(embedding_model.embed(documents))
        
        # Prepare data for LanceDB
        data = []
        for meta, vec in zip(metadata, embeddings):
            meta["vector"] = vec.tolist()
            data.append(meta)
            
        table.add(data)
        log.info("[bold green]✅ Semantic Indexing Complete![/bold green]")

def search_memory(repo_root: str, query: str, top_k: int = 5) -> list:
    """Performs a semantic vector search across the codebase."""
    db_path = get_db_path(repo_root)
    if not Path(db_path).exists():
        return []

    try:
        db = lancedb.connect(db_path)
        table = db.open_table("code_index")
        
        # Embed the search query
        query_vector = next(iter(embedding_model.embed([query]))).tolist()
        
        # LanceDB ANN Search!
        results = table.search(query_vector).limit(top_k).to_list()
        
        # Return just the file paths of the best matches
        return list(dict.fromkeys([res["file_path"] for res in results]))
    except Exception as e:
        log.error(f"Memory Search Error: {e}")
        return []