"""Маршруты ``/api/companies/v1/*``. Монтируются автодискавери по
``CompaniesConfig.API_PREFIX``; ``APPEND_SLASH = False`` — оба написания.

``companies/tree`` стоит ВЫШЕ ``companies/<slug>``: ``<slug:slug>`` матчит и
слово ``tree``.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("me", views.MyCompaniesView.as_view()),
    path("me/", views.MyCompaniesView.as_view()),

    path("companies/tree", views.CompanyTreeView.as_view()),
    path("companies/tree/", views.CompanyTreeView.as_view()),
    path("companies/<slug:slug>/archive", views.CompanyArchiveView.as_view()),
    path("companies/<slug:slug>/archive/", views.CompanyArchiveView.as_view()),
    path("companies/<slug:slug>/restore", views.CompanyRestoreView.as_view()),
    path("companies/<slug:slug>/restore/", views.CompanyRestoreView.as_view()),
    path("companies/<slug:slug>/bankrupt", views.CompanyBankruptView.as_view()),
    path("companies/<slug:slug>/bankrupt/", views.CompanyBankruptView.as_view()),
    path("companies/<slug:slug>/modules/<str:app_label>", views.CompanyModuleItemView.as_view()),
    path("companies/<slug:slug>/modules/<str:app_label>/", views.CompanyModuleItemView.as_view()),
    path("companies/<slug:slug>/modules", views.CompanyModulesView.as_view()),
    path("companies/<slug:slug>/modules/", views.CompanyModulesView.as_view()),
    path("companies/<slug:slug>/memberships/<int:user_id>", views.CompanyMembershipItemView.as_view()),
    path("companies/<slug:slug>/memberships/<int:user_id>/", views.CompanyMembershipItemView.as_view()),
    path("companies/<slug:slug>/memberships", views.CompanyMembershipsView.as_view()),
    path("companies/<slug:slug>/memberships/", views.CompanyMembershipsView.as_view()),
    path("companies/<slug:slug>/external-holders", views.CompanyExternalHoldersView.as_view()),
    path("companies/<slug:slug>/external-holders/", views.CompanyExternalHoldersView.as_view()),
    path("companies/<slug:slug>", views.CompanyItemView.as_view()),
    path("companies/<slug:slug>/", views.CompanyItemView.as_view()),
    path("companies", views.CompanyCollectionView.as_view()),
    path("companies/", views.CompanyCollectionView.as_view()),
]
