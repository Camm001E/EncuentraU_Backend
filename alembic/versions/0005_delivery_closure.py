"""Auditable delivery confirmation and case closure.

Revision ID: 0005_delivery_closure
Revises: 0004_ownership_chat
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_delivery_closure"
down_revision = "0004_ownership_chat"
branch_labels = None
depends_on = None


def backfill():
    # The normal upgrade is additive. No existing report, message or claim is changed.
    if op.get_context().as_sql or op.get_bind().dialect.name == "postgresql":
        op.execute("""
    INSERT INTO deliveries (id, match_id, claim_id, conversation_id, status,
    created_at, updated_at)
    SELECT gen_random_uuid(), c.match_id, c.claim_id, c.id, 'coordinating',
    c.created_at, c.updated_at
    FROM conversations c JOIN ownership_claims cl ON cl.id = c.claim_id
    JOIN object_matches m ON m.id = c.match_id
    WHERE cl.status = 'approved' AND m.status = 'accepted'
    ON CONFLICT (conversation_id) DO NOTHING
""")
        op.execute("""
    INSERT INTO delivery_events (id, delivery_id, actor_user_id, event_type,
    created_at)
    SELECT gen_random_uuid(), d.id, cl.admin_id, 'delivery_created',
    d.created_at
    FROM deliveries d JOIN ownership_claims cl ON cl.id = d.claim_id
    WHERE NOT EXISTS (SELECT 1 FROM delivery_events e WHERE e.delivery_id =
    d.id)
