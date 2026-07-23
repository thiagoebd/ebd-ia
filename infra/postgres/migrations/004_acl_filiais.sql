-- Fonte única da estrutura filial/depósito/regional.
-- Regra de negócio: depósitos NÃO são filiais comerciais. Em ruptura física
-- entram agrupados na filial-mãe; em faturamento comercial não entram.

CREATE TABLE IF NOT EXISTS acl_filiais (
  codigo      text PRIMARY KEY,
  nome        text NOT NULL,
  tipo        text NOT NULL CHECK (tipo IN ('filial','deposito')),
  filial_mae  text REFERENCES acl_filiais(codigo),
  regional    text,
  ativa       boolean NOT NULL DEFAULT true,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT acl_filiais_coerencia CHECK (
    (tipo = 'filial'   AND regional IS NOT NULL AND filial_mae IS NULL) OR
    (tipo = 'deposito' AND regional IS NULL     AND filial_mae IS NOT NULL)
  )
);

INSERT INTO acl_filiais (codigo, nome, tipo, regional) VALUES
  ('01','EBD MATRIZ','filial','NO2'),      ('02','EBD SP','filial','SP1'),
  ('03','EBD FORTALEZA','filial','NE2'),   ('04','EBD SAO LUIS','filial','NE1'),
  ('05','EBD DUQUE','filial','RJ2'),       ('06','EBD MANAUS','filial','NO1'),
  ('07','EBD MACAPA','filial','NO2'),      ('08','EBD BOA VISTA','filial','NO1'),
  ('09','EBD JUAZEIRO','filial','NE2'),    ('10','EBD SAO GONCALO','filial','RJ1'),
  ('11','EBD SANTAREM','filial','NO2'),    ('12','EBD IMPERATRIZ','filial','NE1'),
  ('13','EBD TAQUARA','filial','RJ1'),     ('14','EBD PIRAI','filial','RJ2'),
  ('15','EBD GUARULHOS','filial','SP2'),   ('16','EBD ITAPEVI','filial','SP1'),
  ('18','EBD SBC','filial','SP2'),         ('21','EBD TERESINA','filial','NE2'),
  ('22','EBD MARABA','filial','NO2'),      ('52','EBDN PETROLINA','filial','NE3'),
  ('53','EBDN CARUARU','filial','NE3')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO acl_filiais (codigo, nome, tipo, filial_mae) VALUES
  ('17','CD SAO PEDRO DA ALDEIA','deposito','10'),
  ('19','CD SAO LUIS','deposito','04'),
  ('23','CD PETROPOLIS','deposito','14')
ON CONFLICT (codigo) DO NOTHING;

CREATE OR REPLACE VIEW acl_filiais_resolvido AS
SELECT f.codigo, f.nome, f.tipo, f.filial_mae, f.ativa,
       COALESCE(f.regional, m.regional) AS regional
FROM acl_filiais f
LEFT JOIN acl_filiais m ON m.codigo = f.filial_mae;
