from types import SimpleNamespace

import pytest
from sqlalchemy import column, select
from sqlalchemy.dialects import registry
from sqlalchemy.exc import CompileError

from metadata.ingestion.source.database.customdatabase.connection import (
    CustomDatabaseConnectionAdapter,
)
from metadata.profiler.orm.functions.median import MedianFn
from metadata.profiler.orm.functions.modulo import ModuloFn
from metadata.profiler.orm.functions.random_num import RandomNumFn


def _load_dameng_dialect_from_connection_entrypoint():
    adapter = CustomDatabaseConnectionAdapter(
        SimpleNamespace(
            sourcePythonClass="dameng_connector.dameng_source.DamengSource"
        )
    )
    connection_module = adapter._connector_module()

    assert connection_module.__name__ == "dameng_connector.connection"
    return registry.load("dm")()


@pytest.mark.parametrize(
    ("percentile", "expected"),
    [(0.25, "0.25"), (0.5, "0.50"), (0.75, "0.75")],
)
def test_dm_median_compiles_percentiles_from_connection_entrypoint(
    percentile, expected
):
    expression = MedianFn(column("AGE"), "STUDENT", percentile)

    compiled = str(
        expression.compile(dialect=_load_dameng_dialect_from_connection_entrypoint())
    ).upper()

    assert f"PERCENTILE_CONT({expected})" in compiled
    assert 'WITHIN GROUP (ORDER BY "AGE" ASC) OVER()' in compiled


def test_dm_median_rejects_dimension_validation_from_connection_entrypoint():
    expression = MedianFn(column("AGE"), "STUDENT", 0.5, "normalized_dim")

    with pytest.raises(CompileError, match="dimension_col"):
        expression.compile(dialect=_load_dameng_dialect_from_connection_entrypoint())


def test_dm_sampler_compiles_dameng_random_and_modulo_functions():
    expression = ModuloFn(RandomNumFn(), 100)

    compiled = str(
        expression.compile(dialect=_load_dameng_dialect_from_connection_entrypoint())
    ).upper()

    assert "MOD(ABS(RAND()) * 100," in compiled
    assert "%%" not in compiled


def test_dm_limit_uses_fetch_first_with_literal_count():
    statement = select(column("AGE")).limit(1)

    compiled = str(
        statement.compile(
            dialect=_load_dameng_dialect_from_connection_entrypoint(),
            compile_kwargs={"render_postcompile": True},
        )
    ).upper()

    assert "FETCH FIRST 1 ROWS ONLY" in compiled
    assert "LIMIT" not in compiled
