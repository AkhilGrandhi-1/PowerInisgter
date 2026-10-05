"""
Shared helpers for Power BI Admin API scripts: SPN bearer-token auth with
automatic refresh, paginated admin GET calls, scanner-API (metadata scan)
helpers, and CSV output.

Used by list_pbi_capacities.py, list_pbi_workspaces.py,
list_pbi_datasets_and_reports.py, and list_pbi_tables_and_columns.py.
"""
import csv
import datetime as dt
import logging
import os
import time

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
ADMIN_API_BASE = "https://api.powerbi.com/v1.0/myorg/admin"
CAPACITIES_URL = f"{ADMIN_API_BASE}/capacities"

DEFAULT_REQUEST_TIMEOUT = 60  # seconds, applied to every HTTP call so a stalled response errors instead of hanging
TOKEN_EXPIRY_BUFFER_SECONDS = 300  # refresh this long before the token's real expiry


def load_env():
    load_dotenv()


def add_credential_args(parser):
    """Add --tenant-id/--client-id/--client-secret args, defaulting to env vars."""
    parser.add_argument("--tenant-id", default=os.environ.get("AZURE_TENANT_ID"))
    parser.add_argument("--client-id", default=os.environ.get("AZURE_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("AZURE_CLIENT_SECRET"))
    return parser


def require_credentials(args, parser):
    if not all([args.tenant_id, args.client_id, args.client_secret]):
        parser.error(
            "Missing SPN credentials. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET "
            "(env vars or .env) or pass --tenant-id/--client-id/--client-secret."
        )


class AccessTokenManager:
    """
    Fetches and caches an SPN access token for the Power BI API, transparently
    refreshing it before it expires (or on a live 401) so long-running scans
    over large tenants never fail partway through because of a stale token.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._expires_at = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def get_token(self) -> str:
        if self._token is None or dt.datetime.now(dt.timezone.utc) >= self._expires_at:
            self._refresh()
        return self._token

    def force_refresh(self):
        """Discard the cached token, forcing the next get_token() to fetch a new one."""
        self._token = None
        self._expires_at = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def _refresh(self):
        token_url = TOKEN_URL_TEMPLATE.format(tenant_id=self.tenant_id)
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://analysis.windows.net/powerbi/api/.default",
        }
        response = requests.post(token_url, data=payload, timeout=DEFAULT_REQUEST_TIMEOUT)
        if response.status_code != 200:
            logger.error("Failed to get access token: %s - %s", response.status_code, response.text)
            response.raise_for_status()

        body = response.json()
        expires_in = int(body.get("expires_in", 3600))
        self._token = body["access_token"]
        self._expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            seconds=max(expires_in - TOKEN_EXPIRY_BUFFER_SECONDS, 0)
        )
        logger.info("Fetched access token (valid ~%d minutes)", expires_in // 60)


def _admin_request(method: str, url: str, token_manager: AccessTokenManager, max_retries: int = 5, **kwargs):
    """
    Call the Power BI Admin API with automatic token refresh on 401 and
    exponential-ish backoff on 429. Returns the raw response for any other
    status so callers keep their existing error handling/logging.
    """
    base_headers = dict(kwargs.pop("headers", None) or {})
    kwargs.setdefault("timeout", DEFAULT_REQUEST_TIMEOUT)
    retries = 0

    while True:
        headers = dict(base_headers)
        headers["Authorization"] = f"Bearer {token_manager.get_token()}"
        response = requests.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401 and retries < max_retries:
            logger.warning("Access token rejected (401); refreshing and retrying")
            token_manager.force_refresh()
            retries += 1
            continue

        if response.status_code == 429 and retries < max_retries:
            retry_after = int(response.headers.get("Retry-After", 30))
            logger.warning("Rate limited by admin API, retrying in %ss", retry_after)
            time.sleep(retry_after)
            retries += 1
            continue

        return response


def paginated_admin_get(url: str, token_manager: AccessTokenManager, params: dict = None, top: int = 5000):
    """Yield items from a paginated Power BI Admin API GET endpoint."""
    params = dict(params or {})
    skip = 0

    while True:
        params["$top"] = top
        params["$skip"] = skip

        response = _admin_request("GET", url, token_manager, params=params)
        if response.status_code != 200:
            logger.error("Admin API call failed: %s - %s", response.status_code, response.text)
            response.raise_for_status()

        values = response.json().get("value", [])
        for value in values:
            yield value

        if len(values) < top:
            break
        skip += top


def get_capacities(token_manager: AccessTokenManager) -> list:
    """Call the Power BI Admin API and return the list of capacities."""
    response = _admin_request("GET", CAPACITIES_URL, token_manager)
    if response.status_code != 200:
        logger.error("Failed to fetch capacities: %s - %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json().get("value", [])


def get_all_workspace_ids(token_manager: AccessTokenManager, exclude_personal_workspaces: bool = True,
                           exclude_inactive_workspaces: bool = True) -> list:
    """Return all workspace IDs in the tenant via GetModifiedWorkspaces (no modifiedSince = all)."""
    params = {
        "excludePersonalWorkspaces": str(exclude_personal_workspaces).lower(),
        "excludeInActiveWorkspaces": str(exclude_inactive_workspaces).lower(),
    }
    response = _admin_request("GET", f"{ADMIN_API_BASE}/workspaces/modified", token_manager, params=params)
    if response.status_code != 200:
        logger.error("Failed to list modified workspaces: %s - %s", response.status_code, response.text)
        response.raise_for_status()
    return [w["id"] for w in response.json()]


def start_scan(token_manager: AccessTokenManager, workspace_ids: list, dataset_schema: bool = False,
                dataset_expressions: bool = False, lineage: bool = False,
                datasource_details: bool = False, get_artifact_users: bool = False) -> str:
    """POST getInfo for up to 100 workspace IDs and return the resulting scan ID."""
    params = {
        "datasetSchema": str(dataset_schema).lower(),
        "datasetExpressions": str(dataset_expressions).lower(),
        "lineage": str(lineage).lower(),
        "datasourceDetails": str(datasource_details).lower(),
        "getArtifactUsers": str(get_artifact_users).lower(),
    }
    response = _admin_request(
        "POST",
        f"{ADMIN_API_BASE}/workspaces/getInfo",
        token_manager,
        params=params,
        json={"workspaces": workspace_ids},
    )
    if response.status_code != 202:
        logger.error("Failed to start scan: %s - %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json()["id"]


def wait_for_scan(token_manager: AccessTokenManager, scan_id: str, poll_interval: int = 5, timeout: int = 300):
    """Poll GetScanStatus until the scan succeeds, fails, or the timeout elapses."""
    elapsed = 0
    while elapsed <= timeout:
        response = _admin_request("GET", f"{ADMIN_API_BASE}/workspaces/scanStatus/{scan_id}", token_manager)
        if response.status_code != 200:
            logger.error("Failed to get scan status: %s - %s", response.status_code, response.text)
            response.raise_for_status()

        status = response.json().get("status")
        if status == "Succeeded":
            return
        if status == "Failed":
            raise RuntimeError(f"Scan {scan_id} failed")

        time.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(f"Scan {scan_id} did not complete within {timeout}s")


def get_scan_result(token_manager: AccessTokenManager, scan_id: str) -> dict:
    """GET the scan result payload for a completed scan. Available for 24 hours after completion."""
    response = _admin_request("GET", f"{ADMIN_API_BASE}/workspaces/scanResult/{scan_id}", token_manager)
    if response.status_code != 200:
        logger.error("Failed to get scan result: %s - %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json()


def chunked(items, size):
    """Yield successive `size`-length chunks of `items`."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def write_csv(rows, fieldnames, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
