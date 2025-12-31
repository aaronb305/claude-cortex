"""Entity graph models for code structure tracking."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any
import json


class EntityType(str, Enum):
    """Types of code entities."""

    FILE = "file"
    FUNCTION = "function"
    CLASS = "class"
    CONSTANT = "constant"
    METHOD = "method"
    IMPORT = "import"


class RelationshipType(str, Enum):
    """Types of relationships between entities."""

    IMPORTS = "imports"      # File A imports from File/Module B
    DEFINES = "defines"      # File A defines Entity E
    CALLS = "calls"          # Entity A calls Entity B
    INHERITS = "inherits"    # Class A inherits from Class B
    CONTAINS = "contains"    # Class/Module contains Entity


@dataclass
class Entity:
    """Represents a code entity (file, function, class, etc.)."""

    entity_type: EntityType
    name: str
    qualified_name: str  # Full path: file_path:entity_name
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    content_hash: Optional[str] = None
    last_indexed: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    def __post_init__(self):
        if self.last_indexed is None:
            self.last_indexed = datetime.now(timezone.utc).isoformat()

    @classmethod
    def from_row(cls, row) -> "Entity":
        """Create Entity from SQLite row."""
        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError:
                pass

        return cls(
            id=row["id"],
            entity_type=EntityType(row["entity_type"]),
            name=row["name"],
            qualified_name=row["qualified_name"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            content_hash=row["content_hash"],
            last_indexed=row["last_indexed"],
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "entity_type": self.entity_type.value,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content_hash": self.content_hash,
            "last_indexed": self.last_indexed,
            "metadata": json.dumps(self.metadata) if self.metadata else None,
        }


@dataclass
class Relationship:
    """Represents a relationship between two entities."""

    source_id: int
    target_id: int
    relationship_type: RelationshipType
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    # Populated when fetched with joins
    source_entity: Optional[Entity] = None
    target_entity: Optional[Entity] = None

    @classmethod
    def from_row(cls, row) -> "Relationship":
        """Create Relationship from SQLite row."""
        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError:
                pass

        return cls(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relationship_type=RelationshipType(row["relationship_type"]),
            weight=row["weight"],
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship_type": self.relationship_type.value,
            "weight": self.weight,
            "metadata": json.dumps(self.metadata) if self.metadata else None,
        }


@dataclass
class ExtractionResult:
    """Result of extracting entities from a file."""

    file_path: str
    entities: list[Entity]
    relationships: list[tuple[str, str, RelationshipType, dict]]  # (source_name, target_name, type, metadata)
    errors: list[str] = field(default_factory=list)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def relationship_count(self) -> int:
        return len(self.relationships)
