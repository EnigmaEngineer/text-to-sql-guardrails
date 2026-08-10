"""Checks on the read-only role and the gate in front of it.

The cases that matter here are the ones that a read-only connection allows. A test suite
that only proves INSERT is blocked is testing DuckDB, not this repo.
"""

import json
import os

from agent import role
from tests.harness import eq, true, raises

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_select_is_allowed(ctx):
    d = role.inspect(ctx.con, "SELECT 1 AS a")
    true(d.allowed, "a plain select")
    eq(d.statements, 1, "statement count")
    eq(d.reason, "single_read", "reason")


def check_stacked_statements_are_refused(ctx):
    """The exploit. This exact string ran on a read-only connection and wrote a file.

    The reason it comes back with is `not_a_read` rather than `multiple_statements`,
    which surprised me. `json_serialize_sql` fails on the whole string as soon as one
    statement in it is not a SELECT, so the COPY is what trips it and the statement
    count is never reached. I had asserted `multiple_statements` here and the test
    failed. The refusal was right and my label for it was wrong.

    Worth being precise about, because `multiple_statements` sounds like the defence
    against stacking and it only fires when every statement is a read. The check below
    covers that half.
    """
    sql = ("SELECT 1 AS ok; COPY (SELECT customer_email FROM retail.dim_customer) "
           "TO '/tmp/should-not-exist.csv' (FORMAT CSV)")
    d = role.inspect(ctx.con, sql)
    true(not d.allowed, "stacked statements")
    eq(d.reason, "not_a_read", "reason")
    true(not os.path.exists("/tmp/should-not-exist.csv"), "no file was written")


def check_two_harmless_selects_are_still_refused(ctx):
    """Both halves are reads and it is still two statements.

    The rule is one statement, not one dangerous statement. If this were allowed the
    gate would have to reason about what the second one does, which is the regex path
    this design exists to avoid.
    """
    d = role.inspect(ctx.con, "SELECT 1; SELECT 2")
    true(not d.allowed, "two selects")
    eq(d.reason, "multiple_statements", "reason")
    eq(d.statements, 2, "counted both")


def check_copy_to_file_is_refused(ctx):
    d = role.inspect(ctx.con, "COPY (SELECT 1 AS a) TO '/tmp/x.csv' (FORMAT CSV)")
    true(not d.allowed, "copy")
    eq(d.reason, "not_a_read", "reason")


def check_export_database_is_refused(ctx):
    d = role.inspect(ctx.con, "EXPORT DATABASE '/tmp/dump' (FORMAT CSV)")
    true(not d.allowed, "export")
    eq(d.reason, "not_a_read", "reason")


def check_write_statements_are_refused(ctx):
    for sql in [
        "INSERT INTO retail.dim_customer VALUES (1)",
        "UPDATE retail.dim_customer SET full_name='x'",
        "DELETE FROM retail.dim_customer",
        "DROP TABLE retail.fct_return",
        "CREATE TABLE zz (a INT)",
        "ALTER TABLE retail.dim_customer ADD COLUMN zz INT",
        "ATTACH '/tmp/side.duckdb' AS side",
        "INSTALL httpfs",
        "SET memory_limit='1GB'",
    ]:
        d = role.inspect(ctx.con, sql)
        true(not d.allowed, "refused: %s" % sql[:28])
        eq(d.reason, "not_a_read", "reason for %s" % sql[:28])


def check_empty_input_is_refused(ctx):
    """A gate that approves nothing at all is the 08-04 prose_check bug.

    Whitespace and bare semicolons parse without error into zero statements, so the
    serializer reports no problem and there is nothing to run. Both paths into `empty`
    are covered, the short circuit on a blank string and the zero statement count.
    """
    for sql in ["", "   ", None]:
        eq(role.inspect(ctx.con, sql).reason, "empty", "blank input %r" % sql)
    for sql in [";", ";;", "  ;  ;  "]:
        d = role.inspect(ctx.con, sql)
        eq(d.reason, "empty", "semicolons only %r" % sql)
        eq(d.statements, 0, "counted zero")


