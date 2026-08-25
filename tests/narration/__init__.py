"""Phase 24 narration tests.

A real package, with a real ``__init__.py``, from the first candidate. The
Phase 23 suite learned this the expensive way: two of its modules imported a
helper as ``from tests.render_execution.conftest import ...``, which resolves
only when the repository root is on ``sys.path``. That is true under
``python -m pytest``, which prepends the working directory, and false under the
bare ``pytest`` console script that CI actually invokes -- so a real defect
survived seven candidate rounds of green local gates and only appeared in the
first live CI run.

Modules here import shared helpers as ``from .conftest import ...``, which
resolves identically under both invocations.
"""
