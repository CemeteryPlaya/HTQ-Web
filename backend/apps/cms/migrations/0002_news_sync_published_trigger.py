# Preserves one piece of FastAPI business logic that isn't yet re-homed at
# the model layer: a Postgres trigger that keeps the legacy `published`
# boolean and `published_at` timestamp in sync with `status` on
# INSERT/UPDATE OF status. Ported from the FastAPI cms-service's alembic
# chain (004_news_taxonomy), rewritten for the idiomatic unqualified
# `public.cms_news` table/function names — no more `cms.` schema prefix.
#
# TODO(News CRUD, Task 1.3, currently skipped): once News has real
# create/update views, move this logic into News.save() or a pre_save
# signal and drop this trigger. It is kept as RunSQL for now only because
# there is nowhere else in the app for it to live yet.

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
