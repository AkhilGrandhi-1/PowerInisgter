"""
ONE-TIME ADMIN BOOTSTRAP - creates the Entra security group and enables
service-principal access to the Power BI/Fabric read-only admin APIs, so the
reporting scripts in scripts/ can run.

This is deliberately kept separate from the reporting pipeline (scripts/,
run_all_pbi_reports.py). It does NOT use the reporting SPN's client-secret
credentials at all - it signs YOU in interactively (device code flow) and
acts with YOUR admin permissions, so there's an audit trail of who made the
change, and the reporting SPN never needs directory-write or tenant-setting
permissions.

WHO SHOULD RUN THIS
  A human with both:
    - An Entra ID role that can create security groups and add members to
      them (e.g. Groups Administrator, or Global Administrator).
    - The Fabric administrator role (to update tenant settings).
  Run it from your own machine, signed in as yourself - not as the SPN.

  During sign-in you'll be asked to consent (if you haven't already) to:
    Microsoft Graph: Group.ReadWrite.All, GroupMember.ReadWrite.All,
    Application.ReadWrite.All (the latter two are both required specifically
    to add a *service principal* - not a user - as a group member).
    Fabric: Tenant.ReadWrite.All.
  If your account can't consent to these itself, someone with Global/Cloud
  Application Administrator will need to grant admin consent for them first.

WHAT IT DOES
  1. Signs you in via device code flow (open a URL, enter a code).
  2. Looks up the reporting SPN's service principal by its app (client) ID.
  3. Creates the security group (or reuses it if it already exists).
  4. Adds the SPN as a member of that group (if not already a member).
  5. Reads the current "Service principals can access read-only admin APIs"
     tenant setting, merges the new group into its existing allow-list
     (never replacing it - other apps already allow-listed stay allow-listed),
     and updates it.
  6. Optionally does the same for "Enhance admin APIs responses with
     detailed metadata" (--enable-detailed-metadata), which
     list_pbi_tables_and_columns.py needs.

This calls two different Microsoft Entra/Fabric APIs that this project
hasn't exercised before (Microsoft Graph for the group, and the Fabric v1
admin/tenantsettings API - a preview API at the time of writing). Review the
printed plan carefully, and consider --dry-run first.

Setup:
  pip install -r requirements-bootstrap.txt

Usage:
  python bootstrap_spn_admin_access.py --tenant-id <tenant-id> \
      --target-spn-app-id <reporting-spn-client-id> --dry-run

  python bootstrap_spn_admin_access.py --tenant-id <tenant-id> \
      --target-spn-app-id <reporting-spn-client-id> --enable-detailed-metadata
"""
import argparse
import logging
import re
import sys

import msal
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
FABRIC_BASE = "https://api.fabric.microsoft.com/v1"

# Microsoft's first-party "Azure CLI" app. It's a multi-tenant public client
# that already has "Allow public client flows" enabled and broad Graph
# delegated-permission consent pre-granted in most tenants, so device-code
# sign-in works out of the box without registering a new app just for this
# one-time task. Override with --auth-client-id if your tenant blocks it
# (some Conditional Access policies do) - in that case register your own
# app with "Allow public client flows" = Yes under Authentication.
DEFAULT_AUTH_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

# Requested explicitly (not as "<resource>/.default") so that if your admin
# account hasn't already consented to these, the device-code sign-in prompts
# for consent right then instead of silently returning a token that's missing
# a scope and failing later with an opaque 403 on the actual API call.
# Group.ReadWrite.All: create the group.
# GroupMember.ReadWrite.All + Application.ReadWrite.All: both are required to
# add a service principal (not just a user) as a group member - see
# https://learn.microsoft.com/en-us/graph/api/group-post-members permissions table.
GRAPH_SCOPES = [
    "https://graph.microsoft.com/Group.ReadWrite.All",
    "https://graph.microsoft.com/GroupMember.ReadWrite.All",
    "https://graph.microsoft.com/Application.ReadWrite.All",
]
# Tenant.ReadWrite.All: read + update tenant settings.
FABRIC_SCOPES = ["https://api.fabric.microsoft.com/Tenant.ReadWrite.All"]

