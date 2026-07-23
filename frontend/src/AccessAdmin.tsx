import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL;
const ROLES = ["admin", "gerente", "supervisor"];

const REGIONAIS: Record<string, string[]> = {
  NE1: ["04","12"], NE2: ["03","09","21"], NE3: ["52","53"],
  NO1: ["06","08","11"], NO2: ["01","07"],
  RJ1: ["10","13"], RJ2: ["05","14"],
  SP1: ["02","16"], SP2: ["15","18"],
};

const FILIAL_NOME: Record<string, string> = {
  "01":"Matriz","02":"São Paulo","03":"Fortaleza","04":"São Luís","05":"Duque de Caxias",
  "06":"Manaus","07":"Macapá","08":"Boa Vista","09":"Juazeiro","10":"São Gonçalo",
  "11":"Santarém","12":"Imperatriz","13":"Taquara","14":"Piraí","15":"Guarulhos",
  "16":"Itapevi","18":"São Bernardo","21":"Teresina","22":"Marabá","52":"Petrolina","53":"Caruaru",
};
const TODAS = Object.keys(FILIAL_NOME).sort();

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

function asList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (typeof v === "string") { try { const p = JSON.parse(v); return Array.isArray(p) ? p.map(String) : []; } catch { return []; } }
  return [];
}

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
    if (!r.ok) {
      const j = await r.json().catch(() => ({} as any));
      let d = j?.detail ?? `HTTP ${r.status}`;
      if (Array.isArray(d)) d = d.map((x: any) => `${(x.loc || []).slice(-1)[0]}: ${x.msg}`).join("; ");
      else if (typeof d === "object") d = JSON.stringify(d);
      throw new Error(String(d));
    }
    return r.status === 204 ? null : r.json();
  }
  const load = () => api("").then(setUsers).catch((e) => setMsg(String(e)));
  useEffect(() => { load(); }, []);

  function editar(u: ACLUser) {
    setMsg(null);
    setForm({ id: u.id, email: u.email, nome: u.nome || "", role: u.role, scope_kind: u.scope_kind, scope_value: asList(u.scope_value), super_admin: u.super_admin });
  }

  async function salvar() {
    setMsg(null);
    const body = { email: form.email, nome: form.nome, role: form.role, scope_kind: form.scope_kind, scope_value: asList(form.scope_value), super_admin: form.super_admin };
    if (form.scope_kind !== "brasil" && form.scope_value.length === 0) { setMsg("✗ Selecione ao menos uma filial/regional"); return; }
    try {
      if (editando) { await api(`/${form.id}`, { method: "PATCH", body: JSON.stringify(body) }); setMsg("✓ Alterado (efetivo em ≤30s)"); }
      else { await api("", { method: "POST", body: JSON.stringify(body) }); setMsg("✓ Liberado (efetivo em ≤30s)"); }
      setForm(EMPTY); load();
    } catch (e) { setMsg("✗ " + String(e)); }
  }
  async function toggle(u: ACLUser) {
    try { await api(`/${u.id}/active?active=${!u.active}`, { method: "PATCH" }); load(); }
    catch (e) { setMsg("✗ " + String(e)); }
  }

  // helpers de seleção
  const sel = new Set(form.scope_value);
  const setSel = (s: Set<string>) => setForm({ ...form, scope_value: [...s].sort() });
  const toggleFilial = (f: string) => { const s = new Set(sel); s.has(f) ? s.delete(f) : s.add(f); setSel(s); };
  const toggleRegional = (r: string) => setForm({ ...form, scope_value: sel.has(r) ? form.scope_value.filter((x) => x !== r) : [...form.scope_value, r] });
  const marcarRegional = (r: string) => { const s = new Set(sel); REGIONAIS[r].forEach((f) => s.add(f)); setSel(s); };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", zIndex: 1000, display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 30, overflow: "auto" }}>
      <div style={{ background: "#fff", borderRadius: 12, padding: 24, width: "min(980px,95vw)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ color: "#1c2c5e", margin: 0 }}>Acessos</h2>
          <button onClick={onClose} style={{ border: 0, background: "transparent", fontSize: 22, cursor: "pointer" }}>×</button>
        </div>

        <div style={{ background: editando ? "#eef3fb" : "#f5f5f0", padding: 16, borderRadius: 10, margin: "16px 0", border: editando ? "1px solid #2563eb" : "none" }}>
          <div style={{ fontWeight: 600, marginBottom: 10 }}>{editando ? `Editando: ${form.email}` : "Liberar acesso"}</div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 10 }}>
            <input placeholder="email@ebdgrupo.com.br" value={form.email} disabled={editando}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              style={{ padding: 8, width: 240, background: editando ? "#eee" : "#fff" }} />
            <input placeholder="Nome" value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} style={{ padding: 8, width: 170 }} />
            <label style={{ fontSize: 13 }}>Papel:{" "}
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} style={{ padding: 6 }}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 13 }}>Escopo:{" "}
              <select value={form.scope_kind} onChange={(e) => setForm({ ...form, scope_kind: e.target.value, scope_value: [] })} style={{ padding: 6 }}>
                <option value="brasil">Brasil (tudo)</option>
                <option value="regional">Por regional</option>
                <option value="filiais">Filiais específicas</option>
              </select>
            </label>
            <label style={{ fontSize: 13 }}>
              <input type="checkbox" checked={form.super_admin} onChange={(e) => setForm({ ...form, super_admin: e.target.checked })} /> super-admin
            </label>
          </div>

          {form.scope_kind === "regional" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "4px 0 10px" }}>
              {Object.keys(REGIONAIS).map((r) => {
                const on = sel.has(r);
                return (
                  <button key={r} onClick={() => toggleRegional(r)}
                    style={{ padding: "6px 12px", borderRadius: 20, cursor: "pointer", fontSize: 13, border: on ? "0" : "1px solid #ccc", background: on ? "#1c2c5e" : "#fff", color: on ? "#fff" : "#333" }}>
                    {r} <span style={{ opacity: .7, fontSize: 11 }}>({REGIONAIS[r].join(",")})</span>
                  </button>
                );
              })}
            </div>
          )}

          {form.scope_kind === "filiais" && (
            <div style={{ margin: "4px 0 10px" }}>
              <div style={{ display: "flex", gap: 12, marginBottom: 8, fontSize: 12 }}>
                <button onClick={() => setSel(new Set(TODAS))} style={{ cursor: "pointer" }}>marcar todas</button>
                <button onClick={() => setSel(new Set())} style={{ cursor: "pointer" }}>limpar</button>
                <span style={{ color: "#888" }}>ou por regional:</span>
                {Object.keys(REGIONAIS).map((r) => (
                  <button key={r} onClick={() => marcarRegional(r)} style={{ cursor: "pointer", color: "#2563eb", border: 0, background: "transparent", padding: 0 }}>{r}</button>
                ))}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 4, maxHeight: 240, overflow: "auto", padding: 8, background: "#fff", borderRadius: 8, border: "1px solid #e5e5e0" }}>
                {TODAS.map((f) => (
                  <label key={f} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, padding: "3px 4px", cursor: "pointer" }}>
                    <input type="checkbox" checked={sel.has(f)} onChange={() => toggleFilial(f)} />
                    <b style={{ minWidth: 22 }}>{f}</b> {FILIAL_NOME[f]}
                  </label>
                ))}
              </div>
              <div style={{ fontSize: 12, color: "#666", marginTop: 6 }}>{sel.size} filial(is) selecionada(s)</div>
            </div>
          )}

          <div style={{ marginTop: 6 }}>
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
