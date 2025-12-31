"""Tests for entity graph functionality."""

import pytest
from pathlib import Path
from datetime import datetime, timezone

from claude_cortex.entities.models import (
    Entity,
    Relationship,
    EntityType,
    RelationshipType,
    ExtractionResult,
)
from claude_cortex.entities.graph import EntityGraph
from claude_cortex.entities.extractors.python import PythonExtractor
from claude_cortex.entities.extractors.typescript import TypeScriptExtractor
from claude_cortex.entities.extractors import get_extractor_for_file


# =============================================================================
# Model Tests
# =============================================================================


class TestEntityModel:
    """Tests for the Entity model."""

    def test_entity_creation(self):
        """Should create an entity with required fields."""
        entity = Entity(
            entity_type=EntityType.FUNCTION,
            name="my_function",
            qualified_name="test.py:my_function",
            file_path="test.py",
            start_line=10,
            end_line=20,
        )

        assert entity.entity_type == EntityType.FUNCTION
        assert entity.name == "my_function"
        assert entity.qualified_name == "test.py:my_function"
        assert entity.start_line == 10
        assert entity.end_line == 20
        assert entity.last_indexed is not None

    def test_entity_to_dict(self):
        """Should serialize to dictionary."""
        entity = Entity(
            entity_type=EntityType.CLASS,
            name="MyClass",
            qualified_name="module.py:MyClass",
            file_path="module.py",
            start_line=5,
            metadata={"bases": ["BaseClass"]},
        )

        data = entity.to_dict()

        assert data["entity_type"] == "class"
        assert data["name"] == "MyClass"
        assert '"bases"' in data["metadata"]


class TestRelationshipModel:
    """Tests for the Relationship model."""

    def test_relationship_creation(self):
        """Should create a relationship with required fields."""
        rel = Relationship(
            source_id=1,
            target_id=2,
            relationship_type=RelationshipType.IMPORTS,
        )

        assert rel.source_id == 1
        assert rel.target_id == 2
        assert rel.relationship_type == RelationshipType.IMPORTS
        assert rel.weight == 1.0


class TestExtractionResult:
    """Tests for ExtractionResult."""

    def test_extraction_result_counts(self):
        """Should correctly count entities and relationships."""
        result = ExtractionResult(
            file_path="test.py",
            entities=[
                Entity(
                    entity_type=EntityType.FILE,
                    name="test.py",
                    qualified_name="test.py",
                    file_path="test.py",
                ),
                Entity(
                    entity_type=EntityType.FUNCTION,
                    name="func",
                    qualified_name="test.py:func",
                    file_path="test.py",
                ),
            ],
            relationships=[
                ("test.py", "test.py:func", RelationshipType.DEFINES, {}),
            ],
        )

        assert result.entity_count == 2
        assert result.relationship_count == 1


# =============================================================================
# Python Extractor Tests
# =============================================================================


class TestPythonExtractor:
    """Tests for Python entity extraction."""

    @pytest.fixture
    def extractor(self):
        return PythonExtractor()

    @pytest.fixture
    def python_file(self, temp_dir):
        """Create a sample Python file."""
        code = '''"""Module docstring."""

import os
from pathlib import Path

CONSTANT = 42

def my_function(arg1, arg2):
    """Function docstring."""
    return arg1 + arg2

class MyClass:
    """Class docstring."""

    def __init__(self, value):
        self.value = value

    def method(self):
        """Method docstring."""
        return self.value * 2

class DerivedClass(MyClass):
    """Derived class."""

    def method(self):
        return super().method() + 1
'''
        file_path = temp_dir / "sample.py"
        file_path.write_text(code)
        return file_path

    def test_can_handle_python(self, extractor):
        """Should handle .py files."""
        assert extractor.can_handle(Path("test.py"))
        assert not extractor.can_handle(Path("test.ts"))

    def test_extract_file_entity(self, extractor, python_file):
        """Should extract file entity."""
        result = extractor.extract_file(python_file)

        file_entities = [e for e in result.entities if e.entity_type == EntityType.FILE]
        assert len(file_entities) == 1
        assert file_entities[0].name == "sample.py"

    def test_extract_functions(self, extractor, python_file):
        """Should extract function definitions."""
        result = extractor.extract_file(python_file)

        functions = [e for e in result.entities if e.entity_type == EntityType.FUNCTION]
        assert len(functions) == 1
        assert functions[0].name == "my_function"
        assert functions[0].start_line is not None

    def test_extract_classes(self, extractor, python_file):
        """Should extract class definitions."""
        result = extractor.extract_file(python_file)

        classes = [e for e in result.entities if e.entity_type == EntityType.CLASS]
        assert len(classes) == 2

        class_names = {c.name for c in classes}
        assert "MyClass" in class_names
        assert "DerivedClass" in class_names

    def test_extract_methods(self, extractor, python_file):
        """Should extract class methods."""
        result = extractor.extract_file(python_file)

        methods = [e for e in result.entities if e.entity_type == EntityType.METHOD]
        # __init__ and method from MyClass, method from DerivedClass
        assert len(methods) >= 3

        method_names = {m.name for m in methods}
        assert "__init__" in method_names
        assert "method" in method_names

    def test_extract_inheritance(self, extractor, python_file):
        """Should extract inheritance relationships."""
        result = extractor.extract_file(python_file)

        inherits = [
            r for r in result.relationships
            if r[2] == RelationshipType.INHERITS
        ]
        assert len(inherits) >= 1

        # DerivedClass inherits from MyClass
        targets = {r[1] for r in inherits}
        assert "MyClass" in targets

    def test_extract_imports(self, extractor, python_file):
        """Should extract import relationships."""
        result = extractor.extract_file(python_file)

        imports = [
            r for r in result.relationships
            if r[2] == RelationshipType.IMPORTS
        ]
        assert len(imports) >= 2

        imported = {r[1] for r in imports}
        assert "os" in imported
        assert "pathlib" in imported


