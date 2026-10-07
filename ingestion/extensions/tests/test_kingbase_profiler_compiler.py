from sqlalchemy import func
from sqlalchemy.dialects import registry

import kingbase_connector.kingbase_dialect  # noqa: F401
from metadata.profiler.orm.functions.modulo import ModuloFn
from metadata.profiler.orm.functions.random_num import RandomNumFn


def _load_kingbase_dialect():
    return registry.load("kingbase8")()


def test_kingbase_sampler_compiles_integer_random_and_mod_function():
    expression = ModuloFn(RandomNumFn(), 100)

    compiled = str(
        expression.compile(dialect=_load_kingbase_dialect())
    ).upper()

    assert compiled == "MOD(ABS((RANDOM() * 100)::INTEGER), ?)"
    assert "%%" not in compiled


def test_kingbase_sampler_compiles_count_denominator():
    expression = ModuloFn(RandomNumFn(), func.count())

    compiled = str(
        expression.compile(dialect=_load_kingbase_dialect())
    ).upper()

    assert compiled == "MOD(ABS((RANDOM() * 100)::INTEGER), COUNT(*))"
    assert "%%" not in compiled
