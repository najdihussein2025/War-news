"""Analytics foundation: admin areas, action families, archive, fact tables, dirty-date triggers.

Self-contained on purpose (no imports from app services).

Revision ID: 20261021_0082
Revises: 20261019_0081
"""

from alembic import op


revision = "20261021_0082"
down_revision = "20261019_0081"
branch_labels = None
depends_on = None


MARK_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_mark_dirty(p_kind text, p_date date) RETURNS void AS $$
BEGIN
    IF p_date IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO analytics_dirty_dates (kind, event_date, marked_at)
    VALUES (p_kind, p_date, clock_timestamp())
    ON CONFLICT (kind, event_date) DO UPDATE SET marked_at = clock_timestamp();
END;
$$ LANGUAGE plpgsql
"""

# Marks date - 1, date, date + 1: breach windows can cross midnight.
MARK_AIR_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_mark_air_dirty(p_date date) RETURNS void AS $$
BEGIN
    IF p_date IS NULL THEN
        RETURN;
    END IF;
    PERFORM analytics_mark_dirty('air', p_date - 1);
    PERFORM analytics_mark_dirty('air', p_date);
    PERFORM analytics_mark_dirty('air', p_date + 1);
END;
$$ LANGUAGE plpgsql
"""

INCIDENTS_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_incidents_mark() RETURNS trigger AS $$
BEGIN
    IF current_setting('analytics.skip_dirty_marks', true) = 'on' THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'INSERT' THEN
        PERFORM analytics_mark_dirty('incident', NEW.event_date);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM analytics_mark_dirty('incident', OLD.event_date);
    ELSIF (
        NEW.event_date IS DISTINCT FROM OLD.event_date
        OR NEW.village_id IS DISTINCT FROM OLD.village_id
        OR NEW.condition_id IS DISTINCT FROM OLD.condition_id
        OR NEW.verification_status IS DISTINCT FROM OLD.verification_status
        OR NEW.is_deleted IS DISTINCT FROM OLD.is_deleted
        OR NEW.total_deaths IS DISTINCT FROM OLD.total_deaths
        OR NEW.total_injuries IS DISTINCT FROM OLD.total_injuries
        OR NEW.casualty_status IS DISTINCT FROM OLD.casualty_status
    ) THEN
        PERFORM analytics_mark_dirty('incident', OLD.event_date);
        PERFORM analytics_mark_dirty('incident', NEW.event_date);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

DETAILS_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_incident_details_mark() RETURNS trigger AS $$
DECLARE
    v_date date;
BEGIN
    IF current_setting('analytics.skip_dirty_marks', true) = 'on' THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'DELETE' THEN
        SELECT event_date INTO v_date FROM incidents WHERE id = OLD.incident_id;
        PERFORM analytics_mark_dirty('incident', v_date);
    ELSIF TG_OP = 'INSERT' THEN
        SELECT event_date INTO v_date FROM incidents WHERE id = NEW.incident_id;
        PERFORM analytics_mark_dirty('incident', v_date);
    ELSIF (
        NEW.male_d IS DISTINCT FROM OLD.male_d
        OR NEW.male_i IS DISTINCT FROM OLD.male_i
        OR NEW.female_d IS DISTINCT FROM OLD.female_d
        OR NEW.female_i IS DISTINCT FROM OLD.female_i
        OR NEW.children_d IS DISTINCT FROM OLD.children_d
        OR NEW.children_i IS DISTINCT FROM OLD.children_i
    ) THEN
        SELECT event_date INTO v_date FROM incidents WHERE id = NEW.incident_id;
        PERFORM analytics_mark_dirty('incident', v_date);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

GROUPS_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_bulletin_groups_mark() RETURNS trigger AS $$
DECLARE
    v_row record;
BEGIN
    IF current_setting('analytics.skip_dirty_marks', true) = 'on' THEN
        RETURN NULL;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        FOR v_row IN
            SELECT DISTINCT i.event_date
            FROM incidents i
            WHERE i.id = OLD.owner_incident_id
               OR i.id IN (SELECT m.incident_id FROM bulletin_casualty_group_members m WHERE m.group_id = OLD.id)
        LOOP
            PERFORM analytics_mark_dirty('incident', v_row.event_date);
        END LOOP;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        FOR v_row IN
            SELECT DISTINCT i.event_date
            FROM incidents i
            WHERE i.id = NEW.owner_incident_id
               OR i.id IN (SELECT m.incident_id FROM bulletin_casualty_group_members m WHERE m.group_id = NEW.id)
        LOOP
            PERFORM analytics_mark_dirty('incident', v_row.event_date);
        END LOOP;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