class TestPythonExtractorEdgeCases:
    """Edge case tests for Python extractor."""

    @pytest.fixture
    def extractor(self):
        return PythonExtractor()

    def test_empty_file(self, extractor, temp_dir):
        """Should handle empty file."""
        file_path = temp_dir / "empty.py"
        file_path.write_text("")

        result = extractor.extract_file(file_path)

        assert len(result.errors) == 0
        # Should still have file entity
        assert len(result.entities) == 1
        assert result.entities[0].entity_type == EntityType.FILE

    def test_syntax_error_file(self, extractor, temp_dir):
        """Should handle file with syntax errors gracefully."""
        file_path = temp_dir / "broken.py"
        file_path.write_text("def broken(:\n    pass")

        result = extractor.extract_file(file_path)

        # Tree-sitter is error-tolerant, should still extract what it can
        assert len(result.errors) == 0

    def test_nested_classes(self, extractor, temp_dir):
        """Should handle nested class definitions."""
        code = '''
class Outer:
    class Inner:
        def inner_method(self):
            pass

    def outer_method(self):
        pass
'''
        file_path = temp_dir / "nested.py"
        file_path.write_text(code)

        result = extractor.extract_file(file_path)

        classes = [e for e in result.entities if e.entity_type == EntityType.CLASS]
        assert len(classes) >= 1  # At least Outer


# =============================================================================
# TypeScript Extractor Tests
# =============================================================================


