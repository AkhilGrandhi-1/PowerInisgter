Please create a dedicated service principal for unattended Power BI/Fabric automation.

## SPN details

- SPN name: `PBI-Tenant-Inventory-Automation`
- Security group name: `PBI-ReadOnly-Admin-API-SPNs`
- Authentication: Client credentials using a certificate or client secret
- User sign-in for automation: Not required

## API permissions

### Power BI Service

- Add `Tenant.Read.All` under **Delegated permissions**.
- Grant admin consent for the organization.

`Tenant.Read.All` provides read-only tenant administration when an administrator signs in. It is a delegated permission and does not authorize unattended client-credentials calls by itself.

### Microsoft Graph

- No Microsoft Graph permissions are required for the current Power BI inventory.

## How to add Tenant.Read.All

1. Open the **Microsoft Entra admin center**.
2. Go to **App registrations** and select `PBI-Tenant-Inventory-Automation`.
3. Open **API permissions**.
4. Select **Add a permission**.
5. Select **Power BI Service**.
6. Select **Delegated permissions**.
7. Search for and select `Tenant.Read.All`.
8. Select **Add permissions**.
9. Select **Grant admin consent for the organization**.

## Required setup for unattended SPN automation

1. Add the SPN to the `PBI-ReadOnly-Admin-API-SPNs` security group.
2. In **Fabric Admin portal > Tenant settings > Admin API settings**, enable **Service principals can access read-only admin APIs** for that group.
3. Enable **Enhance admin APIs responses with detailed metadata** for the same group.
4. The automation will request the token scope `https://analysis.windows.net/powerbi/api/.default`.

The Fabric tenant settings and security-group membership authorize unattended SPN access. `Tenant.Read.All` applies only to the delegated flow where an administrator signs in.

## Information to provide

- Tenant ID
- Application (client) ID
- Security group name and object ID
- Client secret or certificate details through an approved secure channel
- Secret or certificate expiration date
- Confirmation that the SPN is a member of the security group
- Confirmation that both Fabric tenant settings are enabled for the group