GROUP_MEMBERS_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_bulletin_group_members_mark() RETURNS trigger AS $$
DECLARE
    v_date date;
BEGIN
    IF current_setting('analytics.skip_dirty_marks', true) = 'on' THEN
        RETURN NULL;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT event_date INTO v_date FROM incidents WHERE id = OLD.incident_id;
        PERFORM analytics_mark_dirty('incident', v_date);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT event_date INTO v_date FROM incidents WHERE id = NEW.incident_id;
        PERFORM analytics_mark_dirty('incident', v_date);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

AIR_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_air_violations_mark() RETURNS trigger AS $$
BEGIN
    IF current_setting('analytics.skip_dirty_marks', true) = 'on' THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'INSERT' THEN
        PERFORM analytics_mark_air_dirty(NEW.event_date);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM analytics_mark_air_dirty(OLD.event_date);
    ELSIF (
        NEW.event_date IS DISTINCT FROM OLD.event_date
        OR NEW.event_time IS DISTINCT FROM OLD.event_time
        OR NEW.condition_id IS DISTINCT FROM OLD.condition_id
        OR NEW.village_id IS DISTINCT FROM OLD.village_id
        OR NEW.caza_en IS DISTINCT FROM OLD.caza_en
        OR NEW.caza_ar IS DISTINCT FROM OLD.caza_ar
    ) THEN
        PERFORM analytics_mark_air_dirty(OLD.event_date);
        PERFORM analytics_mark_air_dirty(NEW.event_date);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

AIR_LOCATIONS_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION analytics_air_locations_mark() RETURNS trigger AS $$
DECLARE
    v_date date;
BEGIN
    IF current_setting('analytics.skip_dirty_marks', true) = 'on' THEN
        RETURN NULL;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT event_date INTO v_date FROM air_violations WHERE id = OLD.air_violation_id;
        PERFORM analytics_mark_air_dirty(v_date);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT event_date INTO v_date FROM air_violations WHERE id = NEW.air_violation_id;
        PERFORM analytics_mark_air_dirty(v_date);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

