"""SQLite-backed storage for application data.

Provides a generic DataStore base class for database operations and schema management,
with TemplateStore handling template-specific logic. The architecture supports adding
new tables and data handlers without modifying the core storage layer.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from config import BASE_DIR, DATABASE_PATH, TEMPLATE_DIR


@dataclass(frozen=True)
class TemplateRecord:
    """Template metadata and loaded body content."""

    id: int
    name: str
    subject: str
    text_file: str
    html_file: str
    text_body: str
    html_body: str


class DataStore:
    """Generic SQLite data store for the application.
    
    Handles database connection management and schema initialization.
    Subclasses and handlers can register table schemas for automatic setup.
    This design enables easy addition of new tables without modifying the core layer.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the data store.
        
        Args:
            db_path: Optional path to the SQLite database file.
                     If None, uses DATABASE_PATH from config.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH
        self._schema_handlers: dict[str, Callable[[sqlite3.Connection], None]] = {}
        self._ensure_db_initialized()

    def register_schema(self, table_name: str, init_handler: Callable[[sqlite3.Connection], None]):
        """Register a schema initialization handler for a table.
        
        Args:
            table_name: Name of the table
            init_handler: Callable that takes a connection and executes CREATE TABLE IF NOT EXISTS
        """
        self._schema_handlers[table_name] = init_handler

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection."""
        return sqlite3.connect(self.db_path)

    def _ensure_db_initialized(self):
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _initialize_schema(self):
        """Execute all registered schema handlers. Call from subclass __init__ after registering."""
        with self._connect() as connection:
            for handler in self._schema_handlers.values():
                handler(connection)
            connection.commit()


class TemplateStore(DataStore):
    """Handles email template storage and validation."""

    _TEMPLATE_PREFIX = Path("templates")

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the template store.
        
        Args:
            db_path: Optional path to the SQLite database file.
        """
        super().__init__(db_path)
        self._register_template_schema()
        self._initialize_schema()

    def _register_template_schema(self):
        """Register the templates table schema."""

        def init_templates_table(connection: sqlite3.Connection):
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL,
                    text_file TEXT NOT NULL,
                    html_file TEXT NOT NULL
                )
                """
            )

        self.register_schema("templates", init_templates_table)


    def _normalize_db_template_path(self, path_value: str, field_name: str) -> str:
        """Normalize a database path to be relative to the templates directory."""
        path = Path(path_value)

        if path.is_absolute():
            try:
                path = path.resolve().relative_to(TEMPLATE_DIR.resolve())
            except ValueError as error:
                raise ValueError(
                    f"Template {field_name} must point inside {TEMPLATE_DIR}: {path_value}"
                ) from error
        elif path.parts and path.parts[0] == self._TEMPLATE_PREFIX.name:
            path = Path(*path.parts[1:])

        normalized_path = path.as_posix()
        if not normalized_path or normalized_path == ".":
            raise ValueError(f"Template {field_name} cannot be empty: {path_value}")
        if normalized_path.startswith("../") or normalized_path == "..":
            raise ValueError(
                f"Template {field_name} must stay inside {TEMPLATE_DIR}: {path_value}"
            )

        return normalized_path

    def _template_db_value_to_path(self, path_value: str, field_name: str) -> Path:
        """Convert a stored database value into a templates/ relative path."""
        normalized_path = self._normalize_db_template_path(path_value, field_name)
        return self._TEMPLATE_PREFIX / normalized_path

    def _resolve_template_path(self, path_value: str, field_name: str) -> Path:
        """Resolve and validate a template file path.
        
        Args:
            path_value: The path value from the database (absolute or relative)
            field_name: Name of the field (for error messages)
            
        Returns:
            Resolved absolute path to the file
            
        Raises:
            ValueError: If the path is invalid or doesn't exist
        """
        path = BASE_DIR / self._template_db_value_to_path(path_value, field_name)

        resolved_path = path.resolve()
        template_root = TEMPLATE_DIR.resolve()

        try:
            resolved_path.relative_to(template_root)
        except ValueError as error:
            raise ValueError(
                f"Template {field_name} must point inside {TEMPLATE_DIR}: {path_value}"
            ) from error

        if not resolved_path.exists() or not resolved_path.is_file():
            raise ValueError(
                f"Template {field_name} does not exist: {path_value}"
            )

        return resolved_path

    def _row_to_template_record(
        self,
        template_id: int,
        name: str,
        subject: str,
        text_file: str,
        html_file: str,
    ) -> TemplateRecord:
        """Build a template record from one database row and loaded files."""
        resolved_text_path = self._resolve_template_path(text_file, "text_file")
        resolved_html_path = self._resolve_template_path(html_file, "html_file")
        rendered_text_file = self._template_db_value_to_path(text_file, "text_file").as_posix()
        rendered_html_file = self._template_db_value_to_path(html_file, "html_file").as_posix()

        return TemplateRecord(
            id=template_id,
            name=name,
            subject=subject,
            text_file=rendered_text_file,
            html_file=rendered_html_file,
            text_body=resolved_text_path.read_text(encoding="utf-8").strip(),
            html_body=resolved_html_path.read_text(encoding="utf-8").strip(),
        )

    def get_templates(self) -> list[TemplateRecord]:
        """Return all templates from the database with validated linked files.

        Returns:
            List of TemplateRecord objects with content loaded from disk

        Raises:
            ValueError: If no templates exist or any template files are invalid
        """
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, subject, text_file, html_file
                FROM templates
                ORDER BY id
                """
            ).fetchall()

        if not rows:
            raise ValueError(
                f"No templates found in database: {self.db_path}. Add at least one row to the templates table."
            )

        return [
            self._row_to_template_record(
                template_id,
                name,
                subject,
                text_file,
                html_file,
            )
            for template_id, name, subject, text_file, html_file in rows
        ]

    def get_template(self, template_id: int) -> TemplateRecord:
        """Return one template by ID with validated linked files.

        Args:
            template_id: Template ID from the templates table.

        Returns:
            TemplateRecord loaded from the database and disk.

        Raises:
            ValueError: If the template does not exist or files are invalid.
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, subject, text_file, html_file
                FROM templates
                WHERE id = ?
                """,
                (template_id,),
            ).fetchone()

        if row is None:
            raise ValueError(f"Template {template_id} does not exist")

        return self._row_to_template_record(*row)