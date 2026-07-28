-- 005_acl_politicas.sql
-- Politica de acesso por PERFIL, ortogonal ao escopo de filial.
--
-- O escopo de filial (acl_users + acl_filiais) responde "quais filiais este
-- usuario ve". Esta tabela responde "quais RECURSOS este perfil pode
-- consultar", seja qual for a filial. As duas se aplicam juntas.
--
-- Para criar uma restricao nova NAO se mexe em codigo: insere uma linha aqui.

BEGIN;

-- ------------------------------------------------------------------
-- 1. Roles validos e hierarquia
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS acl_roles (
    role        TEXT PRIMARY KEY,
    nivel       SMALLINT NOT NULL,
    descricao   TEXT
);

INSERT INTO acl_roles (role, nivel, descricao) VALUES
    ('admin',      5, 'TI / dono do sistema — ve tudo'),
    ('diretor',    4, 'Diretoria — ve comissao e premio'),
    ('gerente',    3, 'Gerencia comercial'),
    ('supervisor', 2, 'Supervisao de equipe'),
    ('analista',   1, 'Analista — menor privilegio e PADRAO de fallback')
ON CONFLICT (role) DO UPDATE
   SET nivel = EXCLUDED.nivel, descricao = EXCLUDED.descricao;

-- ------------------------------------------------------------------
-- 2. Politicas por recurso
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS acl_politicas (
    id                SERIAL PRIMARY KEY,
    recurso           TEXT NOT NULL UNIQUE,
    descricao         TEXT,
    tabelas           JSONB NOT NULL,   -- ["PCGM%","PCCOMISSAOUSUR"]  (% = prefixo)
    roles_permitidos  JSONB NOT NULL,   -- ["admin","diretor"]
    ativa             BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em         TIMESTAMPTZ NOT NULL DEFAULT now(),
    alterada_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_acl_politicas_ativa ON acl_politicas (ativa);

INSERT INTO acl_politicas (recurso, descricao, tabelas, roles_permitidos) VALUES
    ('comissao',
     'Premio, comissao e Gestao de Metas (rotina 3388)',
     '["PCGM%","PCCOMISSAOUSUR"]'::jsonb,
     '["admin","diretor"]'::jsonb)
ON CONFLICT (recurso) DO UPDATE
   SET tabelas = EXCLUDED.tabelas,
       roles_permitidos = EXCLUDED.roles_permitidos,
       descricao = EXCLUDED.descricao,
       alterada_em = now();

-- ------------------------------------------------------------------
-- 3. Normalizar os roles que ja existem em acl_users
--    ATENCAO: o fallback do codigo era 'admin'. Passa a ser 'analista'.
--    Quem estiver com role nulo/invalido PERDE acesso a recurso restrito.
-- ------------------------------------------------------------------
ALTER TABLE acl_users
    ADD COLUMN IF NOT EXISTS role TEXT;

UPDATE acl_users
   SET role = lower(trim(role))
 WHERE role IS NOT NULL AND role <> lower(trim(role));

-- quem nao tem role definido vira analista (menor privilegio)
UPDATE acl_users
   SET role = 'analista'
 WHERE role IS NULL
    OR lower(trim(role)) NOT IN ('admin','diretor','gerente','supervisor','analista');

COMMIT;

-- ------------------------------------------------------------------
-- CONFERENCIA (rode antes e depois)
-- ------------------------------------------------------------------
-- SELECT COALESCE(role,'(nulo)') AS role, COUNT(*) AS usuarios,
--        COUNT(*) FILTER (WHERE active) AS ativos
--   FROM acl_users GROUP BY role ORDER BY usuarios DESC;
--
-- Para liberar um recurso a mais um perfil, SEM rebuild:
--   UPDATE acl_politicas
--      SET roles_permitidos = '["admin","diretor","gerente"]'::jsonb,
--          alterada_em = now()
--    WHERE recurso = 'comissao';
--
-- Para criar uma restricao nova (exemplo: folha de pagamento):
--   INSERT INTO acl_politicas (recurso, descricao, tabelas, roles_permitidos)
--   VALUES ('folha', 'Folha e dados de RH',
--           '["PCEMPR","PCLANC%"]'::jsonb, '["admin"]'::jsonb);
