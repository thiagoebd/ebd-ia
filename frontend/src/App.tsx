import { useState, useRef, useEffect } from "react";
import {
  useMsal,
  AuthenticatedTemplate,
  UnauthenticatedTemplate,
} from "@azure/msal-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { loginRequest, apiRequest } from "./auth/authConfig";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

type Msg = { role: "user" | "assistant"; text: string; status?: string; tools?: string[] };
type Thread = { id: string; title: string; msgs: Msg[]; loaded: boolean; model?: string };
type ModelInfo = { id: string; label: string; tier: string };
type MeInfo = { role: "admin" | "user"; models: { default: string; available: ModelInfo[] } };

function App() {
  const { instance, accounts } = useMsal();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<MeInfo | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>("claude-haiku-4-5");
  const [modelOpen, setModelOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const streamTidRef = useRef<string>("");

  const active = threads.find((t) => t.id === activeId) || null;
  const messages = active?.msgs || [];
  const firstName = accounts[0]?.name?.split(" ")[0] || "";
  const fullName = accounts[0]?.name || "";

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  async function token() {
    const tok = await instance.acquireTokenSilent({ ...apiRequest, account: accounts[0] });
    return tok.accessToken;
  }

  // carrega a lista de conversas do banco ao logar
  useEffect(() => {
    if (accounts.length === 0) return;
    (async () => {
      try {
        const t = await token();
        const resp = await fetch(`${API_BASE}/api/conversations`, {
          headers: { Authorization: `Bearer ${t}` },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        setThreads(data.map((c: any) => ({ id: c.id, title: c.title, msgs: [], loaded: false, model: c.model })));
        const meResp = await fetch(`${API_BASE}/api/me`, { headers: { Authorization: `Bearer ${t}` } });
        if (meResp.ok) {
          const meData = await meResp.json();
          setMe({ role: meData.role, models: meData.models });
          setSelectedModel(meData.models.default);
        }
      } catch { /* silencioso */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts.length]);

  async function openThread(id: string) {
    setActiveId(id);
    setInput("");
    const t = threads.find((x) => x.id === id);
    if (t && t.loaded) return;
    try {
      const tok = await token();
      const resp = await fetch(`${API_BASE}/api/conversations/${id}`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const msgs: Msg[] = (data.messages || []).map((m: any) => ({
        role: m.role, text: m.text, tools: m.tools || [],
      }));
      setThreads((ts) => ts.map((x) => (x.id === id ? { ...x, msgs, loaded: true, title: data.title, model: data.model } : x)));
      if (data.model) setSelectedModel(data.model);
    } catch (e: any) {
      setError(e.message);
    }
  }

  function newChat() {
    setActiveId(null);
    setInput("");
    if (me) setSelectedModel(me.models.default);
  }

  async function logout() {
    await instance.logoutRedirect({ postLogoutRedirectUri: window.location.origin });
  }
  function login() {
    instance.loginRedirect(loginRequest).catch((e) => setError(e.message));
  }

  async function send(presetQuestion?: string) {
    const question = (presetQuestion ?? input).trim();
    if (!question || busy) return;
    setError(null);
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    setBusy(true);

    const isNew = activeId === null;
    let tid = isNew ? `tmp-${Date.now()}` : activeId!;
    streamTidRef.current = tid;

    if (isNew) {
      const title = question.length > 42 ? question.slice(0, 42) + "…" : question;
      setThreads((ts) => [{ id: tid, title, msgs: [], loaded: true }, ...ts]);
      setActiveId(tid);
    }

    const pushMsgs = (updater: (m: Msg[]) => Msg[]) =>
      setThreads((ts) => ts.map((t) => (t.id === streamTidRef.current ? { ...t, msgs: updater(t.msgs) } : t)));

    pushMsgs((m) => [
      ...m,
      { role: "user", text: question },
      { role: "assistant", text: "", status: "Pensando", tools: [] },
    ]);

    try {
      const tok = await token();
      const controller = new AbortController();
      abortRef.current = controller;
      const resp = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${tok}` },
        body: JSON.stringify({ message: question, conversation_id: isNew ? null : activeId, model: selectedModel }),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        const t = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${t}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          let ev: any;
          try { ev = JSON.parse(json); } catch { continue; }

          if (ev.type === "conversation") {
            const realId = ev.id as string;
            if (realId !== streamTidRef.current) {
              const oldId = streamTidRef.current;
              setThreads((ts) => ts.map((t) => (t.id === oldId ? { ...t, id: realId, title: ev.title || t.title } : t)));
              setActiveId(realId);
              streamTidRef.current = realId;
            }
            continue;
          }

          pushMsgs((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (!last || last.role !== "assistant") return copy;
            if (ev.type === "status") last.status = ev.text;
            else if (ev.type === "tool") last.tools = [...(last.tools || []), ev.name];
            else if (ev.type === "token") { last.status = undefined; last.text += ev.text; }
            else if (ev.type === "done") { last.status = undefined; }
            else if (ev.type === "error") { last.status = undefined; last.text += `\n\n⚠️ Erro: ${ev.detail}`; }
            return copy;
          });
        }
      }
    } catch (e: any) {
      const aborted = e?.name === "AbortError";
      if (!aborted) setError(e.message);
      pushMsgs((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") {
          last.status = undefined;
          if (aborted) last.text += (last.text ? "\n\n" : "") + "_(interrompido)_";
        }
        return copy;
      });
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  function autosize() {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <>
      <UnauthenticatedTemplate>
        <div className="login-screen">
          <img src="/logo-ebd.png" alt="EBD" className="logo-login" />
          <p className="subtitle">Agente comercial · dados do Winthor em tempo real</p>
          <button className="btn-primary" onClick={login}>Entrar com Microsoft</button>
        </div>
      </UnauthenticatedTemplate>

      <AuthenticatedTemplate>
        <div className="app">
          <aside className="sidebar">
            <div className="sb-head">
              <img src="/logo-ebd.png" alt="EBD" />
              <span className="name">EBD<em>.ia</em></span>
            </div>

            <button className="new-chat" onClick={newChat}>
              <span>＋ Nova conversa</span>
              <span className="kbd"><kbd>⌃</kbd><kbd>K</kbd></span>
            </button>

            <div className="sb-section">Biblioteca</div>
            <div className="sb-list">
              <div className="sb-link"><span className="lbl">Planilhas</span><span className="count">—</span></div>
              <div className="sb-link"><span className="lbl">Documentos</span><span className="count">—</span></div>
              <div className="sb-link"><span className="lbl">Apresentações</span><span className="count">—</span></div>
              <div className="sb-link"><span className="lbl">Gráficos</span><span className="count">—</span></div>
            </div>

            <div className="sb-section">Conexões</div>
            <div className="sb-list">
              <div className="sb-link"><span className="dot-ok" /><span className="lbl">Winthor / Oracle</span></div>
            </div>

            <div className="sb-history">
              {threads.length > 0 && <div className="sb-group">Conversas</div>}
              {threads.map((t) => (
                <div
                  key={t.id}
                  className={`thread ${t.id === activeId ? "active" : ""}`}
                  onClick={() => openThread(t.id)}
                >
                  <span className="lbl">{t.title}</span>
                </div>
              ))}
            </div>

            <div className="sb-foot">
              <span className="avatar">{firstName.charAt(0)}</span>
              <span className="who">
                <span className="who-name">{fullName}</span>
                <span className="who-sub">Visão Brasil · admin</span>
              </span>
              <button className="link" onClick={logout}>sair</button>
            </div>
          </aside>

          <main className="main">
            <div className="chat" ref={scrollRef}>
              <div className="thread-col">
                {messages.length === 0 ? (
                  <div className="empty">
                    <h1>Olá, {firstName}. <em>O que olhamos hoje?</em></h1>
                    <p className="empty-sub">Pergunte em português — eu cuido do resto. Você tem visão <strong>Brasil completa</strong>.</p>
                    <div className="suggest">
                      <button onClick={() => send("Qual o faturamento de hoje no BR?")}>
                        <span className="s-title">Faturamento de hoje</span>
                        <span className="s-desc">Líquido por filial, visão BR.</span>
                      </button>
                      <button onClick={() => send("Top 10 filiais por faturamento no mês")}>
                        <span className="s-title">Top 10 filiais no mês</span>
                        <span className="s-desc">Ranking de faturamento do mês corrente.</span>
                      </button>
                      <button onClick={() => send("Como está a ruptura hoje no BR?")}>
                        <span className="s-title">Ruptura agora</span>
                        <span className="s-desc">SKUs em falta e valor perdido por filial.</span>
                      </button>
                      <button onClick={() => send("Top fornecedores do mês por faturamento")}>
                        <span className="s-title">Top fornecedores</span>
                        <span className="s-desc">Maiores fornecedores no mês corrente.</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  messages.map((m, i) => (
                    <div key={i} className={`row ${m.role}`}>
                      <div className="gutter">
                        {m.role === "assistant"
                          ? <span className="bot-mark">E</span>
                          : <span className="avatar small">{firstName.charAt(0)}</span>}
                      </div>
                      <div className="content">
                        <div className="who-line">{m.role === "assistant" ? "EBD.ia" : firstName}</div>
                        {m.role === "assistant" && m.tools && m.tools.length > 0 && (
                          <div className="tools"><span className="tool-chip">⚡ Winthor consultado</span></div>
                        )}
                        {m.status && <div className="status"><span className="dots">{m.status}</span></div>}
                        {m.text && (m.role === "assistant"
                          ? <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown></div>
                          : <div className="usertext">{m.text}</div>)}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {error && <div className="error-bar">{error}</div>}

            <div className="composer-wrap">
              <div className="composer">
                <textarea
                  ref={taRef}
                  value={input}
                  onChange={(e) => { setInput(e.target.value); autosize(); }}
                  onKeyDown={onKey}
                  placeholder="Pergunte ao EBD.ia…"
                  rows={1}
                  disabled={busy}
                />
                <div className="composer-foot">
                  <span className="chips">
                    <span className="chip"><span className="dot-ok" /> Winthor</span>
                    {(() => {
                      const current = me?.models.available.find((m) => m.id === selectedModel);
                      const label = current?.label || "Claude Haiku 4.5";
                      const isAdmin = me?.role === "admin";
                      const lockedByConv = !!active && active.msgs.length > 0;
                      if (!isAdmin || lockedByConv) {
                        return <span className="chip muted" title={lockedByConv ? "Modelo fixado nessa conversa" : ""}>{label}</span>;
                      }
                      return (
                        <span className="chip model-picker" onClick={() => setModelOpen((o) => !o)}>
                          {label} <span style={{opacity: 0.5, marginLeft: 4}}>▾</span>
                          {modelOpen && (
                            <div className="model-menu" onClick={(e) => e.stopPropagation()}>
                              {me!.models.available.map((m) => (
                                <div
                                  key={m.id}
                                  className={`model-item ${m.id === selectedModel ? "selected" : ""}`}
                                  onClick={() => { setSelectedModel(m.id); setModelOpen(false); }}
                                >
                                  <span className="model-label">{m.label}</span>
                                  <span className="model-tier">{m.tier}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </span>
                      );
                    })()}
                  </span>
                  {busy ? (
                    <button className="send stop" onClick={stop} title="Parar">■</button>
                  ) : (
                    <button className="send" onClick={() => send()} disabled={!input.trim()}>↑</button>
                  )}
                </div>
              </div>
              <p className="disclaimer">Visão Brasil · escopo aplicado automaticamente · ⏎ enviar · ⇧⏎ nova linha</p>
            </div>
          </main>
        </div>
      </AuthenticatedTemplate>
    </>
  );
}

export default App;
