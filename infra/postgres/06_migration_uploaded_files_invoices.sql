-- Миграция: добавить папку 'invoices' в допустимые значения uploaded_files.folder
-- Выполнить один раз на существующей БД: make migrate-uploaded-folder

ALTER TABLE uploaded_files
  DROP CONSTRAINT IF EXISTS uploaded_files_folder_check;

ALTER TABLE uploaded_files
  ADD CONSTRAINT uploaded_files_folder_check
  CHECK (folder IN ('blueprints','invoices','manuals','gosts','emails','catalogs','tech_processes'));
