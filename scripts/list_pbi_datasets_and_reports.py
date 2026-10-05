"""
List all datasets and reports across every Power BI / Fabric workspace,
written to two CSVs.

Authenticates via SPN client-credentials flow (bearer token) and calls the
Power BI Admin API:
  GET https://api.powerbi.com/v1.0/myorg/admin/groups?$expand=datasets,reports

Prerequisites:
  - Azure AD app registration (SPN) allow-listed under Power BI Admin Portal >
    Tenant settings > Admin API settings > "Service principals can access
    read-only admin APIs". The app itself must have NO admin-consent-required
    API permissions configured - access is granted purely through the
    security-group allow-list, and any admin-consent-required permission on
    the app breaks SPN auth to these APIs. See PBI_ADMIN_SETUP.md.

Env vars (or pass via CLI args):
  AZURE_TENANT_ID
  AZURE_CLIENT_ID
  AZURE_CLIENT_SECRET

Usage:
  .venv/Scripts/python.exe scripts/list_pbi_datasets_and_reports.py \
      --datasets-output pbi_datasets.csv --reports-output pbi_reports.csv
"""
import argparse
import logging

from pbi_admin_common import (
    ADMIN_API_BASE,
    AccessTokenManager,
    add_credential_args,
    load_env,
    paginated_admin_get,
    require_credentials,
    write_csv,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATASET_CSV_FIELDS = [
    "workspace_id",
    "workspace_name",
    "id",
    "name",
    "configuredBy",
    "isRefreshable",
    "addRowsAPIEnabled",
    "targetStorageMode",
]

REPORT_CSV_FIELDS = [
    "workspace_id",
    "workspace_name",
    "id",
    "name",
    "datasetId",
    "webUrl",
]


def main():
    load_env()

    parser = argparse.ArgumentParser(description="List Power BI / Fabric datasets and reports to CSVs.")
    add_credential_args(parser)
    parser.add_argument("--datasets-output", default="pbi_datasets.csv", help="Path to the datasets CSV file.")
    parser.add_argument("--reports-output", default="pbi_reports.csv", help="Path to the reports CSV file.")
    args = parser.parse_args()
    require_credentials(args, parser)

    token_manager = AccessTokenManager(args.tenant_id, args.client_id, args.client_secret)

    logger.info("Fetching workspaces (with datasets and reports) from Power BI Admin API")
    workspaces = paginated_admin_get(
        f"{ADMIN_API_BASE}/groups",
        token_manager,
        params={"$expand": "datasets,reports"},
    )

    dataset_rows = []
    report_rows = []

    for workspace in workspaces:
        workspace_id = workspace.get("id")
        workspace_name = workspace.get("name")

        for dataset in workspace.get("datasets") or []:
            row = dict(dataset)
            row["workspace_id"] = workspace_id
            row["workspace_name"] = workspace_name
            dataset_rows.append(row)

        for report in workspace.get("reports") or []:
            row = dict(report)
            row["workspace_id"] = workspace_id
            row["workspace_name"] = workspace_name
            report_rows.append(row)

    logger.info("Retrieved %d datasets across all workspaces", len(dataset_rows))
    logger.info("Retrieved %d reports across all workspaces", len(report_rows))

    write_csv(dataset_rows, DATASET_CSV_FIELDS, args.datasets_output)
    write_csv(report_rows, REPORT_CSV_FIELDS, args.reports_output)

    logger.info("Wrote datasets to %s", args.datasets_output)
    logger.info("Wrote reports to %s", args.reports_output)


if __name__ == "__main__":
    main()
