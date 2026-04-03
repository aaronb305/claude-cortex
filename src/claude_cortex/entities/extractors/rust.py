"""Rust entity extractor using tree-sitter."""

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

# Lazy import tree-sitter to avoid loading it unless needed
_parser = None
_language = None
_parser_lock = threading.Lock()


def _get_parser():
    """Lazily initialize the Rust tree-sitter parser (thread-safe)."""
    global _parser, _language
    if _parser is None:
        with _parser_lock:
            # Double-check after acquiring lock
            if _parser is None:
                try:
                    from tree_sitter_language_pack import get_parser, get_language
                    _parser = get_parser("rust")
                    _language = get_language("rust")
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


class RustExtractor(BaseExtractor):
    """Extracts entities and relationships from Rust files using tree-sitter."""

    LANGUAGE = "rust"
    EXTENSIONS = {".rs"}

    def __init__(self):
        self._function_query = None
        self._struct_query = None
        self._enum_query = None
        self._trait_query = None
        self._impl_query = None
        self._use_query = None
        self._const_query = None

    def _compile_queries(self):
        """Lazily compile tree-sitter queries."""
        if self._function_query is not None:
            return

        from tree_sitter import Query
        _, language = _get_parser()

        # Free function definitions (top-level only, not inside impl blocks)
        self._function_query = Query(language, """
            (function_item
                name: (identifier) @function.name) @function.def
        """)

        # Struct definitions
        self._struct_query = Query(language, """
            (struct_item
                name: (type_identifier) @struct.name) @struct.def
        """)

        # Enum definitions
        self._enum_query = Query(language, """
            (enum_item
                name: (type_identifier) @enum.name) @enum.def
        """)

        # Trait definitions
        self._trait_query = Query(language, """
            (trait_item
                name: (type_identifier) @trait.name) @trait.def
        """)

        # Impl blocks (both inherent and trait implementations)
        self._impl_query = Query(language, """
            (impl_item
                trait: (type_identifier)? @impl.trait
                type: (type_identifier) @impl.type
                body: (declaration_list) @impl.body) @impl.def
        """)

        # Use declarations
        self._use_query = Query(language, """
            (use_declaration
                argument: (_) @use.path) @use.def
        """)

        # Constants and statics
        self._const_query = Query(language, """
            (const_item
                name: (identifier) @const.name) @const.def

            (static_item
                name: (identifier) @static.name) @static.def
        """)

    def extract_file(self, file_path: Path) -> ExtractionResult:
        """Extract entities and relationships from a Rust file."""
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

        # Track impl block ranges for associating methods with their type
        # Each entry: (start_line, end_line, type_name, trait_name_or_None)
        impl_ranges: list[tuple[int, int, str, str | None]] = []

        # Extract structs
        for pattern_idx, captures in _run_query(self._struct_query, tree.root_node):
            struct_node = None
            struct_name = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "struct.def":
                        struct_node = n
                    elif capture_name == "struct.name":
                        struct_name = n.text.decode("utf-8")

            if struct_node and struct_name:
                start_line = struct_node.start_point[0] + 1
                end_line = struct_node.end_point[0] + 1
                qualified = f"{file_str}:{struct_name}"

                entity = Entity(
                    entity_type=EntityType.CLASS,
                    name=struct_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                    metadata={"kind": "struct"},
                )
                entities.append(entity)

                relationships.append((
                    file_str,
                    qualified,
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

        # Extract enums
        for pattern_idx, captures in _run_query(self._enum_query, tree.root_node):
            enum_node = None
            enum_name = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "enum.def":
                        enum_node = n
                    elif capture_name == "enum.name":
                        enum_name = n.text.decode("utf-8")

            if enum_node and enum_name:
                start_line = enum_node.start_point[0] + 1
                end_line = enum_node.end_point[0] + 1
                qualified = f"{file_str}:{enum_name}"

                entity = Entity(
                    entity_type=EntityType.CLASS,
                    name=enum_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                    metadata={"kind": "enum"},
                )
                entities.append(entity)

                relationships.append((
                    file_str,
                    qualified,
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

        # Extract traits
        for pattern_idx, captures in _run_query(self._trait_query, tree.root_node):
            trait_node = None
            trait_name = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "trait.def":
                        trait_node = n
                    elif capture_name == "trait.name":
                        trait_name = n.text.decode("utf-8")

            if trait_node and trait_name:
                start_line = trait_node.start_point[0] + 1
                end_line = trait_node.end_point[0] + 1
                qualified = f"{file_str}:{trait_name}"

                entity = Entity(
                    entity_type=EntityType.CLASS,
                    name=trait_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                    metadata={"kind": "trait"},
                )
                entities.append(entity)

                relationships.append((
                    file_str,
                    qualified,
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

        # Extract impl blocks and their methods
        for pattern_idx, captures in _run_query(self._impl_query, tree.root_node):
            impl_node = None
            impl_type = None
            impl_trait = None
            impl_body = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "impl.def":
                        impl_node = n
                    elif capture_name == "impl.type":
                        impl_type = n.text.decode("utf-8")
                    elif capture_name == "impl.trait":
                        impl_trait = n.text.decode("utf-8")
                    elif capture_name == "impl.body":
                        impl_body = n

            if impl_node and impl_type:
                impl_start = impl_node.start_point[0] + 1
                impl_end = impl_node.end_point[0] + 1
                impl_ranges.append((impl_start, impl_end, impl_type, impl_trait))

                # If this is a trait implementation, add INHERITS relationship
                if impl_trait:
                    type_qualified = f"{file_str}:{impl_type}"
                    relationships.append((
                        type_qualified,
                        impl_trait,
                        RelationshipType.INHERITS,
                        {"line": impl_start},
                    ))

                # Extract methods from the impl body
                if impl_body:
                    for child in impl_body.children:
                        if child.type == "function_item":
                            method_name = None
                            for sub in child.children:
                                if sub.type == "identifier":
                                    method_name = sub.text.decode("utf-8")
                                    break

                            if method_name:
                                method_start = child.start_point[0] + 1
                                method_end = child.end_point[0] + 1
                                method_qualified = f"{file_str}:{impl_type}.{method_name}"
                                container_qualified = f"{file_str}:{impl_type}"

                                entity = Entity(
                                    entity_type=EntityType.METHOD,
                                    name=method_name,
                                    qualified_name=method_qualified,
                                    file_path=file_str,
                                    start_line=method_start,
                                    end_line=method_end,
                                    content_hash=content_hash,
                                    metadata={
                                        "parent_class": impl_type,
                                        "trait_impl": impl_trait,
                                    } if impl_trait else {
                                        "parent_class": impl_type,
                                    },
                                )
                                entities.append(entity)

                                relationships.append((
                                    container_qualified,
                                    method_qualified,
                                    RelationshipType.CONTAINS,
                                    {"line": method_start},
                                ))

        # Extract free functions (top-level only, not inside impl blocks)
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

                # Skip functions inside impl blocks (they are extracted as methods above)
                in_impl = False
                for impl_start, impl_end, impl_type, _ in impl_ranges:
                    if impl_start <= start_line <= impl_end:
                        in_impl = True
                        break

                if in_impl:
                    continue

                qualified = f"{file_str}:{func_name}"

                entity = Entity(
                    entity_type=EntityType.FUNCTION,
                    name=func_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                )
                entities.append(entity)

                relationships.append((
                    file_str,
                    qualified,
                    RelationshipType.DEFINES,
                    {"line": start_line},
                ))

        # Extract use declarations (imports)
        for pattern_idx, captures in _run_query(self._use_query, tree.root_node):
            use_node = None
            use_path = None

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "use.def":
                        use_node = n
                    elif capture_name == "use.path":
                        use_path = n.text.decode("utf-8")

            if use_node and use_path:
                start_line = use_node.start_point[0] + 1

                relationships.append((
                    file_str,
                    use_path,
                    RelationshipType.IMPORTS,
                    {"line": start_line, "import_type": "use"},
                ))

        # Extract constants and statics
        for pattern_idx, captures in _run_query(self._const_query, tree.root_node):
            const_node = None
            const_name = None
            is_static = False

            for capture_name, node in captures.items():
                nodes = node if isinstance(node, list) else [node]
                for n in nodes:
                    if capture_name == "const.def":
                        const_node = n
                    elif capture_name == "const.name":
                        const_name = n.text.decode("utf-8")
                    elif capture_name == "static.def":
                        const_node = n
                        is_static = True
                    elif capture_name == "static.name":
                        const_name = n.text.decode("utf-8")

            if const_node and const_name:
                start_line = const_node.start_point[0] + 1
                end_line = const_node.end_point[0] + 1

                # Only extract top-level constants (not inside impl blocks)
                in_impl = False
                for impl_start, impl_end, _, _ in impl_ranges:
                    if impl_start <= start_line <= impl_end:
                        in_impl = True
                        break

                if in_impl:
                    continue

                qualified = f"{file_str}:{const_name}"

                entity = Entity(
                    entity_type=EntityType.CONSTANT,
                    name=const_name,
                    qualified_name=qualified,
                    file_path=file_str,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=content_hash,
                    metadata={"kind": "static"} if is_static else {},
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
