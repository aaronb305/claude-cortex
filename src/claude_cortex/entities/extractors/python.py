"""Python entity extractor using tree-sitter."""

import hashlib
import threading
from pathlib import Path
from typing import Optional

from claude_cortex.entities.models import (
    Entity,
    EntityType,
    RelationshipType,
    ExtractionResult,
)
from claude_cortex.entities.extractors.base import BaseExtractor

# Lazy import tree-sitter to avoid loading it unless needed
_parser = None
_language = None
_parser_lock = threading.Lock()


def _get_parser():
    """Lazily initialize the Python tree-sitter parser (thread-safe)."""
    global _parser, _language
    if _parser is None:
        with _parser_lock:
            # Double-check after acquiring lock
            if _parser is None:
                try:
                    from tree_sitter_language_pack import get_parser, get_language
                    _parser = get_parser("python")
                    _language = get_language("python")
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


class PythonExtractor(BaseExtractor):
    """Extracts entities and relationships from Python files using tree-sitter."""

    LANGUAGE = "python"
    EXTENSIONS = {".py"}

    def __init__(self):
        self._function_query = None
        self._class_query = None
        self._import_query = None
        self._assignment_query = None

    def _compile_queries(self):
        """Lazily compile tree-sitter queries."""
        if self._function_query is not None:
            return

        from tree_sitter import Query
        _, language = _get_parser()

        # Function definitions (top-level and in classes)
        self._function_query = Query(language, """
            (function_definition
                name: (identifier) @function.name) @function.def
        """)

        # Class definitions
        self._class_query = Query(language, """
            (class_definition
                name: (identifier) @class.name
                superclasses: (argument_list)? @class.bases) @class.def
        """)

        # Import statements
        self._import_query = Query(language, """
            (import_statement
                name: (dotted_name) @import.module) @import.stmt

            (import_from_statement
                module_name: (dotted_name)? @import.from
                name: (dotted_name)? @import.name) @import.stmt
        """)

        # Top-level assignments (constants) - check indentation in code to filter module-level
        self._assignment_query = Query(language, """
            (assignment
                left: (identifier) @constant.name) @constant.def
        """)

    def extract_file(self, file_path: Path) -> ExtractionResult:
        """Extract entities and relationships from a Python file."""
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

        try:
            parser, _ = _get_parser()
            self._compile_queries()
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

        # Track current class context for methods
        class_ranges: list[tuple[int, int, str]] = []  # (start, end, class_name)

        # Extract classes first to build context
        for pattern_idx, captures in _run_query(self._class_query, tree.root_node):
            class_node = None
            class_name = None
            bases = []

            for capture_name, node in captures.items():
                # captures is a dict of capture_name -> list of nodes
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "class.def":
                        class_node = n
                    elif capture_name == "class.name":
                        class_name = n.text.decode("utf-8")
                    elif capture_name == "class.bases":
                        # Extract base class names
                        for child in n.children:
                            if child.type == "identifier":
                                bases.append(child.text.decode("utf-8"))
                            elif child.type == "attribute":
                                bases.append(child.text.decode("utf-8"))

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
                    metadata={"bases": bases} if bases else {},
                )
                entities.append(entity)

                # Add defines relationship
                relationships.append((
                    file_str,  # source: file
                    qualified,  # target: class
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

                # Add inheritance relationships
                for base in bases:
                    relationships.append((
                        qualified,  # source: this class
                        base,  # target: base class (may be unresolved)
                        RelationshipType.INHERITS,
                        {"line": start_line},
                    ))

        # Extract functions
        for pattern_idx, captures in _run_query(self._function_query, tree.root_node):
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

                # Check if this function is inside a class (method)
                parent_class = None
                for class_start, class_end, cn in class_ranges:
                    if class_start <= start_line <= class_end:
                        parent_class = cn
                        break

                if parent_class:
                    # This is a method
                    entity_type = EntityType.METHOD
                    qualified = f"{file_str}:{parent_class}.{func_name}"
                    container_qualified = f"{file_str}:{parent_class}"
                else:
                    # This is a top-level function
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
                    metadata={"parent_class": parent_class} if parent_class else {},
                )
                entities.append(entity)

                # Add defines/contains relationship
                rel_type = RelationshipType.CONTAINS if parent_class else RelationshipType.DEFINES
                relationships.append((
                    container_qualified,
                    qualified,
                    rel_type,
                    {"line": start_line},
                ))

        # Extract imports
        for pattern_idx, captures in _run_query(self._import_query, tree.root_node):
            import_node = None
            module_name = None
            import_name = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "import.stmt":
                        import_node = n
                    elif capture_name == "import.module":
                        module_name = n.text.decode("utf-8")
                    elif capture_name == "import.from":
                        module_name = n.text.decode("utf-8")
                    elif capture_name == "import.name":
                        import_name = n.text.decode("utf-8")

            if import_node and (module_name or import_name):
                start_line = import_node.start_point[0] + 1
                imported = module_name or import_name

                # Create import relationship
                relationships.append((
                    file_str,  # source: this file
                    imported,  # target: imported module (may be unresolved)
                    RelationshipType.IMPORTS,
                    {"line": start_line, "import_type": "from" if import_name else "import"},
                ))

        # Extract top-level constants (UPPER_CASE assignments)
        for pattern_idx, captures in _run_query(self._assignment_query, tree.root_node):
            const_node = None
            const_name = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "constant.def":
                        const_node = n
                    elif capture_name == "constant.name":
                        const_name = n.text.decode("utf-8")

            if const_node and const_name:
                # Only capture UPPER_CASE names as constants, skip private/dunder
                if not const_name.isupper() or const_name.startswith("_"):
                    continue

                # Check if it's a class-level constant by checking indentation
                if const_node.start_point[1] > 0:
                    continue  # Not at module level

                start_line = const_node.start_point[0] + 1
                qualified = f"{file_str}:{const_name}"

                entity = Entity(
                    entity_type=EntityType.CONSTANT,
                    name=const_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=start_line,
                    content_hash=content_hash,
                )
                entities.append(entity)

                relationships.append((
                    file_str,
                    qualified,
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

        return ExtractionResult(
            file_path=file_str,
            entities=entities,
            relationships=relationships,
            errors=errors,
        )