READ_ONLY_ADMIN_APIS_TITLE = "Service principals can access read-only admin APIs"
DETAILED_METADATA_TITLE = "Enhance admin APIs responses with detailed metadata"

REQUEST_TIMEOUT = 60


def get_device_code_token(tenant_id: str, auth_client_id: str, scopes: list) -> str:
    app = msal.PublicClientApplication(
        client_id=auth_client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to start device code flow: {flow}")

    print(f"\n{flow['message']}\n")
    result = app.acquire_token_by_device_flow(flow)  # blocks until sign-in completes
    if "access_token" not in result:
        raise RuntimeError(
            f"Sign-in failed: {result.get('error')}: {result.get('error_description')}"
        )
    return result["access_token"]


def _request(method: str, url: str, token: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {token}"
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    response = requests.request(method, url, headers=headers, **kwargs)
    if response.status_code >= 400:
        logger.error("%s %s failed: %s - %s", method, url, response.status_code, response.text)
        response.raise_for_status()
    return response


def find_service_principal(token: str, app_id: str) -> dict:
    response = _request(
        "GET", f"{GRAPH_BASE}/servicePrincipals",
        token, params={"$filter": f"appId eq '{app_id}'"},
    )
    values = response.json().get("value", [])
    if not values:
        raise RuntimeError(
            f"No service principal found for app ID {app_id}. "
            "Double-check --target-spn-app-id matches the reporting SPN's Application (client) ID."
        )
    return values[0]


def find_group_by_display_name(token: str, display_name: str):
    response = _request(
        "GET", f"{GRAPH_BASE}/groups",
        token, params={"$filter": f"displayName eq '{display_name}'"},
    )
    values = response.json().get("value", [])
    return values[0] if values else None


def create_group(token: str, display_name: str) -> dict:
    mail_nickname = re.sub(r"[^A-Za-z0-9]", "", display_name)[:64] or "pbiadminspns"
    body = {
        "displayName": display_name,
        "description": "SPNs allow-listed for Power BI/Fabric read-only admin API access.",
        "mailEnabled": False,
        "mailNickname": mail_nickname,
        "securityEnabled": True,
    }
    response = _request("POST", f"{GRAPH_BASE}/groups", token, json=body)
    return response.json()


def group_has_member(token: str, group_id: str, member_object_id: str) -> bool:
    response = _request("GET", f"{GRAPH_BASE}/groups/{group_id}/members", token, params={"$select": "id"})
    return any(m["id"] == member_object_id for m in response.json().get("value", []))


def add_group_member(token: str, group_id: str, member_object_id: str):
    body = {"@odata.id": f"{GRAPH_BASE}/directoryObjects/{member_object_id}"}
    _request("POST", f"{GRAPH_BASE}/groups/{group_id}/members/$ref", token, json=body)


def list_tenant_settings(token: str) -> list:
    settings = []
    url = f"{FABRIC_BASE}/admin/tenantsettings"
    params = {}
    while True:
        response = _request("GET", url, token, params=params)
        body = response.json()
        settings.extend(body.get("value", []))
        continuation = body.get("continuationToken")
        if not continuation:
            return settings
        params = {"continuationToken": continuation}


def find_setting_by_title(settings: list, title: str) -> dict:
    for setting in settings:
        if setting.get("title") == title:
            return setting
    available = ", ".join(sorted(s.get("title", "?") for s in settings))
    raise RuntimeError(
        f"Tenant setting titled '{title}' not found. Available titles: {available}"
    )


def enable_setting_for_group(token: str, setting: dict, group_id: str, group_name: str, dry_run: bool):
    setting_name = setting["settingName"]
    existing_groups = list(setting.get("enabledSecurityGroups") or [])

    if any(g["graphId"] == group_id for g in existing_groups):
        logger.info("'%s' is already enabled for group '%s' - nothing to do", setting["title"], group_name)
        return

    merged_groups = existing_groups + [{"graphId": group_id, "name": group_name}]
    body = {
        "enabled": True,
        "enabledSecurityGroups": merged_groups,
    }
    # Carry over existing delegation flags/properties so this update doesn't reset them.
    for key in ("delegateToCapacity", "delegateToDomain", "delegateToWorkspace", "properties"):
        if key in setting:
            body[key] = setting[key]

    logger.info(
        "%s: enabling for group '%s' (keeping %d existing group(s) allow-listed)",
        setting["title"], group_name, len(existing_groups),
    )
    if dry_run:
        logger.info("[dry-run] Would POST %s/admin/tenantsettings/%s/update with %s", FABRIC_BASE, setting_name, body)
        return

    _request("POST", f"{FABRIC_BASE}/admin/tenantsettings/{setting_name}/update", token, json=body)
    logger.info("'%s' updated successfully", setting["title"])


def main():
    parser = argparse.ArgumentParser(
        description="One-time bootstrap: create the SPN allow-list security group and enable admin API access."
    )
    parser.add_argument("--tenant-id", required=True, help="Azure AD tenant ID.")
    parser.add_argument("--target-spn-app-id", required=True,
                         help="Application (client) ID of the reporting SPN (AZURE_CLIENT_ID in .env) to grant access to.")
    parser.add_argument("--group-name", default="PBI-ReadOnly-Admin-API-SPNs",
                         help="Display name of the security group to create/reuse.")
    parser.add_argument("--auth-client-id", default=DEFAULT_AUTH_CLIENT_ID,
                         help="Public client app ID used for your interactive device-code sign-in.")
    parser.add_argument("--enable-detailed-metadata", action="store_true",
                         help="Also enable 'Enhance admin APIs responses with detailed metadata' for this group "
                              "(needed for list_pbi_tables_and_columns.py).")
    parser.add_argument("--dry-run", action="store_true",
                         help="Do all lookups and print the plan, but make no changes.")
    args = parser.parse_args()

    logger.info("Signing in - complete the device code prompt in your browser as a Fabric/Groups admin")
    graph_token = get_device_code_token(args.tenant_id, args.auth_client_id, GRAPH_SCOPES)
    fabric_token = get_device_code_token(args.tenant_id, args.auth_client_id, FABRIC_SCOPES)

    logger.info("Looking up service principal for app ID %s", args.target_spn_app_id)
    service_principal = find_service_principal(graph_token, args.target_spn_app_id)
    sp_object_id = service_principal["id"]
    logger.info("Found service principal '%s' (object id %s)", service_principal.get("displayName"), sp_object_id)

    group = find_group_by_display_name(graph_token, args.group_name)
    if group:
        logger.info("Reusing existing group '%s' (id %s)", args.group_name, group["id"])
    else:
        logger.info("Creating security group '%s'", args.group_name)
        if args.dry_run:
            logger.info("[dry-run] Would create group '%s'", args.group_name)
            group = {"id": "<dry-run-group-id>", "displayName": args.group_name}
        else:
            group = create_group(graph_token, args.group_name)
            logger.info("Created group '%s' (id %s)", args.group_name, group["id"])

    if not args.dry_run:
        if group_has_member(graph_token, group["id"], sp_object_id):
            logger.info("SPN is already a member of '%s'", args.group_name)
        else:
            add_group_member(graph_token, group["id"], sp_object_id)
            logger.info("Added SPN to group '%s'", args.group_name)
    else:
        logger.info("[dry-run] Would add SPN %s to group '%s' if not already a member", sp_object_id, args.group_name)

    logger.info("Reading current tenant settings")
    tenant_settings = list_tenant_settings(fabric_token)

    read_only_setting = find_setting_by_title(tenant_settings, READ_ONLY_ADMIN_APIS_TITLE)
    enable_setting_for_group(fabric_token, read_only_setting, group["id"], args.group_name, args.dry_run)

    if args.enable_detailed_metadata:
        metadata_setting = find_setting_by_title(tenant_settings, DETAILED_METADATA_TITLE)
        enable_setting_for_group(fabric_token, metadata_setting, group["id"], args.group_name, args.dry_run)

    if args.dry_run:
        logger.info("Dry run complete - no changes were made. Re-run without --dry-run to apply them.")
    else:
        logger.info(
            "Done. It can take a few minutes to propagate. Then the reporting scripts should be able to "
            "authenticate as app ID %s.", args.target_spn_app_id,
        )


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.HTTPError as exc:
        logger.error("API call failed: %s", exc)
        sys.exit(1)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)
