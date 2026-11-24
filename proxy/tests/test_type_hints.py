"""Step 12: public functions of state.py, proxy_logic.py and generate.py carry type hints.
Checked with inspect only; mypy is not a dependency (not approved)."""
import inspect
import typing

import pytest

from xg_netpolicy import generate, proxy_logic, state


def _public_functions(mod):
    for name, obj in vars(mod).items():
        if name.startswith("_") or getattr(obj, "__module__", None) != mod.__name__:
            continue
        if inspect.isfunction(obj):
            yield name, obj
        elif inspect.isclass(obj):
            for mname, m in vars(obj).items():
                if isinstance(m, (classmethod, staticmethod)):
                    m = m.__func__
                if inspect.isfunction(m) and (mname == "__init__" or not mname.startswith("_")):
                    yield f"{name}.{mname}", m


@pytest.mark.parametrize("mod", [state, proxy_logic, generate], ids=lambda m: m.__name__)
def test_public_functions_are_annotated(mod):
    missing = []
    for name, fn in _public_functions(mod):
        typing.get_type_hints(fn)  # every annotation resolves (from __future__ makes them strings)
        sig = inspect.signature(fn)
        for p in sig.parameters.values():
            if p.name in ("self", "cls"):
                continue
            if p.annotation is inspect.Parameter.empty:
                missing.append(f"{name}({p.name})")
        if sig.return_annotation is inspect.Signature.empty:
            missing.append(f"{name} -> ?")
    assert not missing, missing
