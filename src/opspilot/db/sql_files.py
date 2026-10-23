"""Read SQL files that hold several named queries.

Format:

    -- Anything before the first name line is a file header and is ignored.

    -- name: query_name
    -- Comment lines right after the name describe the query.
    SELECT ...;

Used by both the data-quality checks and the analysis queries, so the SQL
stays in plain .sql files that also run unchanged in psql.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NamedQuery:
    name: str
    comments: list[str]  # full-line comments, without the leading "--"
    sql: str


def parse_named_queries(text: str) -> list[NamedQuery]:
    queries = []
    for block in re.split(r"^-- name:", text, flags=re.MULTILINE)[1:]:
        name, _, body = block.partition("\n")
        name = name.strip()
        lines = body.splitlines()
        comments = [line.lstrip()[2:].strip() for line in lines if line.lstrip().startswith("--")]
        sql = "\n".join(line for line in lines if not line.lstrip().startswith("--")).strip().rstrip(";")
        if not sql:
            raise ValueError(f"query {name!r} has no SQL")
        queries.append(NamedQuery(name, comments, sql))

    names = [query.name for query in queries]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ValueError(f"duplicate query names: {sorted(duplicates)}")
    return queries
