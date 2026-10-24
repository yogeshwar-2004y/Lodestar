"""Row level security, append-only/immutable triggers, runtime role grants.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "action_plans", "agent_runs", "approvals", "audit_events", "automation_policies",
    "automation_schedules", "change_sets", "client_workspaces", "connector_capabilities",
    "connector_secret_refs", "connectors", "content_drafts", "crawl_edges", "crawl_jobs",
    "credit_ledger", "data_source_syncs", "execution_runs", "finding_occurrences",
    "idempotency_keys", "keyword_clusters", "keyword_queries", "measurement_annotations",
    "notifications", "oauth_states", "page_snapshots", "pages", "patch_versions", "plan_items",
    "reports", "rollback_snapshots", "search_metrics", "secret_blobs", "seo_findings",
    "site_verifications", "sites", "subscriptions", "tool_invocations", "usage_records",
    "workflow_runs", "workspace_memberships",
]

APPEND_ONLY = ["audit_events", "approvals", "credit_ledger"]

TENANT_PREDICATE = (
    "(current_setting('app.bypass_rls', true) = 'on' "
    "OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING {TENANT_PREDICATE} WITH CHECK {TENANT_PREDICATE}"
        )

    # Append-only tables: UPDATE is never allowed; DELETE only by the retention purge job
    # which sets app.retention_purge='on' in its transaction.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION aseo_append_only() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('app.retention_purge', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION '% on % is not allowed (append-only)', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION aseo_append_only()"
        )

    # Patch versions are immutable: content, hash and before-state can never change.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION aseo_patch_immutable() RETURNS trigger AS $$
        BEGIN
          IF NEW.patch IS DISTINCT FROM OLD.patch
             OR NEW.patch_hash IS DISTINCT FROM OLD.patch_hash
             OR NEW.before IS DISTINCT FROM OLD.before
             OR NEW.resource_version IS DISTINCT FROM OLD.resource_version
             OR NEW.change_set_id IS DISTINCT FROM OLD.change_set_id
             OR NEW.version IS DISTINCT FROM OLD.version THEN
            RAISE EXCEPTION 'patch_versions are immutable' USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER patch_versions_immutable BEFORE UPDATE ON patch_versions "
        "FOR EACH ROW EXECUTE FUNCTION aseo_patch_immutable()"
    )

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aseo_app') THEN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO aseo_app', current_database());
            GRANT USAGE ON SCHEMA public TO aseo_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aseo_app;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aseo_app;
            REVOKE ALL ON alembic_version FROM aseo_app;
            GRANT SELECT ON alembic_version TO aseo_app;
          END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS patch_versions_immutable ON patch_versions")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS aseo_patch_immutable()")
    op.execute("DROP FUNCTION IF EXISTS aseo_append_only()")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
