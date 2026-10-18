"""Deterministic active-model schema inventory.

The application model package intentionally does not import every model module.  This
helper is for controlled schema verification: it first reads every active ``.py``
module under ``src.models`` using :mod:`ast`, then imports each module explicitly and
configures mappers.  It never creates an engine, opens a connection, calls an app
factory, or runs DDL.  Call it only in an already-isolated test/process.
"""
from __future__ import annotations

from dataclasses import dataclass
import ast
import importlib
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class SchemaInventoryError(RuntimeError):
    """Raised when source declarations and loaded SQLAlchemy metadata disagree."""


@dataclass(frozen=True, order=True)
class ModelDeclaration:
    """One statically declared active SQLAlchemy table."""

    table_name: str
    module: str
    class_name: str
    source_path: Path
    line: int


@dataclass(frozen=True)
class SchemaInventory:
    """Result of static discovery plus the explicit, complete import pass."""

    declarations: Mapping[str, ModelDeclaration]
    modules: tuple[str, ...]
    metadata_tables: tuple[str, ...]
    external_foreign_key_targets: Mapping[str, tuple[str, ...]]

    @property
    def declared_tables(self) -> tuple[str, ...]:
        return tuple(sorted(self.declarations))


def model_source_directory() -> Path:
    """Return the repository-local active model package directory."""
    return Path(__file__).resolve().parent / "models"


def model_module_names(models_directory: Path | None = None) -> tuple[str, ...]:
    """Return all active model modules in stable filename order.

    Backups intentionally do not have a ``.py`` suffix.  ``__init__`` is a package
    initializer rather than an independently declared model module.
    """
    directory = models_directory or model_source_directory()
    return tuple(
        f"src.models.{path.stem}"
        for path in sorted(directory.glob("*.py"))
        if path.name != "__init__.py"
    )


def declared_model_tables(models_directory: Path | None = None) -> Mapping[str, ModelDeclaration]:
    """Read all active ``__tablename__`` constants without importing application code.

    A non-literal table declaration or duplicate table name is an inventory failure:
    silently omitting either would permit incomplete migration coverage.
    """
    directory = models_directory or model_source_directory()
    declarations: dict[str, ModelDeclaration] = {}
    module_names = model_module_names(directory)
    for module in module_names:
        path = directory / f"{module.rsplit('.', 1)[-1]}.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise SchemaInventoryError(f"Cannot parse active model source {path}: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            table_values = [
                statement.value
                for statement in node.body
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                for target in (statement.targets if isinstance(statement, ast.Assign) else [statement.target])
                if isinstance(target, ast.Name) and target.id == "__tablename__"
            ]
            if not table_values:
                continue
            if len(table_values) != 1 or not isinstance(table_values[0], ast.Constant) or not isinstance(table_values[0].value, str):
                raise SchemaInventoryError(
                    f"{path}:{node.lineno} {node.name} must use one literal string __tablename__"
                )
            table_name = table_values[0].value
            declaration = ModelDeclaration(table_name, module, node.name, path, node.lineno)
            previous = declarations.get(table_name)
            if previous is not None:
                raise SchemaInventoryError(
                    f"Duplicate active table declaration {table_name!r}: "
                    f"{previous.module}.{previous.class_name} and {module}.{node.name}"
                )
            declarations[table_name] = declaration
    return MappingProxyType(dict(sorted(declarations.items())))


def _require_isolated_model_import_environment() -> None:
    """Reject model imports unless the caller is the isolated staging runner."""
    if os.environ.get("FLASK_TESTING", "").lower() != "true" or os.environ.get("MARKETEDGEPROS_STAGING_INNER") != "1":
        raise SchemaInventoryError(
            "Complete model metadata import requires the isolated staging runner"
        )
    database_url = os.environ.get("STAGING_PG_URL")
    if not database_url:
        raise SchemaInventoryError(
            "Complete model metadata import requires a declared synthetic staging target"
        )
    try:
        from migrations.target_safety import validate_isolated_postgresql_target

        # The validator checks only the explicit synthetic URL and runner-owned
        # socket/namespace metadata; it does not create a connection.
        validate_isolated_postgresql_target(database_url)
    except Exception as exc:  # noqa: BLE001 - never expose a target URL in diagnostics.
        raise SchemaInventoryError(
            "Complete model metadata import requires a validated isolated staging target"
        ) from exc


def load_complete_model_inventory(models_directory: Path | None = None) -> SchemaInventory:
    """Explicitly import all active models and verify their metadata coverage.

    Import errors are collected and raised; no model is skipped.  Mapper
    configuration catches relationship errors without an application factory or a
    database connection.  A legacy ``programs`` table is deliberately absent from
    active metadata, but is not a declared model table and is therefore outside this
    inventory's exact declared-vs-loaded contract.
    """
    _require_isolated_model_import_environment()
    declarations = declared_model_tables(models_directory)
    modules = model_module_names(models_directory)
    errors: dict[str, str] = {}
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - report all source defects together.
            errors[module] = f"{type(exc).__name__}: {exc}"
    if errors:
        detail = "; ".join(f"{module}: {message}" for module, message in sorted(errors.items()))
        raise SchemaInventoryError(f"Active model import failed: {detail}")

    try:
        from sqlalchemy.orm import configure_mappers
        from src.database import db

        configure_mappers()
    except Exception as exc:  # noqa: BLE001 - mapper defects are schema defects here.
        raise SchemaInventoryError(f"Active model mapper configuration failed: {type(exc).__name__}: {exc}") from exc

    metadata_tables = tuple(sorted(db.metadata.tables))
    declared_tables = tuple(sorted(declarations))
    missing_from_metadata = sorted(set(declared_tables) - set(metadata_tables))
    unexpected_metadata = sorted(set(metadata_tables) - set(declared_tables))
    if missing_from_metadata or unexpected_metadata:
        details = []
        if missing_from_metadata:
            details.append("declared but not loaded: " + ", ".join(missing_from_metadata))
        if unexpected_metadata:
            details.append("loaded but not declared: " + ", ".join(unexpected_metadata))
        raise SchemaInventoryError("Active model metadata inventory mismatch; " + "; ".join(details))

    # Keep legacy targets visible without forcing SQLAlchemy to resolve them as
    # current-model metadata.  In this repository affiliate_referrals references
    # the historical ``programs`` table, which revision 005 creates before 000003.
    # Access target_fullname only: resolving ``element.column`` would incorrectly
    # require a present-day ORM class for that legacy table.
    metadata_set = set(metadata_tables)
    external_targets: dict[str, tuple[str, ...]] = {}
    for table_name, table in sorted(db.metadata.tables.items()):
        targets = {
            element.target_fullname.rsplit(".", 1)[0]
            for foreign_key in table.foreign_key_constraints
            for element in foreign_key.elements
            if element.target_fullname.rsplit(".", 1)[0] not in metadata_set
        }
        if targets:
            external_targets[table_name] = tuple(sorted(targets))
    return SchemaInventory(
        declarations,
        modules,
        metadata_tables,
        MappingProxyType(external_targets),
    )
