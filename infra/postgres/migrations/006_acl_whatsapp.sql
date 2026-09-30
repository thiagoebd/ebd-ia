-- WhatsApp na tela de Acessos: quem pode falar com o EBD.ia no grupo.
--
-- Formato canonico E.164 ('+5511999998888'), celular brasileiro sempre COM
-- o nono digito — a tela grava assim e o webhook busca assim
-- (app.adapters.whatsapp.normaliza_whatsapp).
--
-- Idempotente: pode rodar mais de uma vez.
BEGIN;

ALTER TABLE acl_users ADD COLUMN IF NOT EXISTS whatsapp text;

ALTER TABLE acl_users DROP CONSTRAINT IF EXISTS acl_users_whatsapp_e164;
ALTER TABLE acl_users ADD CONSTRAINT acl_users_whatsapp_e164
    CHECK (whatsapp IS NULL OR whatsapp ~ '^\+[1-9][0-9]{7,14}$');

-- um numero = uma pessoa: senao a resposta rodaria com o acesso de quem?
CREATE UNIQUE INDEX IF NOT EXISTS idx_acl_users_whatsapp
    ON acl_users (whatsapp) WHERE whatsapp IS NOT NULL;

COMMIT;
