"""
List all Power BI / Fabric capacities visible to a tenant admin service principal
and write them to a CSV.

Authenticates via SPN client-credentials flow against the Power BI Admin API:
  GET https://api.powerbi.com/v1.0/myorg/admin/capacities

Prerequisites:
  - Azure AD app registration (SPN) allow-listed under Power BI Admin Portal >
    Tenant settings > Admin API settings > "Service principals can access
    read-only admin APIs". The app itself must have NO admin-consent-required
    API permissions configured (not Tenant.Read.All, not anything else) -
    access is granted purely through the security-group allow-list, and any
    admin-consent-required permission on the app breaks SPN auth to these
    APIs. See PBI_ADMIN_SETUP.md for the full setup.

Env vars (or pass via CLI args):
  AZURE_TENANT_ID
  AZURE_CLIENT_ID
  AZURE_CLIENT_SECRET

Usage:
  .venv/Scripts/python.exe scripts/list_pbi_capacities.py --output pbi_capacities.csv
"""
import argparse
import logging

from pbi_admin_common import (
    AccessTokenManager,
    add_credential_args,
    get_capacities,
    load_env,
    require_credentials,
    write_csv,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "id",
    "displayName",
    "sku",
    "state",
    "region",
    "capacityUserAccessRight",
    "admins",
]


def main():
    load_env()

    parser = argparse.ArgumentParser(description="List Power BI / Fabric capacities to a CSV.")
    add_credential_args(parser)
    parser.add_argument("--output", default="pbi_capacities.csv", help="Path to the output CSV file.")
    args = parser.parse_args()
    require_credentials(args, parser)

    token_manager = AccessTokenManager(args.tenant_id, args.client_id, args.client_secret)

    logger.info("Fetching capacities from Power BI Admin API")
    capacities = get_capacities(token_manager)
    logger.info("Retrieved %d capacities", len(capacities))

    rows = []
    for capacity in capacities:
        row = dict(capacity)
        row["admins"] = "; ".join(row.get("admins") or [])
        rows.append(row)

    write_csv(rows, CSV_FIELDS, args.output)
    logger.info("Wrote capacities to %s", args.output)

    for capacity in capacities:
        logger.info(
            "%s | sku=%s | state=%s | region=%s",
            capacity.get("displayName"),
            capacity.get("sku"),
            capacity.get("state"),
            capacity.get("region"),
        )


if __name__ == "__main__":
    main()
