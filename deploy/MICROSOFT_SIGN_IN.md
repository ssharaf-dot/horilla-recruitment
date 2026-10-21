# Proposed Microsoft 365 staff sign-in

Status: integration plan only. Microsoft sign-in has not been activated. Local staff and applicant authentication remain available.

Company IT can register a single-tenant web application in Microsoft Entra ID and grant access to selected staff. Use separate registrations for the demo and the eventual internal production installation. Record the tenant ID and application/client ID; provision a server-side certificate or secret through the deployment's protected configuration, never Git or chat.

Implementation should use a maintained OpenID Connect client with authorization-code flow, state, nonce and PKCE support, tenant-specific discovery, HTTPS callbacks, and validation of issuer, tenant, audience, signature and token lifetime. Establish the final callback route before registering its exact URL. The callback is not implemented yet.

Link identities using the validated tenant ID and object ID. Do not silently attach existing privileged accounts by email. Define and assign HR, HiringManager and Leadership application roles and map them to the existing recruitment permissions. Keep manager job assignments and applicant record ownership checks on the server. No Microsoft identity should automatically become a Django superuser.

Sign-in needs identity scopes such as openid, profile and email, not access to company mail, files or calendars. Applicants continue to use the separate public careers account; external applicant Microsoft identity can be considered independently. Retain the local administrator as a fallback. Stage the integration and verify all roles, denied/unassigned users, logout and fallback login before enabling it in the demo.

For internal migration, deploy the same source and images, restore any required data, supply new protected configuration, register the internal HTTPS callback, and update permitted origins. Tenant identity mappings can be retained if the same tenant is used.

Microsoft documentation:
- https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc
- https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps

Next inputs from company IT: tenant/sign-in domain, application registration owner, approved redirect URL, tenant/client IDs and test-user role assignments. Exchange credentials using the organization's secret-management process.
