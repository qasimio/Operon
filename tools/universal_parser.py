# tools/universal_parser.py
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjavascript


# Map file extensions to their Tree-sitter language engine
SUPPORTED_LANGUAGES = {
    ".py": Language(tspython.language()),
    ".js": Language(tsjavascript.language()),
    ".jsx": Language(tsjavascript.language()),
    ".java": Language(tsjava.language()),
}


def get_parser(file_path: str) -> Parser | None:
    ext = Path(file_path).suffix
    if ext not in SUPPORTED_LANGUAGES:
        return None

    parser = Parser()
    parser.language = SUPPORTED_LANGUAGES[ext]
    return parser


def check_syntax(code: str, file_path: str) -> bool:
    """Returns True if the code is syntactically valid, False otherwise."""
    parser = get_parser(file_path)
    if not parser:
        return True  # fallback if language unsupported

    tree = parser.parse(code.encode("utf8"))
    return not tree.root_node.has_error


def extract_symbols(code: str, file_path: str) -> dict:
    """Universal function/class extractor for supported languages."""
    results = {"functions": [], "classes": []}
    parser = get_parser(file_path)

    if not parser:
        return results

    source_bytes = code.encode("utf8")
    tree = parser.parse(source_bytes)

    # Expanded node support (Python + JS + Java)
    func_types = {
        "function_definition",      # Python
        "function_declaration",     # JS
        "method_definition",        # JS class method
        "arrow_function",           # JS
        "method_declaration",       # Java
        "constructor_declaration",  # Java
    }

    class_types = {
        "class_definition",     # Python
        "class_declaration",    # Java / JS
        "interface_declaration" # Java
    }

    def get_node_name(node):
        """Robust cross-language name extraction."""
        identifier = node.child_by_field_name("name")
        if identifier:
            return source_bytes[identifier.start_byte:identifier.end_byte].decode("utf8")

        # fallback scan (some JS arrow cases etc.)
        for child in node.children:
            if child.type == "identifier":
                return source_bytes[child.start_byte:child.end_byte].decode("utf8")

        return "anonymous"

    def walk(node):
        if node.type in func_types:
            results["functions"].append({
                "name": get_node_name(node),
                "start": node.start_point[0] + 1,
                "end": node.end_point[0] + 1,
            })

        elif node.type in class_types:
            results["classes"].append({
                "name": get_node_name(node),
                "start": node.start_point[0] + 1,
                "end": node.end_point[0] + 1,
            })

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return results   