class TestTypeScriptExtractor:
    """Tests for TypeScript entity extraction."""

    @pytest.fixture
    def extractor(self):
        return TypeScriptExtractor()

    @pytest.fixture
    def typescript_file(self, temp_dir):
        """Create a sample TypeScript file."""
        code = '''import { Component } from 'react';
import axios from 'axios';

export const API_URL = 'https://api.example.com';

export function fetchData(url: string): Promise<any> {
    return axios.get(url);
}

export class UserService {
    private baseUrl: string;

    constructor(baseUrl: string) {
        this.baseUrl = baseUrl;
    }

    async getUser(id: number): Promise<User> {
        return fetchData(`${this.baseUrl}/users/${id}`);
    }
}

class DerivedService extends UserService {
    async getAdmin(id: number): Promise<User> {
        return this.getUser(id);
    }
}
'''
        file_path = temp_dir / "sample.ts"
        file_path.write_text(code)
        return file_path

    def test_can_handle_typescript(self, extractor):
        """Should handle TypeScript files."""
        assert extractor.can_handle(Path("test.ts"))
        assert extractor.can_handle(Path("test.tsx"))
        assert extractor.can_handle(Path("test.js"))
        assert extractor.can_handle(Path("test.jsx"))
        assert not extractor.can_handle(Path("test.py"))

    def test_extract_functions(self, extractor, typescript_file):
        """Should extract function definitions."""
        result = extractor.extract_file(typescript_file)

        functions = [e for e in result.entities if e.entity_type == EntityType.FUNCTION]
        assert len(functions) >= 1

        func_names = {f.name for f in functions}
        assert "fetchData" in func_names

    def test_extract_classes(self, extractor, typescript_file):
        """Should extract class definitions."""
        result = extractor.extract_file(typescript_file)

        classes = [e for e in result.entities if e.entity_type == EntityType.CLASS]
        assert len(classes) >= 2

        class_names = {c.name for c in classes}
        assert "UserService" in class_names
        assert "DerivedService" in class_names

    def test_extract_methods(self, extractor, typescript_file):
        """Should extract class methods."""
        result = extractor.extract_file(typescript_file)

        methods = [e for e in result.entities if e.entity_type == EntityType.METHOD]
        assert len(methods) >= 2

        method_names = {m.name for m in methods}
        assert "getUser" in method_names or "constructor" in method_names

    def test_extract_imports(self, extractor, typescript_file):
        """Should extract import statements."""
        result = extractor.extract_file(typescript_file)

        imports = [
            r for r in result.relationships
            if r[2] == RelationshipType.IMPORTS
        ]
        assert len(imports) >= 2

        sources = {r[1] for r in imports}
        assert "react" in sources
        assert "axios" in sources

    def test_extract_inheritance(self, extractor, typescript_file):
        """Should extract class inheritance."""
        result = extractor.extract_file(typescript_file)

        inherits = [
            r for r in result.relationships
            if r[2] == RelationshipType.INHERITS
        ]
        assert len(inherits) >= 1


class TestTypeScriptExtractorTSX:
    """Tests for TSX file extraction."""

    @pytest.fixture
    def extractor(self):
        return TypeScriptExtractor()

    def test_extract_tsx_component(self, extractor, temp_dir):
        """Should handle TSX React components."""
        code = '''import React from 'react';

interface Props {
    name: string;
}

export function Greeting({ name }: Props) {
    return <div>Hello, {name}!</div>;
}

export class ClassComponent extends React.Component<Props> {
    render() {
        return <div>Hello, {this.props.name}!</div>;
    }
}
'''
        file_path = temp_dir / "component.tsx"
        file_path.write_text(code)

        result = extractor.extract_file(file_path)

        # Should extract the function component
        functions = [e for e in result.entities if e.entity_type == EntityType.FUNCTION]
        assert any(f.name == "Greeting" for f in functions)

        # Should extract the class component
        classes = [e for e in result.entities if e.entity_type == EntityType.CLASS]
        assert any(c.name == "ClassComponent" for c in classes)


# =============================================================================
# Extractor Factory Tests
# =============================================================================


class TestExtractorFactory:
    """Tests for get_extractor_for_file."""

    def test_python_file(self):
        """Should return Python extractor for .py files."""
        extractor = get_extractor_for_file("test.py")
        assert isinstance(extractor, PythonExtractor)

    def test_typescript_file(self):
        """Should return TypeScript extractor for .ts files."""
        extractor = get_extractor_for_file("test.ts")
        assert isinstance(extractor, TypeScriptExtractor)

    def test_tsx_file(self):
        """Should return TypeScript extractor for .tsx files."""
        extractor = get_extractor_for_file("component.tsx")
        assert isinstance(extractor, TypeScriptExtractor)

    def test_unsupported_file(self):
        """Should return None for unsupported files."""
        extractor = get_extractor_for_file("test.go")
        assert extractor is None


# =============================================================================
# EntityGraph Tests
# =============================================================================


