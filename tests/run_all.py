"""Run every check in this package.

    python3 -m tests.run_all --db /tmp/p10/wh.duckdb

A check is a module level function whose name starts with check_. If it takes one
argument it gets a context carrying an open read only connection, so database backed
checks and pure ones live side by side without ceremony.
"""

import argparse
import importlib
import inspect
import os
import pkgutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class Ctx:
    def __init__(self, con):
        self.con = con


def modules():
    for m in pkgutil.iter_modules([HERE]):
        if m.name.startswith("test_"):
            yield importlib.import_module("tests." + m.name)


def main(db_path):
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    ctx = Ctx(con)

    passed = failed = 0
    failures = []
    n_modules = 0
    for mod in sorted(modules(), key=lambda m: m.__name__):
        n_modules += 1
        checks = [
            (n, f) for n, f in vars(mod).items()
            if n.startswith("check_") and callable(f)
        ]
        if not checks:
            failures.append((mod.__name__, "module has no check_ functions"))
            failed += 1
            continue
        for name, fn in sorted(checks):
            try:
                if len(inspect.signature(fn).parameters) == 1:
                    fn(ctx)
                else:
                    fn()
                passed += 1
            except Exception as exc:
                failed += 1
                failures.append(("%s.%s" % (mod.__name__, name), traceback.format_exc().strip().splitlines()[-1]))
    con.close()

    for where, why in failures:
        print("FAIL %s\n     %s" % (where, why))
    print("%d modules, %d checks, %d passed, %d failed" % (n_modules, passed + failed, passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "warehouse", "retail.duckdb"))
    a = ap.parse_args()
    sys.exit(main(a.db))
