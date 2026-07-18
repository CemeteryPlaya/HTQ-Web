"""sqladmin ModelView for FileMetadata."""

from sqladmin import ModelView

from app.models.file_metadata import FileMetadata


class FileMetadataAdmin(ModelView, model=FileMetadata):
    column_list = [
        FileMetadata.id,
        FileMetadata.original_filename,
        FileMetadata.mime,
        FileMetadata.size,
        FileMetadata.owner_id,
        FileMetadata.is_public,
        FileMetadata.created_at,
    ]
    column_searchable_list = [FileMetadata.original_filename, FileMetadata.path]
    column_sortable_list = [
        FileMetadata.size,
        FileMetadata.created_at,
    ]
    column_default_sort = ("created_at", True)
    page_size = 50
    name = "File Metadata"
    name_plural = "File Metadata"
    icon = "fa-solid fa-file"