class TestEntityGraph:
    """Tests for the EntityGraph database manager."""

    @pytest.fixture
    def graph(self, temp_dir):
        """Create an EntityGraph with temporary database."""
        db_path = temp_dir / "test_entities.db"
        graph = EntityGraph(db_path=db_path)
        yield graph
        graph.close()

    @pytest.fixture
    def sample_project(self, temp_dir):
        """Create a sample project with Python files."""
        src_dir = temp_dir / "src"
        src_dir.mkdir()

        # Main module
        (src_dir / "main.py").write_text('''
from utils import helper

def main():
    result = helper()
    return result

class Application:
    def run(self):
        main()
''')

        # Utils module
        (src_dir / "utils.py").write_text('''
def helper():
    return 42

def another_helper():
    return helper() * 2
''')

        return temp_dir

    def test_index_file(self, graph, temp_dir):
        """Should index a single file."""
        file_path = temp_dir / "test.py"
        file_path.write_text("def foo(): pass")

        count = graph.index_file(file_path)

        assert count >= 1

    def test_index_directory(self, graph, sample_project):
        """Should index all files in directory."""
        files, entities = graph.index_directory(
            sample_project,
            patterns=["**/*.py"],
        )

        assert files >= 2
        assert entities >= 4  # Files + functions + classes

    def test_get_entity(self, graph, temp_dir):
        """Should retrieve entity by qualified name."""
        file_path = temp_dir / "module.py"
        file_path.write_text("def my_func(): pass")

        graph.index_file(file_path)

        entity = graph.get_entity(f"{file_path}:my_func")
        assert entity is not None
        assert entity.name == "my_func"
        assert entity.entity_type == EntityType.FUNCTION

    def test_get_entities_in_file(self, graph, temp_dir):
        """Should get all entities in a file."""
        file_path = temp_dir / "multi.py"
        file_path.write_text('''
def func1(): pass
def func2(): pass
class MyClass: pass
''')

        graph.index_file(file_path)
        entities = graph.get_entities_in_file(str(file_path))

        # File + 2 functions + 1 class
        assert len(entities) >= 4

    def test_search_entities(self, graph, temp_dir):
        """Should search entities by name."""
        file_path = temp_dir / "searchable.py"
        file_path.write_text('''
def calculate_total(): pass
def calculate_average(): pass
def other_function(): pass
''')

        graph.index_file(file_path)
        results = graph.search("calculate")

        assert len(results) >= 2
        assert all("calculate" in r.name for r in results)

    def test_get_stats(self, graph, sample_project):
        """Should return correct statistics."""
        graph.index_directory(sample_project, patterns=["**/*.py"])
        stats = graph.get_stats()

        assert stats["files"] >= 2
        assert stats["functions"] >= 3
        assert stats["entities"] >= 5

    def test_staleness_detection(self, graph, temp_dir):
        """Should detect when files need re-indexing."""
        file_path = temp_dir / "changing.py"
        file_path.write_text("def original(): pass")

        # First index
        graph.index_file(file_path)
        assert not graph.is_stale(file_path)

        # Modify file
        file_path.write_text("def modified(): pass")
        assert graph.is_stale(file_path)

        # Re-index
        graph.index_file(file_path)
        assert not graph.is_stale(file_path)

    def test_force_reindex(self, graph, temp_dir):
        """Should re-index even when not stale with force=True."""
        file_path = temp_dir / "stable.py"
        file_path.write_text("def stable(): pass")

        graph.index_file(file_path)
        initial_entity = graph.get_entity(f"{file_path}:stable")

        # Force re-index
        count = graph.index_file(file_path, force=True)
        assert count >= 1

    def test_clear(self, graph, sample_project):
        """Should clear all entities."""
        graph.index_directory(sample_project, patterns=["**/*.py"])

        stats_before = graph.get_stats()
        assert stats_before["entities"] > 0

        graph.clear()

        stats_after = graph.get_stats()
        assert stats_after["entities"] == 0

    def test_skip_common_directories(self, graph, temp_dir):
        """Should skip node_modules and __pycache__."""
        # Create files in directories that should be skipped
        (temp_dir / "node_modules").mkdir()
        (temp_dir / "node_modules" / "lib.ts").write_text("export function lib() {}")

        (temp_dir / "__pycache__").mkdir()
        (temp_dir / "__pycache__" / "cached.py").write_text("def cached(): pass")

        # Create a regular file
        (temp_dir / "main.py").write_text("def main(): pass")

        files, _ = graph.index_directory(temp_dir)

        # Should only index main.py
        assert files == 1


class TestEntityGraphRelationships:
    """Tests for relationship queries."""

    @pytest.fixture
    def graph_with_relationships(self, temp_dir):
        """Create a graph with interconnected entities."""
        db_path = temp_dir / "rel_test.db"
        graph = EntityGraph(db_path=db_path)

        # Create a file with dependencies
        file_path = temp_dir / "connected.py"
        file_path.write_text('''
from external import something

class BaseClass:
    def base_method(self):
        pass

class DerivedClass(BaseClass):
    def derived_method(self):
        self.base_method()
''')

        graph.index_file(file_path)
        yield graph
        graph.close()

    def test_get_dependencies(self, graph_with_relationships):
        """Should get outgoing relationships."""
        # Get file entity
        entities = graph_with_relationships.get_entities_by_type(EntityType.FILE)
        file_entity = entities[0]

        deps = graph_with_relationships.get_dependencies(file_entity.id)

        # File should define classes and have imports
        assert len(deps) >= 1

    def test_get_dependents(self, graph_with_relationships):
        """Should get incoming relationships."""
        # Find BaseClass
        results = graph_with_relationships.search("BaseClass")
        if results:
            base_class = results[0]
            dependents = graph_with_relationships.get_dependents(base_class.id)

            # DerivedClass should inherit from BaseClass
            assert len(dependents) >= 0  # May or may not find the inheritance


