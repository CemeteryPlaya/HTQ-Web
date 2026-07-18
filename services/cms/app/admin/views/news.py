"""sqladmin ModelViews for News, Category, Tag."""

from sqladmin import ModelView

from app.models.news import News
from app.models.taxonomy import Category, Tag


class NewsAdmin(ModelView, model=News):
    column_list = [
        News.id,
        News.title,
        News.slug,
        News.status,
        News.category_id,
        News.scheduled_at,
        News.published_at,
        News.updated_at,
    ]
    column_searchable_list = [News.title, News.slug]
    column_sortable_list = [
        News.id,
        News.title,
        News.status,
        News.published_at,
        News.scheduled_at,
        News.created_at,
        News.updated_at,
    ]
    column_default_sort = ("updated_at", True)
    page_size = 25
    name = "News"
    name_plural = "News"
    icon = "fa-solid fa-newspaper"


class CategoryAdmin(ModelView, model=Category):
    column_list = [Category.id, Category.slug, Category.name, Category.created_at]
    column_searchable_list = [Category.slug, Category.name]
    column_sortable_list = [Category.id, Category.name, Category.created_at]
    page_size = 50
    name = "Category"
    name_plural = "Categories"
    icon = "fa-solid fa-folder"


class TagAdmin(ModelView, model=Tag):
    column_list = [Tag.id, Tag.slug, Tag.name, Tag.created_at]
    column_searchable_list = [Tag.slug, Tag.name]
    column_sortable_list = [Tag.id, Tag.name, Tag.created_at]
    page_size = 100
    name = "Tag"
    name_plural = "Tags"
    icon = "fa-solid fa-tag"
