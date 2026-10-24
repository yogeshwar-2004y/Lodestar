-- Creates the runtime application role used by the API/worker. RLS policies apply to
-- this role (it is NOT a superuser and does not own the tables). Migrations run as the
-- owner role. Change the password outside local development.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aseo_app') THEN
    CREATE ROLE aseo_app LOGIN PASSWORD 'aseo_app_dev_password' NOSUPERUSER NOBYPASSRLS;
  END IF;
END$$;