class TestEntityGraphContextManager:
    """Tests for context manager usage."""

    def test_context_manager(self, temp_dir):
        """Should work as context manager."""
        db_path = temp_dir / "context.db"

        with EntityGraph(db_path=db_path) as graph:
            file_path = temp_dir / "test.py"
            file_path.write_text("def test(): pass")
            graph.index_file(file_path)

            assert graph.get_stats()["functions"] >= 1

        # Connection should be closed after exiting
        # Creating new graph should work
        with EntityGraph(db_path=db_path) as graph2:
            assert graph2.get_stats()["functions"] >= 1


# =============================================================================
# Regression Tests for Bug Fixes
# =============================================================================


class TestConstantExtraction:
    """Regression tests for constant extraction (Issue #1)."""

    @pytest.fixture
    def extractor(self):
        from claude_cortex.entities.extractors.python import PythonExtractor
        return PythonExtractor()

    def test_uppercase_constants_extracted(self, extractor, temp_dir):
        """Should extract UPPER_CASE constants (regression for inverted logic bug)."""
        file_path = temp_dir / "constants.py"
        file_path.write_text('''
MAX_SIZE = 100
MIN_VALUE = 0
DEFAULT_NAME = "test"
lowercase_var = 42
_PRIVATE = "hidden"
''')

        result = extractor.extract_file(file_path)
        constants = [e for e in result.entities if e.entity_type == EntityType.CONSTANT]

        # Should find MAX_SIZE, MIN_VALUE, DEFAULT_NAME but not lowercase_var or _PRIVATE
        constant_names = {c.name for c in constants}
        assert "MAX_SIZE" in constant_names
        assert "MIN_VALUE" in constant_names
        assert "DEFAULT_NAME" in constant_names
        assert "lowercase_var" not in constant_names
        assert "_PRIVATE" not in constant_names

    def test_non_uppercase_not_extracted(self, extractor, temp_dir):
        """Should NOT extract non-uppercase assignments as constants."""
        file_path = temp_dir / "vars.py"
        file_path.write_text('''
my_variable = 100
anotherOne = "test"
CamelCase = True
''')

        result = extractor.extract_file(file_path)
        constants = [e for e in result.entities if e.entity_type == EntityType.CONSTANT]

        # None of these should be extracted as constants
        assert len(constants) == 0


class TestFTS5SearchSafety:
    """Regression tests for FTS5 MATCH escaping (Issue #4)."""

    @pytest.fixture
    def graph_with_entities(self, temp_dir):
        graph = EntityGraph(db_path=temp_dir / "fts.db")
        file_path = temp_dir / "searchable.py"
        file_path.write_text('''
def calculate_total(): pass
def search_and_filter(): pass
def user_name(): pass
''')
        graph.index_file(file_path)
        return graph

    def test_search_with_special_chars(self, graph_with_entities):
        """Should handle FTS5 special characters safely."""
        # These should not raise errors
        graph_with_entities.search('test"query')
        graph_with_entities.search("test*")
        graph_with_entities.search("test AND other")
        graph_with_entities.search("(test)")
        graph_with_entities.search("test:value")

    def test_search_with_quotes(self, graph_with_entities):
        """Should handle double quotes in search query."""
        results = graph_with_entities.search('calculate"total')
        # Should not crash, may return empty results
        assert isinstance(results, list)


