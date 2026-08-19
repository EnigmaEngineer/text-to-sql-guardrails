"""Warehouse dialect adapter.

There is no Snowflake account behind this, so every day is verified against
DuckDB and the Snowflake path is written alongside and left unverified until a trial
account is available. The point of this file is that the Snowflake strings are visible
and reviewable now rather than invented in a hurry at the end.

Anything returned by `snowflake()` has NOT been executed against Snowflake. Do not
quote a number that came through it.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dialect:
    name: str
    # Snowflake folds unquoted identifiers to upper case, DuckDB to lower. This decides
    # whether a validator comparing a generated column name against the catalog should
    # casefold up or down, which is static validation's problem and is easy to get backwards.
    unquoted_case: str
    explain_prefix: str
    verified: bool
    supports_information_schema: bool = True
    notes: str = ""

    def fold(self, identifier: str) -> str:
        if identifier.startswith('"') and identifier.endswith('"'):
            return identifier[1:-1]
        return identifier.upper() if self.unquoted_case == "upper" else identifier.lower()

    def explain(self, sql: str) -> str:
        return "%s %s" % (self.explain_prefix, sql.rstrip().rstrip(";"))


def duckdb() -> Dialect:
    return Dialect(
        name="duckdb",
        unquoted_case="lower",
        explain_prefix="EXPLAIN",
        verified=True,
        notes="everything in this repo is measured here",
    )


def snowflake() -> Dialect:
    return Dialect(
        name="snowflake",
        unquoted_case="upper",
        # EXPLAIN USING JSON is what the cost layer will want, because the text form has to be
        # parsed and the JSON form carries bytesScanned directly.
        explain_prefix="EXPLAIN USING JSON",
        verified=False,
        notes="written from the docs, never executed. TODO: validate on a trial account "
              "in one pass near the end of the program, per the 07-25 decision.",
    )


DIALECTS = {"duckdb": duckdb, "snowflake": snowflake}


def get(name: str) -> Dialect:
    if name not in DIALECTS:
        raise KeyError("unknown dialect %r, have %s" % (name, sorted(DIALECTS)))
    return DIALECTS[name]()
