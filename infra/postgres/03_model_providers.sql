-- ═══════════════════════════════════════════════════════════════════
-- PostgreSQL Schema — Model Providers & Assignments
-- Реестр провайдеров (Ollama, vLLM, OpenAI, OpenRouter и др.)
-- и назначение моделей по ролям (llm, vlm, embedding, reranker).
-- ═══════════════════════════════════════════════════════════════════

-- ─── ПРОВАЙДЕРЫ МОДЕЛЕЙ ─────────────────────────────────────────────
-- type: ollama_gpu, ollama_cpu, vllm, openai, anthropic, openrouter, google, minimax, z_ai
-- config: JSON (url для локальных, base_url для openrouter и т.д.)
-- api_key_set: true если ключ задан (через env или в БД)
CREATE TABLE IF NOT EXISTS model_providers (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    type            VARCHAR(50)  NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    config          JSONB        NOT NULL DEFAULT '{}',
    api_key_set     BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_providers_type ON model_providers (type);

-- ─── НАЗНАЧЕНИЕ МОДЕЛЕЙ ПО РОЛЯМ ────────────────────────────────────
-- Одна запись на роль: какая модель какого провайдера используется
CREATE TABLE IF NOT EXISTS model_assignments (
    role            VARCHAR(30)  NOT NULL PRIMARY KEY
                    CHECK (role IN ('llm', 'vlm', 'embedding', 'reranker')),
    provider_id     UUID         NOT NULL REFERENCES model_providers(id) ON DELETE RESTRICT,
    model_id        VARCHAR(255) NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Сидер: провайдеры Ollama GPU и CPU по умолчанию (фиксированные UUID для ссылок)
INSERT INTO model_providers (id, type, name, config, api_key_set, created_at)
VALUES
    ('a0000001-0000-4000-8000-000000000001', 'ollama_gpu', 'Ollama GPU', '{"url": "http://ollama-gpu:11434"}', FALSE, NOW()),
    ('a0000001-0000-4000-8000-000000000002', 'ollama_cpu', 'Ollama CPU', '{"url": "http://ollama-cpu:11434"}', FALSE, NOW())
ON CONFLICT (type) DO NOTHING;

-- Сидер: облачные провайдеры (ключи задаются через env: OPENAI_API_KEY и т.д.)
INSERT INTO model_providers (id, type, name, config, api_key_set, created_at)
VALUES
    ('a0000001-0000-4000-8000-000000000011', 'openai', 'OpenAI', '{"base_url": "https://api.openai.com/v1"}', FALSE, NOW()),
    ('a0000001-0000-4000-8000-000000000012', 'anthropic', 'Anthropic (Claude)', '{}', FALSE, NOW()),
    ('a0000001-0000-4000-8000-000000000013', 'openrouter', 'OpenRouter', '{"base_url": "https://openrouter.ai/api/v1"}', FALSE, NOW()),
    ('a0000001-0000-4000-8000-000000000021', 'vllm', 'vLLM (локальный)', '{}', FALSE, NOW())
ON CONFLICT (type) DO NOTHING;

-- Сидер: назначения по умолчанию (Ollama GPU для LLM/VLM, Ollama CPU для embedding/reranker)
INSERT INTO model_assignments (role, provider_id, model_id, updated_at)
VALUES
    ('llm',       'a0000001-0000-4000-8000-000000000001', 'qwen3:30b',           NOW()),
    ('vlm',       'a0000001-0000-4000-8000-000000000001', 'qwen3-vl:14b',        NOW()),
    ('embedding', 'a0000001-0000-4000-8000-000000000002', 'qwen3-embedding',     NOW()),
    ('reranker',  'a0000001-0000-4000-8000-000000000002', 'qwen3-reranker',     NOW())
ON CONFLICT (role) DO NOTHING;
