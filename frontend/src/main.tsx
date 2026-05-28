import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { PublicClientApplication, EventType } from "@azure/msal-browser";
import type { AuthenticationResult } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { msalConfig } from "./auth/authConfig";
import App from "./App";
import "./index.css";

const msalInstance = new PublicClientApplication(msalConfig);

await msalInstance.initialize();

// Define conta ativa se já tiver alguma logada
const accounts = msalInstance.getAllAccounts();
if (accounts.length > 0) {
  msalInstance.setActiveAccount(accounts[0]);
}

// Atualiza conta ativa após login bem-sucedido
msalInstance.addEventCallback((event) => {
  if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
    const result = event.payload as AuthenticationResult;
    msalInstance.setActiveAccount(result.account);
  }
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MsalProvider instance={msalInstance}>
      <App />
    </MsalProvider>
  </StrictMode>
);
