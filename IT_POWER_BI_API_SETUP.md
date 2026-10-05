# Power BI Tenant Inventory - IT Setup Request

## What we are trying to do

We are building an automated, read-only inventory of the Power BI/Fabric tenant using an Azure service principal (SPN) and Power BI REST APIs.

The inventory will collect:

- Workspaces
- Capacities
- Reports
- Semantic models/datasets
- Tables and columns
- Additional tenant metadata available through the Power BI Admin and scanner APIs

The automation must not change reports, datasets, workspaces, or permissions. The SPN will be used only to read tenant metadata.

## What IT needs to configure

Please complete the steps below for the reporting application. The reporting application is identified by its **Application (client) ID**.

### Step 1 - Create or confirm the app registration

In Microsoft Entra ID:

1. Open **App registrations**.
2. Create a new application registration, or confirm the existing reporting application.
3. Create a client secret under **Certificates & secrets**.
4. Record the following values securely:
   - Directory (tenant) ID
   - Application (client) ID
   - Client secret value
5. Do not add broad Microsoft Graph or Power BI API permissions to the reporting application as a substitute for the Fabric Admin API configuration. For tenant-wide Admin APIs, access is granted through the Fabric tenant setting and security group in the next steps.
6. Set an expiry and rotation process for the client secret. A certificate is preferred for production use if our standard supports it.

The application must be configured as a confidential client for the client-credentials flow. The secret value must not be sent by email or committed to source control.

#### Can we avoid the security group?

Not for this tenant-wide inventory. Power BI tenant Admin APIs require both:

- The Fabric tenant setting **Service principals can access read-only admin APIs**.
- A security group selected in that setting, with this SPN as a member.

Entra application permissions alone do not grant an SPN access to these tenant-wide Admin APIs. Adding permissions such as Microsoft Graph permissions to the app also does not replace the Fabric tenant setting and may violate the Power BI Admin API service-principal requirements.

Application permissions can still be used for some separate, workspace-scoped Power BI APIs. Those APIs normally also require the SPN to be granted access to each workspace, directly or through a group. That model does not provide a practical replacement for the tenant-wide inventory requested here.

### Step 2 - Create a security group and add the SPN

In Microsoft Entra ID:

1. Create a **Security** group. Do not create a Microsoft 365 group.
2. Use a clear name, for example:
   `PBI-ReadOnly-Admin-API-SPNs`
3. Add the reporting application's **service principal** as a member of the group.

Important: add the service principal from **Enterprise applications** or the service principal object, not only the app registration object. The group must contain the service principal used by the tenant.

### Step 3 - Allow the SPN to use read-only Power BI Admin APIs

A Fabric administrator should open:

**Fabric/Power BI Admin portal > Tenant settings > Admin API settings**

Find:

**Service principals can access read-only admin APIs**

Configure it as follows:

1. Set it to **Enabled**.
2. Select **Specific security groups**.
3. Add `PBI-ReadOnly-Admin-API-SPNs`, or the security group created in Step 2.
4. Apply the setting.

This setting is required to list tenant-wide capacities, workspaces, datasets, and reports.

### Step 4 - Enable detailed metadata for tables and columns

In the same **Admin API settings** area, find:

**Enhance admin APIs responses with detailed metadata**

Configure it as follows:

1. Set it to **Enabled**.
2. Scope it to the same security group used in Step 3.
3. Apply the setting.

This setting is required for the scanner API to return semantic model tables and columns.

Do not enable DAX or Power Query/M expressions unless separately approved. They are not required for the initial inventory and may expose more sensitive metadata.

### Step 5 - Confirm propagation and provide the connection details

Please allow several minutes for group membership and tenant settings to propagate. Then provide the following through the approved secret-sharing process:

- Tenant ID
- Application (client) ID
- Client secret value, or the approved certificate details
- Security group name and object ID
- Confirmation that the SPN is a member of the group
- Confirmation that both tenant settings are enabled for that group
- Client secret/certificate expiry date

## Validation we will perform

After IT completes the setup, we will run the following checks in order:

1. List capacities.
2. List workspaces.
3. List datasets and reports.
4. Run the metadata scanner for tables and columns.
5. Produce CSV files and a combined Excel workbook.

Expected API access is read-only. We do not require workspace Admin, Member, Contributor, or Viewer access for the tenant-wide Admin API inventory. Workspace-level permissions may be requested later only for APIs that are not covered by the tenant Admin APIs.

## Troubleshooting information

- **Token acquisition fails:** verify the tenant ID, client ID, secret value, and secret expiry.
- **Token succeeds but the Admin API returns 401 or 403:** verify that the correct service principal object is in the security group, that the group is selected in the read-only Admin API setting, and that the change has propagated.
- **Workspaces/datasets appear but tables or columns are empty:** verify that detailed metadata is enabled for the same security group.
- **Only partial results are returned:** confirm that the tenant-wide Admin API is being used and check for API pagination or rate limiting.
- **HTTP 429:** the tenant-wide API rate limit has been reached. Wait and retry rather than running repeated scans.

## Security requirements

- Use a dedicated reporting SPN with least privilege.
- Store credentials in an approved secret store or protected environment configuration.
- Never commit `.env` files, client secrets, or certificates to the repository.
- Rotate secrets or certificates according to the organization's policy.
- Keep the reporting SPN read-only and separate from any bootstrap or administration application.

## IT completion checklist

- [ ] App registration exists
- [ ] Client secret or certificate has been created
- [ ] Reporting SPN identified by Application (client) ID
- [ ] Entra Security group created
- [ ] Reporting SPN added to the group
- [ ] Read-only Admin API tenant setting enabled for the group
- [ ] Detailed metadata tenant setting enabled for the group
- [ ] Credentials transferred through the approved secure channel
- [ ] Secret/certificate expiry date recorded
