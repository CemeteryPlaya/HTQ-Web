"""Модели hr для сводных представлений холдинга. См. apps/tasks/holding.py."""

# StaffingPosition — ради «штата против факта»: численность не с чем
# сравнивать, а это первая цифра, которую спрашивает директор. Цена —
# ещё одно представление и обязательный migrate_companies на выкатке.
HOLDING_MODELS = ("Employee", "Department", "Position", "StaffingPosition")
