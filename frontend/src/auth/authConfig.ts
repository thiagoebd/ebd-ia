import type { Configuration } from "@azure/msal-browser";

export const msalConfig: Configuration = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_AZURE_TENANT_ID}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "sessionStorage",
  },
};

// Scope APENAS do nosso app — NUNCA misturar com Graph (cilada audience)
export const loginRequest = {
  scopes: [import.meta.env.VITE_AZURE_SCOPE],
};

// Pra chamar nossa API depois (acquireTokenSilent)
export const apiRequest = {
  scopes: [import.meta.env.VITE_AZURE_SCOPE],
};
