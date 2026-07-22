CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS acl_users (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email        text UNIQUE NOT NULL,
  oid          text,
  nome         text,
  role         text    NOT NULL DEFAULT 'admin'  CHECK (role IN ('admin','gerente','supervisor')),
  scope_kind   text    NOT NULL DEFAULT 'brasil' CHECK (scope_kind IN ('brasil','regional','filiais','filial')),
  scope_value  jsonb   NOT NULL DEFAULT '[]'::jsonb,
  filiais      jsonb   NOT NULL DEFAULT '"*"'::jsonb,
  super_admin  boolean NOT NULL DEFAULT false,
  active       boolean NOT NULL DEFAULT true,
  created_by   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_acl_users_email_lower ON acl_users (lower(email));

CREATE TABLE IF NOT EXISTS acl_audit (
  id bigserial PRIMARY KEY, actor_email text, action text NOT NULL,
  target_email text, before jsonb, after jsonb, at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO acl_users (email, nome, role, scope_kind, filiais, super_admin, created_by) VALUES
  ('thiago.parreira@ebdgrupo.com.br','Thiago Parreira','admin','brasil','"*"', true,  'seed'),
  ('smoraes@ebdgrupo.com.br',        'S. Moraes',      'admin','brasil','"*"', false, 'seed'),
  ('rosana.cesario@ebdgrupo.com.br', 'Rosana Cesario', 'admin','brasil','"*"', false, 'seed'),
  ('filipe@ebdgrupo.com.br',         'Filipe',         'admin','brasil','"*"', false, 'seed'),
  ('enrico.montini@ebdgrupo.com.br', 'Enrico Montini', 'admin','brasil','"*"', false, 'seed'),
  ('andre@ebdgrupo.com.br',          'Andre Andrade',  'admin','brasil','"*"', false, 'seed'),
  ('abel.nau@ebdgrupo.com.br',       'Abel Nau',       'admin','brasil','"*"', false, 'seed'),
  ('viviane.pedroso@ebdgrupo.com.br','Viviane Pedroso','admin','brasil','"*"', false, 'seed'),
  ('fernanda@ebdgrupo.com.br',       'Fernanda',       'admin','brasil','"*"', false, 'seed'),
  ('tercio.quatroni@ebdgrupo.com.br','Tercio Quatroni','admin','brasil','"*"', false, 'seed'),
  ('fabio.alves@ebdgrupo.com.br',    'Fabio Alves',    'admin','brasil','"*"', false, 'seed'),
  ('hudson.coutinho@ebdgrupo.com.br','Hudson Coutinho','admin','brasil','"*"', false, 'seed'),
  ('thomaz.farha@ebdgrupo.com.br',   'Thomaz Farha',   'admin','brasil','"*"', false, 'seed'),
  ('alberto.araujo@ebdgrupo.com.br', 'Alberto Araujo', 'admin','brasil','"*"', false, 'seed')
ON CONFLICT (email) DO NOTHING;
