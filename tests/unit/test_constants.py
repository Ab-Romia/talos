import pytest

from files.constants import (
    ALLOWED_MIME_TYPES,
    DOCUMENT_MIME_TYPES,
    IMAGE_MIME_TYPES,
    MAX_FILE_SIZE,
    STORAGE_KEY_TEMPLATE,
    THUMBNAIL_SIZE,
)


@pytest.mark.unit
class TestConstants:
    def test_max_file_size_is_50mb(self):
        assert MAX_FILE_SIZE == 50 * 1024 * 1024

    def test_mime_types_subsets(self):
        assert DOCUMENT_MIME_TYPES.issubset(ALLOWED_MIME_TYPES)
        assert IMAGE_MIME_TYPES.issubset(ALLOWED_MIME_TYPES)
        assert DOCUMENT_MIME_TYPES | IMAGE_MIME_TYPES == ALLOWED_MIME_TYPES

    def test_storage_key_template_placeholders(self):
        assert "{workspace_id}" in STORAGE_KEY_TEMPLATE
        assert "{chatroom_id}" in STORAGE_KEY_TEMPLATE
        assert "{file_id}" in STORAGE_KEY_TEMPLATE
        assert "{ext}" in STORAGE_KEY_TEMPLATE

    def test_thumbnail_size(self):
        assert THUMBNAIL_SIZE == (300, 300)
