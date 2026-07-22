import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL;
const REGIONAIS = ["NE1","NE2","NE3","NO1","NO2","RJ1","RJ2","SP1","SP2"];
const FILIAIS = ["01","02","03","04","05","06","07","08","09","10","11","12","13","14","15","16","18","21","52","53"];
const ROLES = ["admin","gerente","supervisor"];

type ACLUser = {
  id: string; email: string; nome: string | null; role: string;
  scope_kind: string; scope_value: string[]; filiais: string[] | "*";
  super_admin: boolean; active: boolean;
};

type FormState = {
  id: string | null; email: string; nome: string; role: string;
  scope_kind: string; scope_value: string[]; super_admin: boolean;
};

const EMPTY: FormState = { id: null, email: "", nome: "", role: "admin", scope_kind: "brasil", scope_value: [], super_admin: false };

export function AccessAdmin({ getToken, onClose }: { getToken: () => Promise<string>; onClose: () => void }) {
  const [users, setUsers] = useState<ACLUser[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const editando = form.id !== null;

  async function api(path: string, init?: RequestInit) {
    const tok = await getToken();
    const r = await fetch(`${API_BASE}/api/admin/acl${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    return r.status === 204 ? null : r.json();
  }
  const load = () => api("").then(setUsers).catch((e) => setMsg(String(e)));
  useEffect(() => { load(); }, []);

  function editar(u: ACLUser) {
    setMsg(null);
    setForm({
      id: u.id, email: u.email, nome: u.nome || "", role: u.role,
      scope_kind: u.scope_kind, scope_value: u.scope_value || [], super_admin: u.super_admin,
    });
  }

  async function salvar() {
    setMsg(null);
    const body = { email: form.email, nome: form.nome, role: form.role, scope_kind: form.scope_kind, scope_value: form.scope_value, super_admin: form.super_admin };
    try {
      if (editando) {
        await api(`/${form.id}`, { method: "PATCH", body: JSON.stringify(body) });
        setMsg("✓ Alterado (efetivo em ≤30s)");
      } else {
        await api("", { method: "POST", body: JSON.stringify(body) });
        setMsg("✓ Liberado (efetivo em ≤30s)");
      }
      setForm(EMPTY); load();
    } catch (e) { setMsg("✗ " + String(e)); }
  }
  async function toggle(u: ACLUser) {
    try { await api(`/${u.id}/active?active=${!u.active}`, { method: "PATCH" }); load(); }
    catch (e) { setMsg("✗ " + String(e)); }
  }
  const opts = form.scope_kind === "regional" ? REGIONAIS : form.scope_kind === "brasil" ? [] : FILIAIS;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", zIndex: 1000, display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 30, overflow: "auto" }}>
      <div style={{ background: "#fff", borderRadius: 12, padding: 24, width: "min(960px,95vw)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ color: "#1c2c5e", margin: 0 }}>Acessos</h2>
          <button onClick={onClose} style={{ border: 0, background: "transparent", fontSize: 22, cursor: "pointer" }}>×</button>
        </div>

        <div style={{ background: editando ? "#eef3fb" : "#f5f5f0", padding: 16, borderRadius: 10, margin: "16px 0", border: editando ? "1px solid #2563eb" : "none" }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            {editando ? `Editando: ${form.email}` : "Liberar acesso"}
          </div>
          <input placeholder="email@ebdgrupo.com.br" value={form.email} disabled={editando}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            style={{ padding: 8, width: 240, marginRight: 8, marginBottom: 8, background: editando ? "#eee" : "#fff" }} />
          <input placeholder="Nome" value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} style={{ padding: 8, width: 170, marginRight: 8, marginBottom: 8 }} />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} style={{ padding: 8, marginRight: 8, marginBottom: 8 }}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={form.scope_kind} onChange={(e) => setForm({ ...form, scope_kind: e.target.value, scope_value: [] })} style={{ padding: 8, marginRight: 8, marginBottom: 8 }}>
            <option value="brasil">Brasil</option>
            <option value="regional">Regional</option>
            <option value="filiais">Filiais específicas</option>
            <option value="filial">Uma filial</option>
          </select>
          {opts.length > 0 && (
            <select multiple={form.scope_kind !== "filial"} value={form.scope_value}
              onChange={(e) => setForm({ ...form, scope_value: Array.from(e.target.selectedOptions, (o) => o.value) })}
              style={{ padding: 8, minWidth: 110, height: form.scope_kind === "filial" ? "auto" : 84, verticalAlign: "top", marginRight: 8 }}>
              {opts.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          )}
          <label style={{ marginRight: 8, fontSize: 13 }}>
            <input type="checkbox" checked={form.super_admin} onChange={(e) => setForm({ ...form, super_admin: e.target.checked })} /> super-admin
          </label>
          <div style={{ marginTop: 10 }}>
            <button onClick={salvar} disabled={!form.email} style={{ padding: "8px 16px", background: "#1c2c5e", color: "#fff", border: 0, borderRadius: 8, cursor: "pointer", marginRight: 8 }}>
              {editando ? "Salvar alterações" : "Liberar"}
            </button>
            {editando && <button onClick={() => { setForm(EMPTY); setMsg(null); }} style={{ padding: "8px 16px", background: "#eee", border: 0, borderRadius: 8, cursor: "pointer" }}>Cancelar</button>}
            {msg && <span style={{ marginLeft: 12, fontSize: 13 }}>{msg}</span>}
          </div>
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr style={{ textAlign: "left", borderBottom: "2px solid #e5e5e0" }}>
            <th>Nome</th><th>Email</th><th>Papel</th><th>Escopo</th><th>Super</th><th>Status</th><th></th>
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} style={{ borderBottom: "1px solid #eee", opacity: u.active ? 1 : 0.45 }}>
                <td>{u.nome || "—"}</td><td>{u.email}</td><td>{u.role}</td>
                <td>{u.scope_kind === "brasil" ? "Brasil" : `${u.scope_kind}: ${(u.scope_value || []).join(", ")}`}</td>
                <td>{u.super_admin ? "★" : ""}</td><td>{u.active ? "ativo" : "inativo"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button onClick={() => editar(u)} style={{ cursor: "pointer", marginRight: 6 }}>editar</button>
                  <button onClick={() => toggle(u)} style={{ cursor: "pointer" }}>{u.active ? "revogar" : "reativar"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
