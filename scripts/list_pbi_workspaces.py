"""
List all Power BI / Fabric workspaces visible to a tenant admin service principal,
written to a CSV.

Authenticates via SPN client-credentials flow (bearer token) and calls the
Power BI Admin API:
  GET https://api.powerbi.com/v1.0/myorg/admin/groups

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
  .venv/Scripts/python.exe scripts/list_pbi_workspaces.py --output pbi_workspaces.csv
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

CSV_FIELDS = [
    "id",
    "name",
    "type",
    "state",
    "isOnDedicatedCapacity",
    "capacityId",
]


def main():
    load_env()

    parser = argparse.ArgumentParser(description="List Power BI / Fabric workspaces to a CSV.")
    add_credential_args(parser)
    parser.add_argument("--output", default="pbi_workspaces.csv", help="Path to the output CSV file.")
    args = parser.parse_args()
    require_credentials(args, parser)

    token_manager = AccessTokenManager(args.tenant_id, args.client_id, args.client_secret)

    logger.info("Fetching workspaces from Power BI Admin API")
    workspaces = list(paginated_admin_get(f"{ADMIN_API_BASE}/groups", token_manager))
    logger.info("Retrieved %d workspaces", len(workspaces))

    write_csv(workspaces, CSV_FIELDS, args.output)
    logger.info("Wrote workspaces to %s", args.output)


if __name__ == "__main__":
    main()