def check_garbage_is_unparseable_not_a_write(ctx):
    """Two different refusals. Day 6 sends different feedback for each."""
    d = role.inspect(ctx.con, "SELECT FROM WHERE")
    true(not d.allowed, "garbage")
    eq(d.reason, "unparseable", "reason")
    true(bool(d.detail), "carries the parser message")


def check_semicolon_inside_a_string_does_not_split(ctx):
    """A regex splitting on the statement terminator would call this two. The parser does not."""
    d = role.inspect(ctx.con, "SELECT 'a; DROP TABLE t' AS a")
    true(d.allowed, "semicolon in a literal")
    eq(d.statements, 1, "one statement")


def check_the_word_copy_inside_a_string_is_not_a_copy(ctx):
    d = role.inspect(ctx.con, "SELECT 'COPY (SELECT 1) TO ''/tmp/x''' AS a")
    true(d.allowed, "copy in a literal")


def check_trailing_semicolon_is_fine(ctx):
    for sql in ["SELECT 1;", "SELECT 1;   ", "SELECT 1;\n"]:
        true(role.inspect(ctx.con, sql).allowed, "trailing semicolon %r" % sql)


def check_set_operations_are_allowed(ctx):
    """No gold query uses UNION and the gate still has to allow it.

    An allowlist of node types written against today's eval set would reject a correct
    query the moment a question needed one, and it would look like a guardrail working.
    """
    d = role.inspect(ctx.con, "SELECT 1 AS a UNION ALL SELECT 2")
    true(d.allowed, "union")
    eq(d.node_types, ("SET_OPERATION_NODE",), "node type")


def check_every_gold_query_passes_the_gate(ctx):
    """If the gate rejects the answer key, the gate is wrong."""
    from evals import gold

    rows = gold.answerable()
    true(len(rows) == 22, "22 answerable questions, got %d" % len(rows))
    for row in rows:
        d = role.inspect(ctx.con, row["gold_sql"])
        true(d.allowed, "%s gold query passes the gate: %s" % (row["id"], d.reason))


def check_the_gate_alone_approves_a_query_that_reads_the_host(ctx):
    """The day 4 finding, pinned where the day 3 gate lives.

    `read_csv` on a path is a single SELECT, so this layer approves it and is right to.
    Refusing it is `agent.validate`'s job. The check is here so that anyone reading
    `role.py` and concluding the gate is the guardrail meets the counterexample in the
    same file's tests.
    """
    for sql in (
        "SELECT * FROM read_csv('/etc/hostname')",
        "SELECT * FROM glob('/etc/*')",
    ):
        d = role.inspect(ctx.con, sql)
        true(d.allowed, "the parser gate alone approves %r" % sql)


def check_read_only_connection_still_allows_copy(ctx):
    """The finding, pinned as a test.

    This is the reason the gate exists. If a future DuckDB starts refusing COPY on a
    read-only connection, this check fails and that is a good failure. It means the
    second layer got stronger and the comment in role.py needs rewriting.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        target = os.path.join(work, "leak.csv")
        ctx.con.execute(
            "COPY (SELECT customer_email FROM retail.dim_customer LIMIT 5) TO '%s' (FORMAT CSV)"
            % target
        )
        true(os.path.exists(target), "read-only connection wrote a file")
        with open(target) as fh:
            # Six, not five. COPY TO CSV writes a header unless told not to, which I did
            # not know and which the first run of this check told me.
            eq(sum(1 for _ in fh), 6, "five rows plus a header")


def check_decision_serialises_for_the_trace(ctx):
    d = role.inspect(ctx.con, "SELECT 1")
    payload = json.loads(json.dumps(d.as_dict()))
    eq(sorted(payload), ["allowed", "detail", "node_types", "reason", "statements"], "keys")
