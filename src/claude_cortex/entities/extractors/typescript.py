"""TypeScript/JavaScript entity extractor using tree-sitter."""

import hashlib
import threading
from pathlib import Path

from claude_cortex.entities.models import (
    Entity,
    EntityType,
    RelationshipType,
    ExtractionResult,
)
from claude_cortex.entities.extractors.base import BaseExtractor

# Lazy import tree-sitter (thread-safe)
_parser = None
_tsx_parser = None
_language = None
_tsx_language = None
_parser_lock = threading.Lock()


def _get_parser(use_tsx: bool = False):
    """Lazily initialize the TypeScript tree-sitter parser (thread-safe)."""
    global _parser, _tsx_parser, _language, _tsx_language

    if use_tsx:
        if _tsx_parser is None:
            with _parser_lock:
                if _tsx_parser is None:
                    try:
                        from tree_sitter_language_pack import get_parser, get_language
                        _tsx_parser = get_parser("tsx")
                        _tsx_language = get_language("tsx")
                    except ImportError:
                        raise ImportError(
                            "tree-sitter-language-pack is required for entity extraction. "
                            "Install with: uv add tree-sitter-language-pack"
                        )
        return _tsx_parser, _tsx_language
    else:
        if _parser is None:
            with _parser_lock:
                if _parser is None:
                    try:
                        from tree_sitter_language_pack import get_parser, get_language
                        _parser = get_parser("typescript")
                        _language = get_language("typescript")
                    except ImportError:
                        raise ImportError(
                            "tree-sitter-language-pack is required for entity extraction. "
                            "Install with: uv add tree-sitter-language-pack"
                        )
        return _parser, _language


def _run_query(query, root_node):
    """Run a tree-sitter query using the 0.25.x API with QueryCursor."""
    from tree_sitter import QueryCursor
    cursor = QueryCursor(query)
    return cursor.matches(root_node)


# Query string constants (shared between TS and TSX)
_FUNCTION_QUERY = """
    (function_declaration
        name: (identifier) @function.name) @function.def

    (variable_declarator
        name: (identifier) @function.name
        value: (arrow_function)) @function.def

    (method_definition
        name: (property_identifier) @function.name) @function.def
"""

_CLASS_QUERY = """
    (class_declaration
        name: (type_identifier) @class.name
        (class_heritage
            (extends_clause
                value: (_) @class.extends))?
        body: (class_body) @class.body) @class.def
"""

_IMPORT_QUERY = """
    (import_statement
        source: (string) @import.source) @import.stmt
"""

_EXPORT_QUERY = """
    (export_statement
        declaration: (function_declaration
            name: (identifier) @export.name)?) @export.stmt

    (export_statement
        declaration: (class_declaration
            name: (type_identifier) @export.name)?) @export.stmt

    (export_statement
        declaration: (lexical_declaration
            (variable_declarator
                name: (identifier) @export.name))?) @export.stmt
"""


