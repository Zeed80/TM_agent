-- ═══════════════════════════════════════════════════════════════════
-- PostgreSQL Schema — Enterprise AI Assistant
-- Автоматически выполняется при первом старте контейнера.
-- Таблицы: tools_catalog, metals_catalog, polymers_catalog,
--          inventory, employees
-- ═══════════════════════════════════════════════════════════════════

-- Расширение для gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ───────────────────────────────────────────────────────────────────
-- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ — автообновление updated_at
-- ───────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

-- ───────────────────────────────────────────────────────────────────
-- ИНСТРУМЕНТАЛЬНЫЙ КАТАЛОГ
-- Фрезы, резцы, сверла, метчики и прочий режущий инструмент
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tools_catalog (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(255) NOT NULL,
    type             VARCHAR(100) NOT NULL,       -- 'mill' | 'lathe_tool' | 'drill' | 'tap' | 'reamer' | 'insert' | 'other'
    size             VARCHAR(100),                -- Например: 'D10', '25x25x150', 'M8'
    gost             VARCHAR(100),                -- ГОСТ или ISO
    manufacturer     VARCHAR(255),
    coating          VARCHAR(100),                -- 'TiN' | 'TiAlN' | 'DLC' | 'none'
    material         VARCHAR(100),               -- 'HSS' | 'carbide' | 'ceramic' | 'CBN'
    description      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER tools_catalog_updated_at
    BEFORE UPDATE ON tools_catalog
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ───────────────────────────────────────────────────────────────────
-- КАТАЛОГ МЕТАЛЛОВ / СТАЛЕЙ / СПЛАВОВ
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS metals_catalog (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  VARCHAR(255) NOT NULL,  -- 'Сталь конструкционная'
    gost                  VARCHAR(100) NOT NULL,  -- 'ГОСТ 1050-2013'
    grade                 VARCHAR(100) NOT NULL,  -- '45', '40Х', '12Х18Н10Т'
    density_g_cm3         NUMERIC(6,3),
    hardness_hb           INTEGER,                -- Твёрдость по Бринеллю
    tensile_strength_mpa  INTEGER,                -- Предел прочности
    yield_strength_mpa    INTEGER,                -- Предел текучести
    elongation_pct        NUMERIC(5,2),           -- Относительное удлинение, %
    description           TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ───────────────────────────────────────────────────────────────────
-- КАТАЛОГ ПОЛИМЕРОВ (для ТПА)
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS polymers_catalog (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    VARCHAR(255) NOT NULL,  -- 'Полиамид 6'
    grade                   VARCHAR(100) NOT NULL,  -- 'PA6-GF30', 'ABS HI-121H'
    manufacturer            VARCHAR(255),
    mfi_g_10min             NUMERIC(8,3),           -- Показатель текучести расплава (г/10 мин)
    density_g_cm3           NUMERIC(6,3),
    melting_temp_c          INTEGER,                -- Температура плавления, °C
    processing_temp_min_c   INTEGER,                -- Мин. температура переработки
    processing_temp_max_c   INTEGER,                -- Макс. температура переработки
    mold_temp_min_c         INTEGER,                -- Мин. температура формы
    mold_temp_max_c         INTEGER,                -- Макс. температура формы
    injection_pressure_bar  INTEGER,                -- Давление литья, бар
    shrinkage_pct           NUMERIC(5,3),           -- Усадка, %
    moisture_content_max    NUMERIC(5,3),           -- Допустимая влажность перед сушкой, %
    drying_temp_c           INTEGER,                -- Температура сушки
    drying_time_h           NUMERIC(4,1),           -- Время сушки, часы
    description             TEXT,
    datasheet_path          VARCHAR(500),           -- Путь к технической документации
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ───────────────────────────────────────────────────────────────────
-- СКЛАДСКОЙ УЧЁТ
-- Единая таблица для всех типов: инструмент, металл, полимер
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inventory (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    item_type          VARCHAR(20)  NOT NULL
                           CHECK (item_type IN ('tool', 'metal', 'polymer')),
    catalog_item_id    UUID         NOT NULL,        -- FK на tools_catalog / metals_catalog / polymers_catalog
    quantity           NUMERIC(12,3) NOT NULL DEFAULT 0
                           CHECK (quantity >= 0),
    unit               VARCHAR(20)  NOT NULL,        -- 'pcs' | 'kg' | 'm' | 'l' | 'm2'
    warehouse_location VARCHAR(100),                 -- 'Склад А, стеллаж 3, полка 2'
    reserved_quantity  NUMERIC(12,3) NOT NULL DEFAULT 0
                           CHECK (reserved_quantity >= 0),
    last_updated       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    notes              TEXT,

    -- Гарантируем уникальность позиции на складе по типу и id товара
    CONSTRAINT inventory_unique_item UNIQUE (item_type, catalog_item_id)
);

-- Функция обновления last_updated при изменении остатков
CREATE OR REPLACE FUNCTION update_inventory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = NOW();
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

CREATE TRIGGER inventory_updated_at
    BEFORE UPDATE ON inventory
    FOR EACH ROW EXECUTE FUNCTION update_inventory_timestamp();

-- ───────────────────────────────────────────────────────────────────
-- СПРАВОЧНИК СОТРУДНИКОВ
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS employees (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name    VARCHAR(255) NOT NULL,
    department   VARCHAR(100),   -- 'Технологический отдел', 'ОГМ', 'Производство'
    position     VARCHAR(100),   -- 'Технолог', 'Мастер участка'
    email        VARCHAR(255),
    phone        VARCHAR(50),
    telegram_id  BIGINT,         -- Telegram user_id для уведомлений
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ───────────────────────────────────────────────────────────────────
-- ИНДЕКСЫ
-- ───────────────────────────────────────────────────────────────────

-- Основной поиск по складу: по типу и ID товара
CREATE INDEX IF NOT EXISTS idx_inventory_item
    ON inventory (item_type, catalog_item_id);

-- Поиск позиций с низким остатком
CREATE INDEX IF NOT EXISTS idx_inventory_qty
    ON inventory (quantity);

-- Поиск инструмента по типу (основной фильтр)
CREATE INDEX IF NOT EXISTS idx_tools_type
    ON tools_catalog (type);

-- Поиск металлов по ГОСТ и марке
CREATE INDEX IF NOT EXISTS idx_metals_gost
    ON metals_catalog (gost);

CREATE INDEX IF NOT EXISTS idx_metals_grade
    ON metals_catalog (grade);

-- Поиск полимеров по марке
CREATE INDEX IF NOT EXISTS idx_polymers_grade
    ON polymers_catalog (grade);

-- Поиск активных сотрудников по отделу
CREATE INDEX IF NOT EXISTS idx_employees_department
    ON employees (department)
    WHERE is_active = TRUE;

-- Поиск сотрудника по telegram_id (для уведомлений)
CREATE INDEX IF NOT EXISTS idx_employees_telegram_id
    ON employees (telegram_id)
    WHERE telegram_id IS NOT NULL;

-- ───────────────────────────────────────────────────────────────────
-- ТЕСТОВЫЕ ДАННЫЕ (минимальные, для первоначальной проверки)
-- ───────────────────────────────────────────────────────────────────

INSERT INTO tools_catalog (name, type, size, gost, manufacturer, coating, material)
VALUES
    ('Фреза концевая Ø10', 'mill', 'D10 L72', 'ГОСТ 17025-71', 'Sandvik', 'TiAlN', 'carbide'),
    ('Фреза концевая Ø16', 'mill', 'D16 L92', 'ГОСТ 17025-71', 'Iscar', 'TiAlN', 'carbide'),
    ('Резец проходной 25х25', 'lathe_tool', '25x25x150', 'ГОСТ 18877-73', 'Korloy', 'TiN', 'carbide'),
    ('Сверло Ø8 HSS', 'drill', 'D8 L117', 'ГОСТ 10902-77', 'Dormer', 'none', 'HSS'),
    ('Метчик М8 HSS', 'tap', 'M8 p1.25', 'ГОСТ 3266-81', 'Yamawa', 'TiN', 'HSS')
ON CONFLICT DO NOTHING;

INSERT INTO polymers_catalog (name, grade, manufacturer, mfi_g_10min, density_g_cm3,
    melting_temp_c, processing_temp_min_c, processing_temp_max_c,
    mold_temp_min_c, mold_temp_max_c, shrinkage_pct)
VALUES
    ('Полиамид 6', 'PA6 B3', 'BASF', 13.0, 1.14, 220, 240, 280, 60, 90, 1.2),
    ('Полиамид 6 со стекловолокном 30%', 'PA6-GF30', 'Lanxess', 7.0, 1.36, 220, 260, 290, 70, 100, 0.5),
    ('АБС-пластик', 'ABS HI-121H', 'INEOS', 22.0, 1.05, 105, 210, 250, 40, 80, 0.5)
ON CONFLICT DO NOTHING;

INSERT INTO metals_catalog (name, gost, grade, density_g_cm3, hardness_hb,
    tensile_strength_mpa, yield_strength_mpa)
VALUES
    ('Сталь конструкционная', 'ГОСТ 1050-2013', '45', 7.85, 197, 598, 353),
    ('Сталь легированная', 'ГОСТ 4543-2016', '40Х', 7.82, 217, 785, 638),
    ('Сталь нержавеющая аустенитная', 'ГОСТ 5632-2014', '12Х18Н10Т', 7.90, 179, 540, 196)
ON CONFLICT DO NOTHING;

-- Инициализируем склад с небольшими тестовыми остатками
INSERT INTO inventory (item_type, catalog_item_id, quantity, unit, warehouse_location)
SELECT 'tool', id, 10, 'pcs', 'Склад А, стеллаж 1'
FROM tools_catalog
ON CONFLICT DO NOTHING;

INSERT INTO inventory (item_type, catalog_item_id, quantity, unit, warehouse_location)
SELECT 'polymer', id, 250, 'kg', 'Склад Б, зона полимеров'
FROM polymers_catalog
ON CONFLICT DO NOTHING;

INSERT INTO inventory (item_type, catalog_item_id, quantity, unit, warehouse_location)
SELECT 'metal', id, 500, 'kg', 'Склад А, металлостеллаж'
FROM metals_catalog
ON CONFLICT DO NOTHING;