""")
    else:
        from uuid import uuid4

        connection = op.get_bind()
        # SQLite is used only for deterministic unit tests, not normal development data.
        for row in (
            connection.execute(
                sa.text("""
            SELECT c.id, c.match_id, c.claim_id, c.created_at, c.updated_at, cl.admin_id
            FROM conversations c JOIN ownership_claims cl ON cl.id=c.claim_id
            JOIN object_matches m ON m.id=c.match_id
            WHERE cl.status='approved' AND m.status='accepted'
        """)
            )
            .mappings()
            .all()
        ):
            identifier = uuid4().hex
            connection.execute(
                sa.text("""    INSERT INTO deliveries
    (id,match_id,claim_id,conversation_id,status,created_at,updated_at)
    VALUES
    (:id,:match,:claim,:conversation,'coordinating',:created,:updated)"""),
                dict(
                    id=identifier,
                    match=row["match_id"],
                    claim=row["claim_id"],
                    conversation=row["id"],
                    created=row["created_at"],
                    updated=row["updated_at"],
                ),
            )
            connection.execute(
                sa.text("""INSERT INTO delivery_events
                (id,delivery_id,actor_user_id,event_type,created_at)
                VALUES (:id,:delivery,:actor,'delivery_created',:created)"""),
                dict(
                    id=uuid4().hex,
                    delivery=identifier,
                    actor=row["admin_id"],
                    created=row["created_at"],
                ),
            )


def install_guards():
    if not op.get_context().as_sql and op.get_bind().dialect.name != "postgresql":
        op.execute("""CREATE TRIGGER delivery_events_no_update
            BEFORE UPDATE ON delivery_events
            BEGIN SELECT RAISE(ABORT, 'Delivery events are immutable'); END""")
        op.execute("""CREATE TRIGGER delivery_events_no_delete
            BEFORE DELETE ON delivery_events
            BEGIN SELECT RAISE(ABORT, 'Delivery events are immutable'); END""")
        return
    op.execute("""    CREATE FUNCTION enforce_delivery_integrity() RETURNS trigger AS $$
    BEGIN
    IF NOT EXISTS (
    SELECT 1 FROM ownership_claims cl
    JOIN object_matches m ON m.id=cl.match_id
    JOIN conversations c ON c.claim_id=cl.id AND c.match_id=m.id
    WHERE cl.id=NEW.claim_id AND m.id=NEW.match_id AND
    c.id=NEW.conversation_id
    AND cl.status='approved' AND m.status='accepted'
    ) THEN RAISE EXCEPTION 'Invalid approved delivery relationship'; END IF;
    IF TG_OP='UPDATE' THEN
    IF OLD.match_id<>NEW.match_id OR OLD.claim_id<>NEW.claim_id OR
    OLD.conversation_id<>NEW.conversation_id
    THEN RAISE EXCEPTION 'Delivery relationships are immutable'; END IF;
    IF OLD.status='completed' OR (OLD.status<>NEW.status AND NOT (
    (OLD.status='coordinating' AND NEW.status IN
    ('awaiting_confirmations','disputed')) OR
    (OLD.status='awaiting_confirmations' AND NEW.status IN
    ('awaiting_admin','disputed')) OR
    (OLD.status='awaiting_admin' AND NEW.status IN
    ('completed','disputed','coordinating')) OR
    (OLD.status='disputed' AND NEW.status='coordinating')
    )) THEN RAISE EXCEPTION 'Invalid delivery transition'; END IF;
    END IF;
    RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER deliveries_integrity
        BEFORE INSERT OR UPDATE ON deliveries
        FOR EACH ROW EXECUTE FUNCTION enforce_delivery_integrity()""")
    op.execute("""    CREATE FUNCTION immutable_delivery_event() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'Delivery events are immutable'; END; $$ LANGUAGE
    plpgsql""")
    op.execute("""CREATE TRIGGER delivery_events_immutable
        BEFORE UPDATE OR DELETE ON delivery_events
        FOR EACH ROW EXECUTE FUNCTION immutable_delivery_event()""")


def remove_guards():
    if not op.get_context().as_sql and op.get_bind().dialect.name != "postgresql":
        op.execute("DROP TRIGGER IF EXISTS delivery_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS delivery_events_no_delete")
        return
    op.execute("DROP TRIGGER IF EXISTS delivery_events_immutable ON delivery_events")
    op.execute("DROP TRIGGER IF EXISTS deliveries_integrity ON deliveries")
    op.execute("DROP FUNCTION IF EXISTS immutable_delivery_event()")
    op.execute("DROP FUNCTION IF EXISTS enforce_delivery_integrity()")


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "deliveries",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="coordinating",
            nullable=False,
        ),
        sa.Column("claimant_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("custodian_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispute_raised_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("dispute_reason", sa.Text(), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND admin_id IS NOT NULL AND "
            "completed_at IS NOT NULL) OR (status <> 'completed' AND "
            "completed_at IS NULL)",
            name=op.f("ck_deliveries_completion"),
        ),
        sa.CheckConstraint(
            "(status = 'coordinating' AND claimant_confirmed_at IS NULL "
            "AND custodian_confirmed_at IS NULL) OR (status = "
            "'awaiting_confirmations' AND ((claimant_confirmed_at IS NULL "
            "AND custodian_confirmed_at IS NOT NULL) OR "
            "(claimant_confirmed_at IS NOT NULL AND "
            "custodian_confirmed_at IS NULL))) OR (status IN "
            "('awaiting_admin', 'completed') AND claimant_confirmed_at IS "
            "NOT NULL AND custodian_confirmed_at IS NOT NULL) OR status = "
            "'disputed'",
            name=op.f("ck_deliveries_confirmations"),
        ),
        sa.CheckConstraint(
            "(status = 'disputed' AND dispute_raised_by_user_id IS NOT "
            "NULL AND dispute_reason IS NOT NULL AND "
            "length(trim(dispute_reason)) BETWEEN 10 AND 2000) OR (status "
            "<> 'disputed' AND dispute_raised_by_user_id IS NULL AND "
            "dispute_reason IS NULL)",
            name=op.f("ck_deliveries_dispute"),
        ),
        sa.CheckConstraint(
            "status IN ('coordinating', 'awaiting_confirmations', "
            "'awaiting_admin', 'disputed', 'completed')",
            name=op.f("ck_deliveries_status"),
        ),
        sa.CheckConstraint(
            "admin_note IS NULL OR length(trim(admin_note)) BETWEEN 1 AND 2000",
            name=op.f("ck_deliveries_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["users.id"],
            name=op.f("fk_deliveries_admin_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "match_id"],
            ["ownership_claims.id", "ownership_claims.match_id"],
            name="fk_deliveries_claim_match",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_deliveries_conversation_id_conversations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dispute_raised_by_user_id"],
            ["users.id"],
            name=op.f("fk_deliveries_dispute_raised_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["object_matches.id"],
            name=op.f("fk_deliveries_match_id_object_matches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deliveries")),
        sa.UniqueConstraint("claim_id", name=op.f("uq_deliveries_claim_id")),
        sa.UniqueConstraint(
            "conversation_id", name=op.f("uq_deliveries_conversation_id")
        ),
        sa.UniqueConstraint("match_id", name=op.f("uq_deliveries_match_id")),
    )
    op.create_index(
        "ix_deliveries_created_at", "deliveries", ["created_at"], unique=False
    )
    op.create_index(
        "ix_deliveries_status_created_at",
        "deliveries",
        ["status", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "delivery_events",
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('delivery_created', 'custodian_confirmed', "
            "'claimant_confirmed', 'dispute_opened', 'admin_reopened', "
            "'admin_completed')",
            name=op.f("ck_delivery_events_event_type"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(trim(note)) BETWEEN 1 AND 2000",
            name=op.f("ck_delivery_events_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_delivery_events_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["deliveries.id"],
            name=op.f("fk_delivery_events_delivery_id_deliveries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_events")),
    )
    op.create_index(
        "ix_delivery_events_delivery_created_id",
        "delivery_events",
        ["delivery_id", "created_at", "id"],
        unique=False,
    )
    # ### end Alembic commands ###
    backfill()
    install_guards()


def downgrade():
    remove_guards()
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "ix_delivery_events_delivery_created_id", table_name="delivery_events"
    )
    op.drop_table("delivery_events")
    op.drop_index("ix_deliveries_status_created_at", table_name="deliveries")
    op.drop_index("ix_deliveries_created_at", table_name="deliveries")
    op.drop_table("deliveries")
    # ### end Alembic commands ###
