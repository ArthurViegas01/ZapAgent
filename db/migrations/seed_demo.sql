-- Demo seed: a single tenant + a few FAQ rows for the StubProvider demo.
-- Idempotent; safe to re-run.

BEGIN;

INSERT INTO tenants (id, slug, name, settings, data_retention_days)
VALUES (
    '00000000-0000-0000-0000-0000000d3070',
    'demo',
    'Salao Demo',
    jsonb_build_object(
        'agent_persona', 'Atendente educado e prestativo de um salao de beleza.',
        'business_hours', jsonb_build_object('open', '09:00', 'close', '19:00')
    ),
    365
)
ON CONFLICT (id) DO UPDATE
SET name     = EXCLUDED.name,
    settings = EXCLUDED.settings;

INSERT INTO faq_items (tenant_id, question, answer)
VALUES
    ('00000000-0000-0000-0000-0000000d3070',
     'Qual e o horario de funcionamento?',
     'Atendemos de segunda a sabado, das 9h as 19h.'),
    ('00000000-0000-0000-0000-0000000d3070',
     'Qual o preco do corte de cabelo?',
     'O corte feminino esta R$ 80 e o masculino R$ 50.'),
    ('00000000-0000-0000-0000-0000000d3070',
     'Voces aceitam Pix?',
     'Sim, aceitamos Pix, dinheiro e cartao.')
ON CONFLICT (tenant_id, question) DO NOTHING;

COMMIT;
