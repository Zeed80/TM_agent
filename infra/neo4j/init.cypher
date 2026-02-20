// ═══════════════════════════════════════════════════════════════════
// Neo4j Schema Initialization — Enterprise AI Assistant
// Запуск: make init-db
// Или вручную:
//   docker compose exec neo4j cypher-shell -u neo4j -p PASSWORD \
//     --non-interactive -f /var/lib/neo4j/import/init.cypher
// ═══════════════════════════════════════════════════════════════════

// ───────────────────────────────────────────────────────────────────
// УНИКАЛЬНЫЕ ОГРАНИЧЕНИЯ (автоматически создают индексы по id)
// ───────────────────────────────────────────────────────────────────

CREATE CONSTRAINT part_id_unique IF NOT EXISTS
  FOR (n:Part) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT assembly_id_unique IF NOT EXISTS
  FOR (n:Assembly) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT drawing_id_unique IF NOT EXISTS
  FOR (n:Drawing) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT material_id_unique IF NOT EXISTS
  FOR (n:Material) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT machine_id_unique IF NOT EXISTS
  FOR (n:Machine) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT mold_id_unique IF NOT EXISTS
  FOR (n:Mold) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT tool_id_unique IF NOT EXISTS
  FOR (n:Tool) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT techprocess_id_unique IF NOT EXISTS
  FOR (n:TechProcess) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT operation_id_unique IF NOT EXISTS
  FOR (n:Operation) REQUIRE n.id IS UNIQUE;

// Операции изготовления (из blueprint_ingestion)
CREATE CONSTRAINT mfg_operation_id_unique IF NOT EXISTS
  FOR (n:ManufacturingOperation) REQUIRE n.id IS UNIQUE;

// Типы инструмента (из blueprint_ingestion)
CREATE CONSTRAINT tool_type_id_unique IF NOT EXISTS
  FOR (n:ToolType) REQUIRE n.id IS UNIQUE;

// Виды поверхностной обработки (из blueprint_ingestion)
CREATE CONSTRAINT surface_treatment_id_unique IF NOT EXISTS
  FOR (n:SurfaceTreatment) REQUIRE n.id IS UNIQUE;

// Виды термообработки (из blueprint_ingestion)
CREATE CONSTRAINT heat_treatment_id_unique IF NOT EXISTS
  FOR (n:HeatTreatment) REQUIRE n.id IS UNIQUE;

// ───────────────────────────────────────────────────────────────────
// ДОПОЛНИТЕЛЬНЫЕ ИНДЕКСЫ для частых поисков
// ───────────────────────────────────────────────────────────────────

// Поиск детали по номеру чертежа (основной идентификатор в производстве)
CREATE INDEX part_drawing_number_idx IF NOT EXISTS
  FOR (n:Part) ON (n.drawing_number);

// Поиск чертежа по номеру и ревизии
CREATE INDEX drawing_number_idx IF NOT EXISTS
  FOR (n:Drawing) ON (n.drawing_number);

CREATE INDEX drawing_revision_idx IF NOT EXISTS
  FOR (n:Drawing) ON (n.revision);

// Поиск чертежа по пути файла (основной lookup для blueprint-vision)
CREATE INDEX drawing_file_path_idx IF NOT EXISTS
  FOR (n:Drawing) ON (n.file_path);

// Поиск операций по типу
CREATE INDEX mfg_operation_name_idx IF NOT EXISTS
  FOR (n:ManufacturingOperation) ON (n.name);

// Поиск типов инструмента
CREATE INDEX tool_type_name_idx IF NOT EXISTS
  FOR (n:ToolType) ON (n.name);

// Поиск по типу обработки
CREATE INDEX surface_treatment_type_idx IF NOT EXISTS
  FOR (n:SurfaceTreatment) ON (n.type);

CREATE INDEX heat_treatment_type_idx IF NOT EXISTS
  FOR (n:HeatTreatment) ON (n.type);

// Поиск пресс-формы по номеру
CREATE INDEX mold_number_idx IF NOT EXISTS
  FOR (n:Mold) ON (n.mold_number);

// Фильтрация станков по типу (CNC / UNIVERSAL_LATHE / UNIVERSAL_MILLING / TPA)
CREATE INDEX machine_type_idx IF NOT EXISTS
  FOR (n:Machine) ON (n.type);

// Фильтрация станков по статусу (ACTIVE / MAINTENANCE / IDLE)
CREATE INDEX machine_status_idx IF NOT EXISTS
  FOR (n:Machine) ON (n.status);

// Поиск инструмента по типу
CREATE INDEX tool_type_idx IF NOT EXISTS
  FOR (n:Tool) ON (n.type);

// Поиск инструмента по ГОСТ
CREATE INDEX tool_gost_idx IF NOT EXISTS
  FOR (n:Tool) ON (n.gost);

// Поиск техпроцесса по номеру
CREATE INDEX techprocess_number_idx IF NOT EXISTS
  FOR (n:TechProcess) ON (n.number);

// Поиск техпроцесса по статусу (ACTIVE / ARCHIVED)
CREATE INDEX techprocess_status_idx IF NOT EXISTS
  FOR (n:TechProcess) ON (n.status);

// Поиск материала по марке
CREATE INDEX material_grade_idx IF NOT EXISTS
  FOR (n:Material) ON (n.grade);

// ───────────────────────────────────────────────────────────────────
// ПОЛНОТЕКСТОВЫЕ ИНДЕКСЫ для поиска по названию
// (используются в Text-to-Cypher генерации когда нет точного id)
// ───────────────────────────────────────────────────────────────────

CREATE FULLTEXT INDEX part_fulltext_idx IF NOT EXISTS
  FOR (n:Part) ON EACH [n.name, n.drawing_number, n.technical_requirements];

CREATE FULLTEXT INDEX mfg_operation_fulltext_idx IF NOT EXISTS
  FOR (n:ManufacturingOperation) ON EACH [n.name, n.description];

CREATE FULLTEXT INDEX machine_fulltext_idx IF NOT EXISTS
  FOR (n:Machine) ON EACH [n.name, n.model];

CREATE FULLTEXT INDEX tool_fulltext_idx IF NOT EXISTS
  FOR (n:Tool) ON EACH [n.name, n.type, n.gost];

CREATE FULLTEXT INDEX mold_fulltext_idx IF NOT EXISTS
  FOR (n:Mold) ON EACH [n.name, n.mold_number];

CREATE FULLTEXT INDEX material_fulltext_idx IF NOT EXISTS
  FOR (n:Material) ON EACH [n.name, n.grade, n.gost];

// ───────────────────────────────────────────────────────────────────
// ПРОВЕРКА — вывести все созданные ограничения и индексы
// ───────────────────────────────────────────────────────────────────

SHOW CONSTRAINTS;
SHOW INDEXES;