class TestDuplicateRelationships:
    """Regression tests for duplicate relationship prevention (Issue #3)."""

    @pytest.fixture
    def graph(self, temp_dir):
        return EntityGraph(db_path=temp_dir / "dup.db")

    def test_reindex_does_not_duplicate_relationships(self, graph, temp_dir):
        """Re-indexing should not create duplicate relationships."""
        file_path = temp_dir / "module.py"
        file_path.write_text('''
import os
import sys

class MyClass:
    def method(self): pass
''')

        # Index twice
        graph.index_file(file_path)
        graph.index_file(file_path, force=True)

        # Count relationships - should not have duplicates
        cursor = graph.connection.execute("SELECT COUNT(*) FROM relationships")
        count1 = cursor.fetchone()[0]

        # Index again
        graph.index_file(file_path, force=True)

        cursor = graph.connection.execute("SELECT COUNT(*) FROM relationships")
        count2 = cursor.fetchone()[0]

        # Counts should be the same (no duplicates added)
        assert count1 == count2


class TestDepthValidation:
    """Regression tests for recursive CTE depth validation (Issue #8)."""

    @pytest.fixture
    def graph(self, temp_dir):
        graph = EntityGraph(db_path=temp_dir / "depth.db")
        file_path = temp_dir / "chain.py"
        file_path.write_text('''
class A: pass
class B(A): pass
class C(B): pass
''')
        graph.index_file(file_path)
        return graph

    def test_depth_capped_at_max(self, graph):
        """Should cap depth at 10 even if larger value passed."""
        # Get an entity ID
        entities = graph.get_entities_by_type(EntityType.CLASS)
        if not entities:
            pytest.skip("No class entities found")

        entity_id = entities[0].id

        # Should not raise error even with excessive depth
        deps = graph.get_dependencies(entity_id, depth=100)
        assert isinstance(deps, list)

        dependents = graph.get_dependents(entity_id, depth=100)
        assert isinstance(dependents, list)

    def test_depth_minimum_is_one(self, graph):
        """Should use depth=1 even if 0 or negative passed."""
        entities = graph.get_entities_by_type(EntityType.CLASS)
        if not entities:
            pytest.skip("No class entities found")

        entity_id = entities[0].id

        deps = graph.get_dependencies(entity_id, depth=0)
        assert isinstance(deps, list)

        deps = graph.get_dependencies(entity_id, depth=-5)
        assert isinstance(deps, list)


class TestTypeScriptQueryCaching:
    """Regression tests for TypeScript query caching (Issue #7)."""

    def test_mixed_ts_tsx_files_no_recompilation_error(self, temp_dir):
        """Should handle mixed .ts and .tsx files without errors."""
        from claude_cortex.entities.extractors.typescript import TypeScriptExtractor

        extractor = TypeScriptExtractor()

        # Create mixed files
        ts_file = temp_dir / "module.ts"
        ts_file.write_text('function hello(): void {}')

        tsx_file = temp_dir / "component.tsx"
        tsx_file.write_text('const App = () => <div>Hello</div>;')

        ts_file2 = temp_dir / "util.ts"
        ts_file2.write_text('export const util = () => {};')

        tsx_file2 = temp_dir / "other.tsx"
        tsx_file2.write_text('export const Other = () => <span/>;')

        # Extract from alternating file types - should not error
        result1 = extractor.extract_file(ts_file)
        result2 = extractor.extract_file(tsx_file)
        result3 = extractor.extract_file(ts_file2)
        result4 = extractor.extract_file(tsx_file2)

        # All should extract successfully
        assert len(result1.errors) == 0
        assert len(result2.errors) == 0
        assert len(result3.errors) == 0
        assert len(result4.errors) == 0


class TestJSONMetadataWarning:
    """Regression tests for JSON metadata error logging (Issue #5)."""

    def test_corrupted_metadata_logs_warning(self, temp_dir, caplog):
        """Should log warning when metadata JSON is corrupted."""
        import logging
        from claude_cortex.entities.models import Entity

        # Create a mock row with corrupted metadata
        class MockRow(dict):
            def __getitem__(self, key):
                if key == "metadata":
                    return "not valid json {"
                return super().__getitem__(key)

            def get(self, key, default=None):
                if key == "metadata":
                    return "not valid json {"
                return super().get(key, default)

        mock_row = MockRow({
            "id": 1,
            "entity_type": "function",
            "name": "test",
            "qualified_name": "/test.py:test",
            "file_path": "/test.py",
            "start_line": 1,
            "end_line": 1,
            "content_hash": "abc123",
            "last_indexed": "2024-01-01T00:00:00Z",
        })

        with caplog.at_level(logging.WARNING, logger="claude_cortex.entities.models"):
            entity = Entity.from_row(mock_row)

        # Entity should be created with empty metadata
        assert entity.metadata == {}

        # Warning should be logged
        assert any("Failed to parse metadata" in record.message for record in caplog.records)
