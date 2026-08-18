from sqlalchemy import text

from app.core.database import SessionLocal


with SessionLocal() as db:
    db.execute(
        text(
            """
            INSERT INTO sources (
                type, name, external_id, config, last_cursor,
                auth_secret_ref, is_active
            )
            SELECT
                'api', 'CNRS Webhook', 'cnrs_webhook',
                '{"delivery_method":"webhook"}'::jsonb,
                NULL, 'CNRS_WEBHOOK_SECRET', TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM sources WHERE external_id = 'cnrs_webhook'
            )
            """
        )
    )
    db.commit()
    source = db.execute(
        text(
            "SELECT id, name, external_id, is_active "
            "FROM sources WHERE external_id = 'cnrs_webhook'"
        )
    ).mappings().one()
    print(dict(source))
