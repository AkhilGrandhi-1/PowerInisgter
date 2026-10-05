"""
List all tables and columns across every Power BI / Fabric semantic model
(dataset) in the tenant, written to two CSVs.

Unlike the other list_pbi_*.py scripts, this one uses the Admin *scanner*
API workflow instead of a single paginated GET, because table/column
schema is only available through a scan:

  GET  /admin/workspaces/modified          - list workspace IDs to scan
  POST /admin/workspaces/getInfo           - start a scan (datasetSchema=true)
  GET  /admin/workspaces/scanStatus/{id}   - poll until Succeeded
  GET  /admin/workspaces/scanResult/{id}   - download tables/columns

Prerequisites:
  - Same SPN setup as the other list_pbi_*.py scripts (see
    PBI_ADMIN_SETUP.md).
  - Admin portal > Tenant settings > Admin API settings >
    "Enhance admin APIs responses with detailed metadata" must be Enabled,
    otherwise scans return workspaces/datasets but no table or column data.

Env vars (or pass via CLI args):
  AZURE_TENANT_ID
  AZURE_CLIENT_ID
  AZURE_CLIENT_SECRET

Usage:
  .venv/Scripts/python.exe scripts/list_pbi_tables_and_columns.py \
      --tables-output pbi_tables.csv --columns-output pbi_columns.csv
"""
import argparse
import logging

from pbi_admin_common import (
    AccessTokenManager,
    add_credential_args,
    chunked,
    get_all_workspace_ids,
    get_scan_result,
    load_env,
    require_credentials,
    start_scan,
    wait_for_scan,
    write_csv,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE_BATCH_SIZE = 100  # PostWorkspaceInfo accepts 1-100 workspace IDs per call

TABLE_CSV_FIELDS = [
    "workspace_id",
    "workspace_name",
    "dataset_id",
    "dataset_name",
    "table_name",
    "isHidden",
    "description",
]

COLUMN_CSV_FIELDS = [
    "workspace_id",
    "workspace_name",
    "dataset_id",
    "dataset_name",
    "table_name",
    "column_name",
    "dataType",
    "isHidden",
    "formatString",
    "dataCategory",
    "summarizeBy",
]


def main():
    load_env()

    parser = argparse.ArgumentParser(
        description="List all semantic model tables and columns to CSVs via the Power BI scanner API."
    )
    add_credential_args(parser)
    parser.add_argument("--tables-output", default="pbi_tables.csv", help="Path to the tables CSV file.")
    parser.add_argument("--columns-output", default="pbi_columns.csv", help="Path to the columns CSV file.")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between scan status polls.")
    parser.add_argument("--scan-timeout", type=int, default=600, help="Seconds to wait for each scan to finish.")
    args = parser.parse_args()
    require_credentials(args, parser)

    token_manager = AccessTokenManager(args.tenant_id, args.client_id, args.client_secret)

    logger.info("Listing all workspace IDs")
    workspace_ids = get_all_workspace_ids(token_manager)
    logger.info("Found %d workspaces to scan", len(workspace_ids))

    table_rows = []
    column_rows = []

    batches = list(chunked(workspace_ids, WORKSPACE_BATCH_SIZE))
    for batch_num, batch in enumerate(batches, start=1):
        logger.info("Scanning batch %d/%d (%d workspaces)", batch_num, len(batches), len(batch))

        scan_id = start_scan(token_manager, batch, dataset_schema=True)
        wait_for_scan(token_manager, scan_id, poll_interval=args.poll_interval, timeout=args.scan_timeout)
        result = get_scan_result(token_manager, scan_id)

        for workspace in result.get("workspaces", []):
            workspace_id = workspace.get("id")
            workspace_name = workspace.get("name")

            for dataset in workspace.get("datasets") or []:
                dataset_id = dataset.get("id")
                dataset_name = dataset.get("name")

                for table in dataset.get("tables") or []:
                    table_name = table.get("name")
                    table_rows.append({
                        "workspace_id": workspace_id,
                        "workspace_name": workspace_name,
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "table_name": table_name,
                        "isHidden": table.get("isHidden", False),
                        "description": table.get("description"),
                    })

                    for column in table.get("columns") or []:
                        column_rows.append({
                            "workspace_id": workspace_id,
                            "workspace_name": workspace_name,
                            "dataset_id": dataset_id,
                            "dataset_name": dataset_name,
                            "table_name": table_name,
                            "column_name": column.get("name"),
                            "dataType": column.get("dataType"),
                            "isHidden": column.get("isHidden", False),
                            "formatString": column.get("formatString"),
                            "dataCategory": column.get("dataCategory"),
                            "summarizeBy": column.get("summarizeBy"),
                        })

    logger.info("Retrieved %d tables across all datasets", len(table_rows))
    logger.info("Retrieved %d columns across all tables", len(column_rows))

    write_csv(table_rows, TABLE_CSV_FIELDS, args.tables_output)
    write_csv(column_rows, COLUMN_CSV_FIELDS, args.columns_output)

    logger.info("Wrote tables to %s", args.tables_output)
    logger.info("Wrote columns to %s", args.columns_output)


if __name__ == "__main__":
    main()
