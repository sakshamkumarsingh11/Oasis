"""
SIH26143 — AIS Pipeline: DuckDB Store

Connection management and data registration for querying AIS data
via DuckDB. Supports both raw CSV querying (development) and
Parquet querying (production).

Reference:
    Pipeline §14 (DuckDB role), §15 (basic queries).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb

logger = logging.getLogger(__name__)


def connect(db_path: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """
    Open a DuckDB connection.

    Args:
        db_path: Path to a persistent DuckDB file. If None, uses in-memory.

    Returns:
        DuckDB connection object.
    """
    if db_path:
        logger.info("Connecting to DuckDB file: %s", db_path)
        con = duckdb.connect(db_path)
    else:
        logger.info("Connecting to DuckDB in-memory.")
        con = duckdb.connect()

    return con


def register_csv_data(
    con: duckdb.DuckDBPyConnection,
    csv_glob: str,
    view_name: str = "ais_data",
) -> None:
    """
    Register raw CSV files as a DuckDB view using read_csv_auto().

    This is the development path — DuckDB scans CSV files directly
    without requiring a Parquet conversion step.

    Pipeline §14: DuckDB can query CSVs directly.

    Args:
        con: DuckDB connection.
        csv_glob: Glob pattern for CSV files, e.g.
                  'ais dataset/ais-*.csv'
        view_name: Name of the SQL view to create.
    """
    # Normalise path separators for DuckDB (use forward slashes)
    csv_glob_normalised = csv_glob.replace("\\", "/")

    sql = f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT *
        FROM read_csv_auto('{csv_glob_normalised}',
                           header=true,
                           filename=true)
    """
    con.execute(sql)
    logger.info("Registered CSV view '%s' from: %s", view_name, csv_glob)


def register_parquet_data(
    con: duckdb.DuckDBPyConnection,
    parquet_glob: str,
    view_name: str = "ais_data",
) -> None:
    """
    Register Parquet files as a DuckDB view.

    Pipeline §13–14: Parquet is the production query format.

    Args:
        con: DuckDB connection.
        parquet_glob: Glob pattern for Parquet files.
        view_name: Name of the SQL view to create.
    """
    parquet_glob_normalised = parquet_glob.replace("\\", "/")

    sql = f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT *
        FROM read_parquet('{parquet_glob_normalised}')
    """
    con.execute(sql)
    logger.info("Registered Parquet view '%s' from: %s", view_name, parquet_glob)


def get_table_stats(
    con: duckdb.DuckDBPyConnection,
    view_name: str = "ais_data",
) -> dict:
    """
    Get basic statistics about the registered AIS data.

    Returns:
        Dict with row_count, unique_mmsis, date_min, date_max.
    """
    result = con.execute(f"""
        SELECT
            COUNT(*)                         AS row_count,
            COUNT(DISTINCT mmsi)             AS unique_mmsis,
            MIN(base_date_time)              AS date_min,
            MAX(base_date_time)              AS date_max
        FROM {view_name}
    """).fetchone()

    stats = {
        "row_count": result[0],
        "unique_mmsis": result[1],
        "date_min": str(result[2]) if result[2] else None,
        "date_max": str(result[3]) if result[3] else None,
    }
    logger.info("AIS data stats: %s", stats)
    return stats