TRIGGERS = (
    ("trg_analytics_incidents_mark", "incidents", "analytics_incidents_mark"),
    ("trg_analytics_incident_details_mark", "incident_details", "analytics_incident_details_mark"),
    ("trg_analytics_bulletin_groups_mark", "bulletin_casualty_groups", "analytics_bulletin_groups_mark"),
    (
        "trg_analytics_bulletin_group_members_mark",
        "bulletin_casualty_group_members",
        "analytics_bulletin_group_members_mark",
    ),
    ("trg_analytics_air_violations_mark", "air_violations", "analytics_air_violations_mark"),
    ("trg_analytics_air_locations_mark", "air_violation_locations", "analytics_air_locations_mark"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE admin_areas (
            code text PRIMARY KEY,
            level text NOT NULL CONSTRAINT ck_admin_areas_level
                CHECK (level IN ('mohafaza', 'caza', 'village')),
            name_en text,
            name_ar text,
            parent_code text REFERENCES admin_areas (code),
            caza_code text,
            mohafaza_code text,
            area_km2 numeric,
            center_lat double precision,
            center_lon double precision,
            is_disputed boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_admin_areas_level ON admin_areas (level)")
    op.execute("CREATE INDEX ix_admin_areas_caza_code ON admin_areas (caza_code)")
    op.execute("CREATE INDEX ix_admin_areas_mohafaza_code ON admin_areas (mohafaza_code)")

    op.execute(
        "ALTER TABLE villages ADD COLUMN admin_area_code text "
        "REFERENCES admin_areas (code) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_villages_admin_area_code ON villages (admin_area_code)")

    op.execute(
        """
        CREATE TABLE action_families (
            id serial PRIMARY KEY,
            code text NOT NULL UNIQUE,
            name_en text NOT NULL,
            name_ar text NOT NULL,
            sort_order integer NOT NULL DEFAULT 0,
            is_air_violation boolean NOT NULL DEFAULT false,
            counts_in_headline boolean NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        """
        CREATE TABLE condition_families (
            condition_id integer PRIMARY KEY REFERENCES conditions (id) ON DELETE CASCADE,
            family_id integer NOT NULL REFERENCES action_families (id) ON DELETE RESTRICT
        )
        """
    )

    op.execute(
        """
        CREATE TABLE incidents_archive (
            archive_batch text NOT NULL,
            id uuid NOT NULL,
            archived_at timestamptz NOT NULL DEFAULT now(),
            raw_message_id bigint,
            village_id integer,
            village_display_name varchar,
            condition_id integer,
            source_id bigint,
            event_month varchar,
            event_date date NOT NULL,
            event_time time,
            khabar text NOT NULL,
            story_group_id uuid,
            note text,
            moh varchar,
            martyrs text,
            worker_name varchar,
            source_link text,
            source_link_2 text,
            total_deaths integer,
            total_injuries integer,
            casualty_status varchar(24),
            casualty_deaths_status varchar(24),
            casualty_injuries_status varchar(24),
            casualty_status_remaining_total jsonb,
            quality_flags jsonb,
            casualty_is_preliminary boolean,
            casualty_status_evidence text,
            deaths integer,
            injuries integer,
            injuries_extra integer,
            note_extra text,
            note_extra_2 text,
            exact_hash char(64),
            incident_key varchar,
            duplicate_flag boolean NOT NULL DEFAULT false,
            duplicate_level varchar(16),
            duplicate_similarity_score double precision,
            details_pending boolean NOT NULL DEFAULT false,
            is_deleted boolean NOT NULL DEFAULT false,
            deleted_reason varchar(32),
            decision_reason varchar(64),
            decision_source_summary_id bigint,
            decision_ref_incident_id uuid,
            decided_at timestamptz,
            created_by uuid,
            created_at timestamptz,
            updated_at timestamptz,
            origin varchar,
            source_summary_item_id bigint,
            verification_status varchar(24) NOT NULL,
            verification_reason text,
            verified_by_user_id uuid,
            verified_at timestamptz,
            version integer,
            locked_by_user_id uuid,
            edit_lock_expires_at timestamptz,
            male_d integer,
            male_i integer,
            female_d integer,
            female_i integer,
            children_d integer,
            children_i integer,
            bulletin_casualty_group_id bigint,
            casualty_scope varchar,
            PRIMARY KEY (archive_batch, id)
        )
        """
    )
    op.execute("CREATE INDEX ix_incidents_archive_event_date ON incidents_archive (event_date)")
    op.execute("CREATE INDEX ix_incidents_archive_village_id ON incidents_archive (village_id)")
    op.execute("CREATE INDEX ix_incidents_archive_condition_id ON incidents_archive (condition_id)")
    op.execute("CREATE INDEX ix_incidents_archive_id ON incidents_archive (id)")

    op.execute(
        """
        CREATE TABLE analytics_incident_facts (
            id bigserial PRIMARY KEY,
            event_date date NOT NULL,
            admin_village_code text,
            caza_code text,
            mohafaza_code text,
            village_id integer,
            condition_id integer NOT NULL,
            family_id integer NOT NULL,
            bucket text NOT NULL CONSTRAINT ck_analytics_incident_facts_bucket
                CHECK (bucket IN ('counted', 'pending')),
            source text NOT NULL CONSTRAINT ck_analytics_incident_facts_source
                CHECK (source IN ('live', 'archive')),
            archive_batch text,
            incidents integer NOT NULL DEFAULT 0,
            deaths_total integer NOT NULL DEFAULT 0,
            deaths_male integer NOT NULL DEFAULT 0,
            deaths_female integer NOT NULL DEFAULT 0,
            deaths_children integer NOT NULL DEFAULT 0,
            deaths_unspecified integer NOT NULL DEFAULT 0,
            injuries_total integer NOT NULL DEFAULT 0,
            injuries_male integer NOT NULL DEFAULT 0,
            injuries_female integer NOT NULL DEFAULT 0,
            injuries_children integer NOT NULL DEFAULT 0,
            injuries_unspecified integer NOT NULL DEFAULT 0,
            aggregate_only_incidents integer NOT NULL DEFAULT 0,
            refreshed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_analytics_incident_facts_grain
                UNIQUE NULLS NOT DISTINCT (event_date, village_id, condition_id, bucket, source)
        )
        """
    )
    op.execute("CREATE INDEX ix_analytics_incident_facts_date ON analytics_incident_facts (event_date)")
    op.execute(
        "CREATE INDEX ix_analytics_incident_facts_moh_date "
        "ON analytics_incident_facts (mohafaza_code, event_date)"
    )
    op.execute(
        "CREATE INDEX ix_analytics_incident_facts_caza_date "
        "ON analytics_incident_facts (caza_code, event_date)"
    )
    op.execute(
        "CREATE INDEX ix_analytics_incident_facts_village_date "
        "ON analytics_incident_facts (admin_village_code, event_date)"
    )
    op.execute(
        "CREATE INDEX ix_analytics_incident_facts_family_date "
        "ON analytics_incident_facts (family_id, event_date)"
    )

    op.execute(
        """
        CREATE TABLE analytics_air_breach_facts (
            id bigserial PRIMARY KEY,
            breach_date date NOT NULL,
            condition_id integer NOT NULL,
            family_id integer NOT NULL,
            unit_level text NOT NULL CONSTRAINT ck_analytics_air_breach_facts_level
                CHECK (unit_level IN ('mohafaza', 'caza', 'village', 'unknown')),
            area_code text,
            mohafaza_code text,
            caza_code text,
            breaches integer NOT NULL DEFAULT 0,
            reports integer NOT NULL DEFAULT 0,
            needs_review_breaches integer NOT NULL DEFAULT 0,
            refreshed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_analytics_air_breach_facts_grain
                UNIQUE NULLS NOT DISTINCT (breach_date, condition_id, unit_level, area_code)
        )
        """
    )
    op.execute("CREATE INDEX ix_analytics_air_breach_facts_date ON analytics_air_breach_facts (breach_date)")
    op.execute(
        "CREATE INDEX ix_analytics_air_breach_facts_unit "
        "ON analytics_air_breach_facts (unit_level, area_code)"
    )

    op.execute(
        """
        CREATE TABLE analytics_dirty_dates (
            kind text NOT NULL CONSTRAINT ck_analytics_dirty_dates_kind
                CHECK (kind IN ('incident', 'air')),
            event_date date NOT NULL,
            marked_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (kind, event_date)
        )
        """
    )

    for statement in (
        MARK_FUNCTION,
        MARK_AIR_FUNCTION,
        INCIDENTS_TRIGGER_FUNCTION,
        DETAILS_TRIGGER_FUNCTION,
        GROUPS_TRIGGER_FUNCTION,
        GROUP_MEMBERS_TRIGGER_FUNCTION,
        AIR_TRIGGER_FUNCTION,
        AIR_LOCATIONS_TRIGGER_FUNCTION,
    ):
        op.execute(statement)
    for name, table, function in TRIGGERS:
        op.execute(
            f"CREATE TRIGGER {name} AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )


def downgrade() -> None:
    for name, table, _function in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    for function in (
        "analytics_air_locations_mark()",
        "analytics_air_violations_mark()",
        "analytics_bulletin_group_members_mark()",
        "analytics_bulletin_groups_mark()",
        "analytics_incident_details_mark()",
        "analytics_incidents_mark()",
        "analytics_mark_air_dirty(date)",
        "analytics_mark_dirty(text, date)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TABLE IF EXISTS analytics_dirty_dates")
    op.execute("DROP TABLE IF EXISTS analytics_air_breach_facts")
    op.execute("DROP TABLE IF EXISTS analytics_incident_facts")
    op.execute("DROP TABLE IF EXISTS incidents_archive")
    op.execute("DROP TABLE IF EXISTS condition_families")
    op.execute("DROP TABLE IF EXISTS action_families")
    op.execute("DROP INDEX IF EXISTS ix_villages_admin_area_code")
    op.execute("ALTER TABLE villages DROP COLUMN IF EXISTS admin_area_code")
    op.execute("DROP TABLE IF EXISTS admin_areas")
