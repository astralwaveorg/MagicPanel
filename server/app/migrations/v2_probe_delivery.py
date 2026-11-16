"""V2 探测、路由计划与资源发布表；调用方必须已在事务内。"""


def migrate(conn) -> None:
    if not conn.in_transaction:
        raise ValueError('migration_transaction_required')
    statements = (
        """CREATE TABLE IF NOT EXISTS probe_jobs (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=0),
            trigger TEXT NOT NULL, schedule_key TEXT UNIQUE,
            observer_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
            scope_json TEXT NOT NULL DEFAULT '{}', budget_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
            lease_owner TEXT, lease_until TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
            reason_codes_json TEXT NOT NULL DEFAULT '[]')""",
        """CREATE TABLE IF NOT EXISTS probe_items (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES probe_jobs(id) ON DELETE CASCADE,
            node_uid TEXT NOT NULL, node_revision INTEGER NOT NULL CHECK(node_revision>=1),
            service_key TEXT NOT NULL, source_bucket TEXT NOT NULL DEFAULT '',
            fault_bucket TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0), next_at TEXT,
            lease_owner TEXT, lease_until TEXT,
            UNIQUE(job_id,node_uid,node_revision,service_key))""",
        """CREATE TABLE IF NOT EXISTS probe_results (
            id TEXT PRIMARY KEY, item_id TEXT NOT NULL UNIQUE REFERENCES probe_items(id),
            observer_id TEXT NOT NULL, path_epoch INTEGER NOT NULL DEFAULT 0,
            probe_id TEXT NOT NULL, probe_version TEXT NOT NULL,
            transport_state TEXT NOT NULL, result_state TEXT NOT NULL,
            reason_code TEXT NOT NULL DEFAULT '', http_status INTEGER,
            egress_json TEXT NOT NULL DEFAULT '{}', evidence_json TEXT NOT NULL DEFAULT '{}',
            request_count INTEGER NOT NULL DEFAULT 0 CHECK(request_count>=0),
            bytes_read INTEGER NOT NULL DEFAULT 0 CHECK(bytes_read>=0),
            bytes_written INTEGER NOT NULL DEFAULT 0 CHECK(bytes_written>=0),
            measured_at TEXT NOT NULL, valid_until TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS probe_reservations (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES probe_jobs(id),
            item_id TEXT REFERENCES probe_items(id), reservation_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            requests_reserved INTEGER NOT NULL DEFAULT 0 CHECK(requests_reserved>=0),
            requests_used INTEGER NOT NULL DEFAULT 0 CHECK(requests_used>=0),
            bytes_reserved INTEGER NOT NULL DEFAULT 0 CHECK(bytes_reserved>=0),
            bytes_used INTEGER NOT NULL DEFAULT 0 CHECK(bytes_used>=0),
            reserved_at TEXT NOT NULL, settled_at TEXT,
            state TEXT NOT NULL DEFAULT 'reserved')""",
        """CREATE TABLE IF NOT EXISTS probe_observers (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, public_key TEXT NOT NULL DEFAULT '',
            config_revision INTEGER NOT NULL DEFAULT 1 CHECK(config_revision>=1),
            enabled INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS probe_paths (
            id TEXT PRIMARY KEY, observer_id TEXT NOT NULL REFERENCES probe_observers(id),
            epoch INTEGER NOT NULL CHECK(epoch>=1), contract_json TEXT NOT NULL DEFAULT '{}',
            proof_json TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'pending',
            qualified_at TEXT, expires_at TEXT, UNIQUE(observer_id,epoch))""",
        """CREATE TABLE IF NOT EXISTS probe_adapter_health (
            probe_id TEXT NOT NULL, probe_version TEXT NOT NULL, state TEXT NOT NULL,
            window_json TEXT NOT NULL DEFAULT '{}', last_reason TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL, PRIMARY KEY(probe_id,probe_version))""",
        """CREATE TABLE IF NOT EXISTS routing_plans (
            plan_sha TEXT PRIMARY KEY, eligibility_sha TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}', input_json TEXT NOT NULL DEFAULT '{}',
            safe_output_json TEXT NOT NULL DEFAULT '{}', evaluation_at TEXT NOT NULL,
            accepted_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS resource_revisions (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, logical_name TEXT NOT NULL,
            content_sha TEXT NOT NULL, blob_id TEXT NOT NULL REFERENCES private_blobs(blob_id),
            behavior TEXT NOT NULL DEFAULT '', format TEXT NOT NULL,
            byte_length INTEGER NOT NULL CHECK(byte_length>=0),
            schema_version TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT,
            UNIQUE(kind,logical_name,content_sha,schema_version,behavior,format))""",
        """CREATE TABLE IF NOT EXISTS build_manifests (
            build_id TEXT PRIMARY KEY, manifest_sha TEXT NOT NULL,
            private_json TEXT NOT NULL DEFAULT '{}', safe_json TEXT NOT NULL DEFAULT '{}',
            ready INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS build_resources (
            build_id TEXT NOT NULL REFERENCES build_manifests(build_id),
            artifact_key TEXT NOT NULL, resource_id TEXT NOT NULL REFERENCES resource_revisions(id),
            PRIMARY KEY(build_id,artifact_key,resource_id))""",
        """CREATE TABLE IF NOT EXISTS resource_aliases (
            device_id INTEGER NOT NULL, variant_id INTEGER NOT NULL,
            kind TEXT NOT NULL, legacy_name TEXT NOT NULL, build_id TEXT NOT NULL,
            resource_id TEXT NOT NULL REFERENCES resource_revisions(id),
            UNIQUE(device_id,variant_id,kind,legacy_name,build_id))""",
        """CREATE TABLE IF NOT EXISTS artifact_leases (
            device_id INTEGER NOT NULL, build_id TEXT NOT NULL, artifact_key TEXT NOT NULL,
            expires_at TEXT NOT NULL, last_envelope_sha TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(device_id,build_id,artifact_key))""",
        """CREATE TABLE IF NOT EXISTS distribution_envelopes (
            device_id INTEGER NOT NULL, envelope_sha TEXT NOT NULL, build_id TEXT NOT NULL,
            artifact_key TEXT NOT NULL, overlay_revision INTEGER NOT NULL DEFAULT 0,
            ua_class TEXT NOT NULL DEFAULT '', base_url_sha TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, PRIMARY KEY(device_id,envelope_sha))""",
        """CREATE TABLE IF NOT EXISTS deployment_bundles (
            bundle_sha TEXT PRIMARY KEY, build_id TEXT NOT NULL,
            predecessor_sha TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'prepared',
            manifest_json TEXT NOT NULL DEFAULT '{}')""",
        """CREATE TABLE IF NOT EXISTS owner_receipts (
            bundle_sha TEXT NOT NULL REFERENCES deployment_bundles(bundle_sha),
            owner_target TEXT NOT NULL, dns_scope TEXT NOT NULL DEFAULT '',
            expected_revision INTEGER NOT NULL DEFAULT 0, applied_revision INTEGER NOT NULL DEFAULT 0,
            verified_revision INTEGER NOT NULL DEFAULT 0, output_sha TEXT NOT NULL DEFAULT '',
            received_at TEXT NOT NULL, safe_error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(bundle_sha,owner_target,dns_scope))""",
        """CREATE TABLE IF NOT EXISTS resource_gc_queue (
            resource_id TEXT PRIMARY KEY REFERENCES resource_revisions(id),
            marked_at TEXT NOT NULL, not_before TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending')""",
        """CREATE TABLE IF NOT EXISTS release_state (
            env TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
            current_build_id TEXT, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS operation_requests (
            action TEXT NOT NULL, scope TEXT NOT NULL, actor_id INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL, payload_sha TEXT NOT NULL DEFAULT '',
            response_json TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            PRIMARY KEY(action,scope,actor_id,idempotency_key))""",
        """CREATE TABLE IF NOT EXISTS probe_schedule_state (
            kind TEXT NOT NULL, observer_id TEXT NOT NULL, scope TEXT NOT NULL,
            next_due_at TEXT NOT NULL, cursor_json TEXT NOT NULL DEFAULT '{}',
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
            PRIMARY KEY(kind,observer_id,scope))""",
        """CREATE TABLE IF NOT EXISTS probe_recovery_windows (
            window_id TEXT PRIMARY KEY, scope_sha TEXT NOT NULL, kind TEXT NOT NULL,
            confirmation_count INTEGER NOT NULL DEFAULT 0 CHECK(confirmation_count>=0),
            first_at TEXT NOT NULL, last_at TEXT NOT NULL, next_at TEXT,
            expanded_at TEXT, state TEXT NOT NULL DEFAULT 'open',
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1))""",
    )
    for sql in statements:
        conn.execute(sql)
    indexes = (
        'CREATE INDEX IF NOT EXISTS idx_probe_jobs_state_next ON probe_jobs(state,deadline_at)',
        'CREATE INDEX IF NOT EXISTS idx_probe_items_claim ON probe_items(state,next_at,job_id)',
        'CREATE INDEX IF NOT EXISTS idx_probe_results_valid ON probe_results(valid_until)',
        'CREATE INDEX IF NOT EXISTS idx_resource_revisions_logical ON resource_revisions(kind,logical_name,revoked_at)',
        'CREATE INDEX IF NOT EXISTS idx_deployment_bundles_build ON deployment_bundles(build_id,state)',
    )
    for sql in indexes:
        conn.execute(sql)
    _backfill_release_state(conn)
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('v2_recovery_mode','auto_stable_v1')")
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('v2_runtime_activation','staged')")
    conn.execute("INSERT OR REPLACE INTO schema_version(key,value) VALUES('v2_probe_delivery','1')")


def _backfill_release_state(conn) -> None:
    """从现有构建状态回填环境指针；没有历史时保持零版本。"""
    for env, status in (('testing','TESTING'),('production','PRODUCTION')):
        current = conn.execute('SELECT current_build_id FROM release_state WHERE env=?',(env,)).fetchone()
        if current and current['current_build_id'] is not None:
            continue
        row = conn.execute('SELECT id FROM builds WHERE status=? ORDER BY id DESC LIMIT 1',(status,)).fetchone()
        if row:
            now = conn.execute("SELECT datetime('now')").fetchone()[0]
            conn.execute('INSERT INTO release_state(env,revision,current_build_id,updated_at) '
                         'VALUES(?,1,?,?) ON CONFLICT(env) DO UPDATE SET '
                         'current_build_id=excluded.current_build_id,updated_at=excluded.updated_at',
                         (env,str(row['id']),now))
