import { Fragment, useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

type Agendamento = {
  id: number; titulo: string; pergunta: string; criado_por: string; dono_nome: string | null;
  quando: string; regra_desc: string; entrega_desc: string; formato_saida: string;
  ativo: boolean; proxima: string | null; ultima: string | null;
  ultimo_status: string | null; ultimo_erro: string | null;
};
type Execucao = { janela: string; status: string; duracao_seg: number | null; erro: string | null };

const STATUS: Record<string, { icone: string; texto: string; cor: string }> = {
  OK: { icone: "✅", texto: "entregue", cor: "#15803d" },
  PULADO_NAO_DIA_UTIL: { icone: "⏭", texto: "pulado (não era dia útil)", cor: "#666" },
  PULADO_ATRASADO: { icone: "⏰", texto: "pulado (atrasado)", cor: "#b45309" },
  EM_EXECUCAO: { icone: "⏳", texto: "rodando", cor: "#2563eb" },
  ERRO: { icone: "⚠️", texto: "erro", cor: "#b91c1c" },
  TIMEOUT: { icone: "⚠️", texto: "tempo esgotado", cor: "#b91c1c" },
  FALHA_ENTREGA: { icone: "⚠️", texto: "falha na entrega", cor: "#b91c1c" },
};

function Status({ s, erro }: { s: string | null; erro?: string | null }) {
  if (!s) return <span style={{ color: "#999" }}>ainda não rodou</span>;
  const x = STATUS[s] || { icone: "•", texto: s, cor: "#333" };
  return <span style={{ color: x.cor }} title={erro || ""}>{x.icone} {x.texto}</span>;
}

function Chave({ ligado, onTroca }: { ligado: boolean; onTroca: () => void }) {
  return (
    <button role="switch" aria-checked={ligado} onClick={onTroca}
      title={ligado ? "Ativa — clique para pausar" : "Pausada — clique para reativar"}
      style={{ width: 38, height: 22, borderRadius: 11, border: 0, padding: 0, cursor: "pointer", position: "relative",
               background: ligado ? "#15803d" : "#c9c9c4", transition: "background .15s", flex: "0 0 auto" }}>
      <span style={{ position: "absolute", top: 3, left: ligado ? 19 : 3, width: 16, height: 16, borderRadius: "50%",
                     background: "#fff", transition: "left .15s", boxShadow: "0 1px 2px rgba(0,0,0,.25)" }} />
    </button>
  );
}

export function AgendaAdmin({ getToken, onClose, onMudou }: {
  getToken: () => Promise<string>; onClose: () => void; onMudou?: () => void;
}) {
  const [itens, setItens] = useState<Agendamento[]>([]);
  const [aberto, setAberto] = useState<number | null>(null);
  const [hist, setHist] = useState<Execucao[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  async function api(path: string, init?: RequestInit) {
    const tok = await getToken();
    const r = await fetch(`${API_BASE}/api/admin/agendamentos${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    const j = await r.json().catch(() => ({} as any));
    if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
    return j;
  }

  async function carregar() {
    setCarregando(true);
    try {
      const j = await api("");
      setItens(j.agendamentos || []);
    } catch (e: any) {
      setMsg(`Erro ao carregar: ${e.message}`);
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => { carregar(); }, []);

  async function carregarHist(id: number) {
    const j = await api(`/${id}/historico`);
    setHist(j.historico || []);
  }

  async function verHistorico(id: number) {
    if (aberto === id) { setAberto(null); return; }
    try {
      await carregarHist(id);
      setAberto(id);
    } catch (e: any) {
      setMsg(`Erro: ${e.message}`);
    }
  }

  async function acao(a: Agendamento, oque: "pausar" | "reativar" | "rodar_agora" | "excluir") {
    if (oque === "excluir" && !window.confirm(`Excluir o agendamento "${a.titulo}"? O histórico fica guardado.`)) return;
    try {
      if (oque === "excluir") await api(`/${a.id}`, { method: "DELETE" });
      else await api(`/${a.id}/${oque}`, { method: "POST" });
      setMsg({
        pausar: `"${a.titulo}" pausado.`,
        reativar: `"${a.titulo}" reativado — volta no próximo horário.`,
        rodar_agora: `"${a.titulo}" vai rodar em até 30 segundos.`,
        excluir: `"${a.titulo}" excluído.`,
      }[oque]);
      await carregar();
      onMudou?.();
      if (aberto === a.id) {
        if (oque === "excluir") setAberto(null); else await carregarHist(a.id);
      }
    } catch (e: any) {
      setMsg(`Erro: ${e.message}`);
    }
  }

  const btn = { cursor: "pointer", marginRight: 6, padding: "3px 8px", fontSize: 12 } as const;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", zIndex: 1000, display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 30, overflow: "auto" }}>
      <div style={{ background: "#fff", borderRadius: 12, padding: 24, width: "min(1100px,95vw)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ color: "#1c2c5e", margin: 0 }}>🕒 Agendados</h2>
          <div>
            <button onClick={carregar} style={{ ...btn, marginRight: 12 }}>atualizar</button>
            <button onClick={onClose} style={{ border: 0, background: "transparent", fontSize: 22, cursor: "pointer" }}>×</button>
          </div>
        </div>
        <p style={{ fontSize: 13, color: "#666", margin: "8px 0 16px" }}>
          Para criar, peça ao EBD.ia na conversa — por exemplo: <i>"todo dia útil às 8h me manda o faturamento de ontem"</i>.
          Cada tarefa roda com o acesso de quem a criou.
        </p>
        {msg && <div style={{ background: "#f5f5f0", padding: "8px 12px", borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{msg}</div>}

        {carregando ? <div style={{ color: "#888" }}>carregando…</div> : itens.length === 0 ? (
          <div style={{ color: "#888", padding: 20, textAlign: "center" }}>Nenhuma tarefa agendada.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr style={{ textAlign: "left", borderBottom: "2px solid #e5e5e0" }}>
              <th></th><th>#</th><th>Tarefa</th><th>Quando</th><th>Entrega</th><th>Próxima</th><th>Último resultado</th><th>Dono</th><th></th>
            </tr></thead>
            <tbody>
              {itens.map((a) => (
                <Fragment key={a.id}>
                  <tr style={{ borderBottom: "1px solid #eee", verticalAlign: "top" }}>
                    <td style={{ padding: "8px 4px" }}><Chave ligado={a.ativo} onTroca={() => acao(a, a.ativo ? "pausar" : "reativar")} /></td>
                    <td style={{ padding: "8px 4px", opacity: a.ativo ? 1 : 0.5 }}>{a.id}</td>
                    <td style={{ padding: "8px 4px", maxWidth: 260 }}>
                      <b>{a.titulo}</b>{!a.ativo && <span style={{ color: "#b45309", marginLeft: 6 }}>(pausada)</span>}
                      <div style={{ color: "#666", fontSize: 12 }}>{a.pergunta}</div>
                    </td>
                    <td style={{ padding: "8px 4px" }}>{a.quando}<div style={{ color: "#666", fontSize: 12 }}>{a.regra_desc}</div></td>
                    <td style={{ padding: "8px 4px" }}>{a.entrega_desc}<div style={{ color: "#666", fontSize: 12 }}>{a.formato_saida}</div></td>
                    <td style={{ padding: "8px 4px", whiteSpace: "nowrap" }}>{a.ativo ? (a.proxima || "—") : "—"}</td>
                    <td style={{ padding: "8px 4px" }}>
                      <Status s={a.ultimo_status} erro={a.ultimo_erro} />
                      {a.ultima && <div style={{ color: "#666", fontSize: 12 }}>{a.ultima}</div>}
                    </td>
                    <td style={{ padding: "8px 4px" }}>{a.dono_nome || a.criado_por}</td>
                    <td style={{ padding: "8px 4px", whiteSpace: "nowrap" }}>
                      {a.ativo && <button style={btn} onClick={() => acao(a, "rodar_agora")}>rodar agora</button>}
                      <button style={btn} onClick={() => verHistorico(a.id)}>{aberto === a.id ? "fechar" : "histórico"}</button>
                      <button style={{ ...btn, color: "#b91c1c" }} onClick={() => acao(a, "excluir")}>excluir</button>
                    </td>
                  </tr>
                  {aberto === a.id && (
                    <tr><td colSpan={9} style={{ background: "#fafaf7", padding: "8px 16px" }}>
                      {hist.length === 0 ? <span style={{ color: "#888" }}>Ainda não rodou nenhuma vez.</span> : (
                        <table style={{ width: "100%", fontSize: 12 }}>
                          <thead><tr style={{ textAlign: "left", color: "#666" }}><th>Janela</th><th>Resultado</th><th>Duração</th><th>Detalhe</th></tr></thead>
                          <tbody>
                            {hist.map((h, i) => (
                              <tr key={i}>
                                <td>{h.janela}</td><td><Status s={h.status} /></td>
                                <td>{h.duracao_seg != null ? `${Math.round(h.duracao_seg)}s` : "—"}</td>
                                <td style={{ color: "#666" }}>{h.erro || ""}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
