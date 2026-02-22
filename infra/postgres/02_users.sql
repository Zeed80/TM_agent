-- ═══════════════════════════════════════════════════════════════════
-- PostgreSQL Schema — Users, Chat Sessions, Messages, Uploaded Files
-- Выполняется автоматически при первом старте контейнера (алфавитный порядок).
-- Таблицы: users, chat_sessions, chat_messages, uploaded_files
-- ═══════════════════════════════════════════════════════════════════

-- ─── ПОЛЬЗОВАТЕЛИ ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(100) NOT NULL UNIQUE,
    full_name     VARCHAR(255),
    email         VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'user'
                      CHECK (role IN ('admin', 'user')),
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
CREATE INDEX IF NOT EXISTS idx_users_email    ON users (email) WHERE email IS NOT NULL;

-- ─── СЕССИИ ЧАТА ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(255) NOT NULL DEFAULT 'Новый чат',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
    ON chat_sessions (user_id, updated_at DESC);

-- ─── СООБЩЕНИЯ ЧАТА ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_messages (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID        NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL
                    CHECK (role IN ('user', 'assistant', 'tool')),
    content     TEXT        NOT NULL DEFAULT '',
    tool_name   VARCHAR(100),
    tool_input  JSONB,
    tool_result JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at ASC);

-- ─── ЗАГРУЖЕННЫЕ ФАЙЛЫ ───────────────────────────────────────────────
-- Учёт файлов, загруженных пользователями через веб-интерфейс.
-- Сами файлы хранятся в Docker-volume /app/documents/<folder>/
CREATE TABLE IF NOT EXISTS uploaded_files (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    filename    VARCHAR(500) NOT NULL,
    folder      VARCHAR(100) NOT NULL
                    CHECK (folder IN ('blueprints','invoices','manuals','gosts','emails','catalogs','tech_processes')),
    file_size   BIGINT,
    mime_type   VARCHAR(255),
    status      VARCHAR(20)  NOT NULL DEFAULT 'uploaded'
                    CHECK (status IN ('uploaded','processing','indexed','error')),
    error_msg   TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_user
    ON uploaded_files (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_status
    ON uploaded_files (status) WHERE status != 'indexed';
