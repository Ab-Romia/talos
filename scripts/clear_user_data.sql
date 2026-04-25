-- Wipe user-linked data for a fresh login (keeps platform_roles / permissions).
-- psql:   psql "postgresql://USER:PASS@localhost:5432/DB" -f scripts/clear_user_data.sql
-- Python: from repo root, PYTHONPATH=src uv run python scripts/clear_user_data.py

TRUNCATE TABLE
  message_files,
  messages,
  file_attachments,
  chatrooms,
  workspaces,
  sessions,
  identity_providers,
  otp,
  users_platform_roles,
  users
RESTART IDENTITY;
