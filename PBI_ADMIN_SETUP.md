# Power BI Admin API Setup — What the Tenant Admin Must Enable

## Overview

These scripts read tenant-wide Power BI/Fabric metadata (capacities,
workspaces, reports, datasets, tables, columns) through an Azure AD service
principal (SPN). Before any of them will run, a Fabric/Power BI admin has
to complete a one-time setup: register the app, create an allow-list
security group, and enable two tenant settings. None of this can be done
by whoever writes or runs the reporting scripts — it requires Fabric admin
rights in the tenant.

There are two ways to do this setup:
- **Manually**, following Steps 1-5 below, entirely through the Azure and
  Fabric admin portals.
- **Semi-automated**, using a separate helper script
  (`bootstrap_spn_admin_access.py`) for Steps 2-4. Step 1 is always manual.
  See "Optional: automate Steps 2-4" further down.

Pick whichever you're more comfortable with — the end result is identical.

## Steps

### Step 1: Create the Azure AD app (service principal)

1. In the **Azure portal** → **Microsoft Entra ID** → **App registrations**,
   create a new app registration (or reuse an existing one).
2. Create a **client secret** for it (Certificates & secrets). Record:
   - Tenant ID
   - Application (client) ID
   - Client secret value
3. **Do not add any Power BI API permissions to this app** (no
   `Tenant.Read.All`, `Capacity.Read.All`, etc. under API permissions).
   Service-principal access to the read-only admin APIs is granted entirely
   through the security-group allow-list in Step 3 — if the app has *any*
   admin-consent-required permission configured, its calls to the
   read-only admin APIs will be rejected.
   - To verify: **Microsoft Entra ID** → **Enterprise applications** →
     select the app → **Permissions** → confirm there are no permissions
     requiring admin consent.

### Step 2: Create a security group and add the app to it

1. **Microsoft Entra ID** → **Groups** → **New group**.
   - Group type: **Security** (not Microsoft 365).
2. Add the app (service principal) as a member of this group.

### Step 3: Allow the service principal to use read-only Admin APIs

1. Sign in to the **Fabric/Power BI Admin portal** (requires Fabric admin
   role) → **Tenant settings** → **Admin API settings**.
2. Find **"Service principals can access read-only admin APIs"**.
3. Set it to **Enabled**.
4. Choose **Specific security groups** and add the group created in Step 2.
5. Select **Apply**.

This alone is enough for:
- `list_pbi_capacities.py`
- `list_pbi_workspaces.py`
- `list_pbi_datasets_and_reports.py`

### Step 4: Enable detailed metadata for table/column scanning

`list_pbi_tables_and_columns.py` uses the scanner API
(`getInfo` → `scanStatus` → `scanResult`) with `datasetSchema=true`. This
requires one more tenant setting, in the same **Admin API settings**
section:

1. **"Enhance admin APIs responses with detailed metadata"** → **Enabled**,
   scoped to the same group as Step 3. Without this, scans return
   workspaces/datasets but the `tables` and `columns` arrays come back
   empty.

There's also **"Enhance admin APIs responses with DAX and mashup
expressions"** — only needed if a future script requests measure DAX or
Power Query (M) source code. It can only be turned on after the setting
above is, and isn't required for the current tables/columns script.

### Step 5: Give the credentials to whoever runs the scripts

Provide the Tenant ID, Client ID, and Client secret from Step 1 via
environment variables (or a local `.env` file, never committed to source
control):

```
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
```

## Optional: automate Steps 2-4 with bootstrap_spn_admin_access.py

Instead of clicking through the portals for Steps 2-4, an admin can run
`bootstrap_spn_admin_access.py` (in the repo root) once. It creates the
security group, adds the app to it, and enables both tenant settings via
API calls — same end result as the manual steps, just done for you.

It's kept as a separate script from the reporting pipeline on purpose: it
signs **you** in (not the reporting SPN) and acts under your own admin
permissions, so there's an audit trail of who made the change, and the
reporting SPN's credentials are never involved.

**How to run it:**

```
pip install -r requirements-bootstrap.txt

# Review the plan first - makes no changes:
python bootstrap_spn_admin_access.py --tenant-id <tenant-id> \
    --target-spn-app-id <reporting-spn-client-id> \
    --enable-detailed-metadata --dry-run

# Then actually apply it:
python bootstrap_spn_admin_access.py --tenant-id <tenant-id> \
    --target-spn-app-id <reporting-spn-client-id> \
    --enable-detailed-metadata
```

`<reporting-spn-client-id>` is the Application (client) ID from Step 1 —
the same value that goes into `AZURE_CLIENT_ID` in `.env`. Drop
`--enable-detailed-metadata` if you only need Steps 2-3 (i.e. you don't
plan to run `list_pbi_tables_and_columns.py`); it's safe to re-run the
command later to add it — the script is idempotent.

