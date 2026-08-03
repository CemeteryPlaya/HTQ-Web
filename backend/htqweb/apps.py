"""AppConfig проекта — подмена дефолтного AdminSite на брендированный.

``django.contrib.admin`` в INSTALLED_APPS заменён на этот конфиг (см.
``settings/base.py``): Django инстанцирует ``default_site`` как ``admin.site``
ещё до автодискавери ``admin.py``, поэтому все ``@admin.register`` попадают
именно в него. Это штатный механизм — руками ``admin.site`` нигде не
переприсваиваем.
"""
from django.contrib.admin.apps import AdminConfig


class HTQAdminConfig(AdminConfig):
    default_site = "htqweb.admin_site.HTQAdminSite"
