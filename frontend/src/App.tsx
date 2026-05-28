import { useState } from "react";
import {
  useMsal,
  AuthenticatedTemplate,
  UnauthenticatedTemplate,
} from "@azure/msal-react";
import { loginRequest, apiRequest } from "./auth/authConfig";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

function App() {
  const { instance, accounts } = useMsal();
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function login() {
    setError(null);
    try {
      await instance.loginRedirect(loginRequest);
    } catch (e: any) {
      setError(`Login falhou: ${e.message}`);
    }
  }

  async function logout() {
    await instance.logoutRedirect({
      postLogoutRedirectUri: window.location.origin,
    });
  }

  async function fetchMe() {
    setLoading(true);
    setError(null);
    setMe(null);
    try {
      // Pega token silenciosamente (já foi obtido no login)
      const result = await instance.acquireTokenSilent({
        ...apiRequest,
        account: accounts[0],
      });

      // Chama o gateway com o Bearer token
      const resp = await fetch(`${API_BASE}/api/me`, {
        headers: {
          Authorization: `Bearer ${result.accessToken}`,
        },
      });

      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${body}`);
      }

      const data = await resp.json();
      setMe(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="container">
      <header>
        <h1>EBD.ia</h1>
        <p className="subtitle">Frontend dev — autenticação Microsoft Entra ID</p>
      </header>

      <UnauthenticatedTemplate>
        <div className="card">
          <h2>Não autenticado</h2>
          <p>Faça login com sua conta corporativa @ebdbr.com.br</p>
          <button onClick={login}>Entrar com Microsoft</button>
        </div>
      </UnauthenticatedTemplate>

      <AuthenticatedTemplate>
        <div className="card success">
          <h2>✅ Autenticado</h2>
          <p>
            <strong>Conta:</strong> {accounts[0]?.username}<br />
            <strong>Nome:</strong> {accounts[0]?.name}<br />
            <strong>Tenant:</strong> {accounts[0]?.tenantId}
          </p>
          <button onClick={fetchMe} disabled={loading}>
            {loading ? "Chamando /api/me..." : "Testar /api/me no gateway"}
          </button>
          <button onClick={logout} className="secondary">
            Sair
          </button>
        </div>

        {me && (
          <div className="card">
            <h3>Resposta do gateway:</h3>
            <pre>{JSON.stringify(me, null, 2)}</pre>
          </div>
        )}
      </AuthenticatedTemplate>

      {error && (
        <div className="card error">
          <h3>⚠️ Erro</h3>
          <pre>{error}</pre>
        </div>
      )}

      <footer>
        <p>
          Gateway: <code>{API_BASE}</code> |
          Client: <code>{import.meta.env.VITE_AZURE_CLIENT_ID?.substring(0, 8)}...</code>
        </p>
      </footer>
    </div>
  );
}

export default App;