class TypeScriptExtractor(BaseExtractor):
    """Extracts entities and relationships from TypeScript/JavaScript files."""

    LANGUAGE = "typescript"
    EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}

    def __init__(self):
        # Cache queries separately for TS and TSX to avoid recompilation
        self._ts_queries: dict = {}
        self._tsx_queries: dict = {}

    def _compile_queries(self, use_tsx: bool = False):
        """Lazily compile tree-sitter queries (cached per language)."""
        cache = self._tsx_queries if use_tsx else self._ts_queries

        if cache:
            return cache

        from tree_sitter import Query
        _, language = _get_parser(use_tsx)

        cache["function"] = Query(language, _FUNCTION_QUERY)
        cache["class"] = Query(language, _CLASS_QUERY)
        cache["import"] = Query(language, _IMPORT_QUERY)
        cache["export"] = Query(language, _EXPORT_QUERY)

        return cache

    def extract_file(self, file_path: Path) -> ExtractionResult:
        """Extract entities and relationships from a TypeScript/JavaScript file."""
        file_path = Path(file_path)
        entities: list[Entity] = []
        relationships: list[tuple[str, str, RelationshipType, dict]] = []
        errors: list[str] = []

        try:
            content = file_path.read_bytes()
            content_hash = hashlib.md5(content).hexdigest()
        except Exception as e:
            return ExtractionResult(
                file_path=str(file_path),
                entities=[],
                relationships=[],
                errors=[f"Failed to read file: {e}"],
            )

        # Use TSX parser for .tsx and .jsx files
        use_tsx = file_path.suffix.lower() in (".tsx", ".jsx")

        try:
            parser, _ = _get_parser(use_tsx)
            queries = self._compile_queries(use_tsx)
            tree = parser.parse(content)
        except Exception as e:
            return ExtractionResult(
                file_path=str(file_path),
                entities=[],
                relationships=[],
                errors=[f"Failed to parse file: {e}"],
            )

        file_str = str(file_path)
        text = content.decode("utf-8", errors="replace")
        lines = text.split("\n")

        # Create file entity
        file_entity = Entity(
            entity_type=EntityType.FILE,
            name=file_path.name,
            qualified_name=file_str,
            file_path=file_str,
            start_line=1,
            end_line=len(lines),
            content_hash=content_hash,
        )
        entities.append(file_entity)

        # Track class ranges for methods
        class_ranges: list[tuple[int, int, str]] = []

        # Track exported names
        exported_names: set[str] = set()

        # Extract exports first to know what's exported
        for pattern_idx, captures in _run_query(queries["export"], tree.root_node):
            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "export.name":
                        exported_names.add(n.text.decode("utf-8"))

        # Extract classes
        for pattern_idx, captures in _run_query(queries["class"], tree.root_node):
            class_node = None
            class_name = None
            extends = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "class.def":
                        class_node = n
                    elif capture_name == "class.name":
                        class_name = n.text.decode("utf-8")
                    elif capture_name == "class.extends":
                        extends = n.text.decode("utf-8")

            if class_node and class_name:
                start_line = class_node.start_point[0] + 1
                end_line = class_node.end_point[0] + 1
                qualified = f"{file_str}:{class_name}"

                class_ranges.append((start_line, end_line, class_name))

                entity = Entity(
                    entity_type=EntityType.CLASS,
                    name=class_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                    metadata={
                        "extends": extends,
                        "exported": class_name in exported_names,
                    } if extends or class_name in exported_names else {},
                )
                entities.append(entity)

                # Add defines relationship
                relationships.append((
                    file_str,
                    qualified,
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

                # Add inheritance relationship
                if extends:
                    relationships.append((
                        qualified,
                        extends,
                        RelationshipType.INHERITS,
                        {"line": start_line},
                    ))

        # Extract functions
        for pattern_idx, captures in _run_query(queries["function"], tree.root_node):
            func_node = None
            func_name = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "function.def":
                        func_node = n
                    elif capture_name == "function.name":
                        func_name = n.text.decode("utf-8")

            if func_node and func_name:
                start_line = func_node.start_point[0] + 1
                end_line = func_node.end_point[0] + 1

                # Check if inside a class (method)
                parent_class = None
                for class_start, class_end, class_name in class_ranges:
                    if class_start <= start_line <= class_end:
                        parent_class = class_name
                        break

                if parent_class:
                    entity_type = EntityType.METHOD
                    qualified = f"{file_str}:{parent_class}.{func_name}"
                    container_qualified = f"{file_str}:{parent_class}"
                else:
                    entity_type = EntityType.FUNCTION
                    qualified = f"{file_str}:{func_name}"
                    container_qualified = file_str

                entity = Entity(
                    entity_type=entity_type,
                    name=func_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                    metadata={
                        "parent_class": parent_class,
                        "exported": func_name in exported_names,
                    } if parent_class or func_name in exported_names else {},
                )
                entities.append(entity)

                rel_type = RelationshipType.CONTAINS if parent_class else RelationshipType.DEFINES
                relationships.append((
                    container_qualified,
                    qualified,
                    rel_type,
                    {"line": start_line},
                ))

        # Extract imports
        for pattern_idx, captures in _run_query(queries["import"], tree.root_node):
            import_node = None
            source = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "import.stmt":
                        import_node = n
                    elif capture_name == "import.source":
                        # Remove quotes from string
                        source = n.text.decode("utf-8").strip("'\"")

            if import_node and source:
                start_line = import_node.start_point[0] + 1

                relationships.append((
                    file_str,
                    source,
                    RelationshipType.IMPORTS,
                    {"line": start_line},
                ))

        return ExtractionResult(
            file_path=file_str,
            entities=entities,
            relationships=relationships,
            errors=errors,
        )
