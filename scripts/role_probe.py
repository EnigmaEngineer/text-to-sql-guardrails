"""Measure what a read-only DuckDB connection actually blocks.

    python3 scripts/role_probe.py --db /tmp/p10/wh.duckdb

The README quotes this table, so it lives here rather than in a scratch file. Every row
is executed against a throwaway copy of the warehouse, because two of the cases would
modify it if they were ever allowed to.

A note on how this script was wrong the first time it ran. Three statements came back
refused and the reason was a binder error about a column that does not exist, not the
read-only role. The SQL in the probe was simply malformed. `INSERT` with the wrong column
count and `UPDATE` on a misspelled column both fail on a writable connection too, so the
probe was reporting a protection that had not been tested. Every case now runs against a
writable copy first, and a case that fails on both connections is reported as `INVALID`
rather than as blocked. A probe that cannot tell those apart is not a probe.
"""

import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb


def cases(outdir):
    """(label, sql, writes_outside_the_database).

    The last flag marks the cases that are the point of this script. They do not touch
    the database, so the read-only role has no opinion, and they move data anyway.
    """
    return [
        ("SELECT", "SELECT count(*) FROM retail.dim_customer", False),
        ("INSERT", "INSERT INTO retail.dim_customer VALUES "
                   "(999999,'a@b.invalid','n',DATE '2024-01-01','GB','X','gold',true,true)", False),
        ("UPDATE", "UPDATE retail.dim_customer SET full_name='x' WHERE customer_id=1", False),
        ("DELETE", "DELETE FROM retail.dim_customer WHERE customer_id=1", False),
        ("CREATE TABLE", "CREATE TABLE retail.zz (a INT)", False),
        ("DROP TABLE", "DROP TABLE retail.fct_return", False),
        ("ALTER TABLE", "ALTER TABLE retail.dim_customer ADD COLUMN zz INT", False),
        ("CREATE VIEW", "CREATE VIEW retail.vv AS SELECT 1 AS a", False),
        ("CREATE TEMP TABLE", "CREATE TEMP TABLE zz AS SELECT 1 AS a", False),
        ("COPY TO file", "COPY (SELECT full_name, customer_email FROM retail.dim_customer) "
                         "TO '%s' (FORMAT CSV, HEADER)" % os.path.join(outdir, "copy.csv"), True),
        ("EXPORT DATABASE", "EXPORT DATABASE '%s' (FORMAT CSV)" % os.path.join(outdir, "dump"), True),
        ("read a host file", "SELECT count(*) FROM read_csv('/etc/hostname', header=false, "
                             "columns={'l':'VARCHAR'})", True),
        ("INSTALL extension", "INSTALL httpfs", True),
        ("SET memory_limit", "SET memory_limit='128MB'", False),
        ("stacked SELECT plus COPY",
         "SELECT 1 AS ok; COPY (SELECT customer_email FROM retail.dim_customer) TO '%s' (FORMAT CSV)"
         % os.path.join(outdir, "stacked.csv"), True),
    ]


def attempt(con, sql):
    try:
        con.execute(sql)
        return True, ""
    except Exception as exc:
        return False, str(exc).splitlines()[0]


def why(message):
    """The part of a DuckDB error that says something.

    Every read-only refusal starts with the same forty characters of exception class and
    "Invalid Input Error", so printing the first N characters printed the same useless
    prefix on every row. The sentence that matters names the statement type.
    """
    marker = "Cannot execute statement of type "
    if marker in message:
        rest = message.split(marker, 1)[1]
        return "read-only rejects " + rest.split(" on database")[0].strip('"')
    return message[:52]


def main(db_path):
    work = tempfile.mkdtemp(prefix="roleprobe-")
    try:
        ro_db = os.path.join(work, "ro.duckdb")
        rw_db = os.path.join(work, "rw.duckdb")
        shutil.copyfile(db_path, ro_db)
        shutil.copyfile(db_path, rw_db)
        out = os.path.join(work, "out")
        os.makedirs(out, exist_ok=True)

        ro = duckdb.connect(ro_db, read_only=True)
        print("%-26s %-9s %s" % ("statement", "read-only", "note"))
        print("-" * 78)
        holes = 0
        for label, sql, outside in cases(out):
            ok_ro, err_ro = attempt(ro, sql)
            if not ok_ro:
                # Only now open a writable connection, and only to find out whether the
                # refusal was the role or a mistake in this file.
                rw = duckdb.connect(rw_db)
                ok_rw, _ = attempt(rw, sql)
                rw.close()
                if not ok_rw:
                    print("%-26s %-9s INVALID SQL, refused on both connections: %s"
                          % (label, "-", why(err_ro)))
                    continue
                print("%-26s %-9s %s" % (label, "blocked", why(err_ro)))
                continue
            if outside:
                holes += 1
                print("%-26s %-9s allowed, and it acts outside the database" % (label, "ALLOWED"))
            else:
                print("%-26s %-9s allowed" % (label, "allowed"))
        ro.close()

        print("-" * 78)
        # Walked rather than listed, because EXPORT DATABASE writes a directory and a
        # flat listing of files reported it as having left nothing behind.
        written = []
        for root, _dirs, files in os.walk(out):
            for name in files:
                path = os.path.join(root, name)
                written.append((os.path.relpath(path, out), path))
        written.sort()
        print("files the read-only connection left on disk: %d" % len(written))
        for rel, path in written:
            with open(path, errors="replace") as fh:
                lines = sum(1 for _ in fh)
            print("  %-28s %6d lines" % (rel, lines))
        print("%d statements were allowed that act outside the database" % holes)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "warehouse", "retail.duckdb"))
    sys.exit(main(ap.parse_args().db))