**What to expect when you run it:** it prints a URL and a one-time code and
pauses — open that URL in a browser and sign in as yourself (a Fabric
admin / Groups admin) to continue. It asks for sign-in every time it's run
rather than the reporting SPN's saved credentials; see "Detailed
information" below for the full reasoning if you're wondering why.

## Detailed information

### Why the bootstrap script signs in interactively instead of using the SPN

It would be more convenient if `bootstrap_spn_admin_access.py` could just
use the reporting SPN's existing client secret instead of prompting for
sign-in. It can't, for two separate reasons:

1. **Power BI/Fabric's own permission model doesn't allow an SPN to
   bootstrap itself.** Both SPN-admin-API tiers ("read-only" and "used for
   updates") are granted the same way — a tenant setting plus a
   security-group allow-list — not through ordinary Azure AD API
   permissions. An SPN can only call the "updates" tier (needed to change
   tenant settings) if it's *already* been allow-listed for it, and
   nothing can grant that allow-listing except a human doing it once,
   either interactively or through the admin portal. This is unavoidable
   the first time, no matter which app performs it.
2. **Even the part that's technically possible with application
   permissions (creating the group and adding the SPN as a member, via
   Microsoft Graph) can't reuse the reporting SPN's app registration.**
   Every reporting script depends on that app having **zero** API
   permissions configured — Microsoft's docs are explicit that an SPN
   calling the read-only admin APIs must have no admin-consent-required
   permission on it, or its calls get rejected. Adding Graph permissions
   to the same app to do the group/membership setup risks breaking the
   reporting pipeline itself. Doing this with application permissions
   would require a **second**, separate app registration dedicated to
   bootstrap tasks — and even then, the tenant-setting update would still
   need one manual admin action to allow-list that second app for the
   "updates" tier.

Since this setup is a one-time (or rarely repeated) task, signing in
interactively avoids permanently maintaining a second, highly-privileged
app registration — one of the permissions involved,
`Application.ReadWrite.All`, is powerful enough to modify other apps'
credentials — just to save a single sign-in prompt.

### Notes / gotchas

- Tenant setting changes can take a few minutes to propagate — if a script
  fails immediately after enabling a setting, wait and retry.
- These are **read-only** admin APIs — nothing here can modify workspaces,
  datasets, or permissions.
- Metadata scanning works even for content in workspaces that are **not**
  on a dedicated (Premium/Fabric) capacity — no special licensing required.
- Scan results expire **24 hours** after a scan completes, so
  `list_pbi_tables_and_columns.py` downloads results immediately after each
  scan finishes rather than caching scan IDs for later.
- Rate limits to be aware of (per hour, tenant-wide, shared across anyone
  using these APIs):
  - `GET /admin/workspaces/modified` — 30 requests/hour
  - `POST /admin/workspaces/getInfo` — 500 requests/hour, 16 concurrent scans
  - `GET /admin/workspaces/scanResult/{id}` — 500 requests/hour
- The reporting scripts handle token expiry and rate limiting on their
  own: the access token auto-refreshes before it expires (or on a live
  401), and a 429 from any of the above limits triggers an automatic
  wait-and-retry using the API's `Retry-After` value. Nothing extra to
  configure for this — it's built into `pbi_admin_common.py`.
- During the bootstrap script's sign-in, you'll be prompted to consent (if
  not already granted in your tenant) to Microsoft Graph
  `Group.ReadWrite.All`, `GroupMember.ReadWrite.All`,
  `Application.ReadWrite.All`, and Fabric `Tenant.ReadWrite.All`. The
  middle two Graph permissions are both required specifically because
  you're adding a *service principal* (not a user) as a group member. If
  your own account can't grant that consent, someone with Global or Cloud
  Application Administrator needs to approve it once.

### Reference

- [Metadata scanning overview](https://learn.microsoft.com/en-us/fabric/governance/metadata-scanning-overview)
- [Set up metadata scanning](https://learn.microsoft.com/en-us/fabric/admin/metadata-scanning-setup)
- [Enable service principal authentication for admin APIs](https://learn.microsoft.com/en-us/fabric/admin/enable-service-principal-admin-apis)

APIs used by `bootstrap_spn_admin_access.py`:
- [Microsoft Graph - Create group](https://learn.microsoft.com/en-us/graph/api/group-post-groups)
- [Microsoft Graph - Add member](https://learn.microsoft.com/en-us/graph/api/group-post-members)
- [Fabric Admin - List Tenant Settings](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings)
- [Fabric Admin - Update Tenant Setting](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/update-tenant-setting) (preview API)
