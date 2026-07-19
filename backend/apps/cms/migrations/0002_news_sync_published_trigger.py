# Preserves one piece of FastAPI business logic: a Postgres trigger that
# keeps the legacy `published` boolean and `published_at` timestamp in sync
# with `status` on INSERT/UPDATE OF status. Ported from the FastAPI
# cms-service's alembic chain (004_news_taxonomy), rewritten for the
# idiomatic unqualified `public.cms_news` table/function names — no more
# `cms.` schema prefix.
#
# Task 1.3 (News CRUD, apps.cms.services.news_service) deliberately kept
# this trigger rather than folding it into News.save()/a signal — see
# apps/cms/models.py's module docstring and
# news_service.apply_status_side_effects for how the Python-side mirror and
# this trigger stay in sync instead of fighting each other.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE OR REPLACE FUNCTION cms_news_sync_published() RETURNS TRIGGER AS $$\n"
            "BEGIN\n"
            "    NEW.published := (NEW.status = 'published');\n"
            "    IF NEW.status = 'published' AND NEW.published_at IS NULL THEN\n"
            "        NEW.published_at := now();\n"
            "    ELSIF NEW.status <> 'published' THEN\n"
            "        NEW.published_at := NULL;\n"
            "    END IF;\n"
            "    RETURN NEW;\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;\n"
            "DROP TRIGGER IF EXISTS news_sync_published ON cms_news;\n"
            "CREATE TRIGGER news_sync_published\n"
            "BEFORE INSERT OR UPDATE OF status ON cms_news\n"
            "FOR EACH ROW EXECUTE FUNCTION cms_news_sync_published();",
            reverse_sql=
            "DROP TRIGGER IF EXISTS news_sync_published ON cms_news;"
            "DROP FUNCTION IF EXISTS cms_news_sync_published();",
        ),
    ]
