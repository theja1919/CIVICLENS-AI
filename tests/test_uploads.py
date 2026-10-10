"""tests/test_uploads.py — Image upload validation tests."""

from __future__ import annotations
import io

_TINY_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
    0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
    0xFF, 0xD9,
])
_TINY_PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])

_BASE = {
    "category": "garbage",
    "description": "Overflowing garbage bins on the corner of Oak and Elm street",
}


def _post_with_image(client, data_bytes, filename, content_type, **extra):
    data = {**_BASE, **extra}
    data["image"] = (io.BytesIO(data_bytes), filename, content_type)
    return client.post("/reports", data=data, content_type="multipart/form-data")


class TestUploadValidation:
    def test_jpeg_accepted(self, client):
        assert _post_with_image(client, _TINY_JPEG, "photo.jpg", "image/jpeg").status_code == 201

    def test_png_accepted(self, client):
        assert _post_with_image(client, _TINY_PNG, "photo.png", "image/png").status_code == 201

    def test_upload_sets_image_path(self, client):
        rid = _post_with_image(client, _TINY_JPEG, "garbage.jpg", "image/jpeg").get_json()["id"]
        path = client.get(f"/reports/{rid}").get_json()["image_path"]
        assert path is not None
        assert path.startswith("uploads/")

    def test_bad_extension_rejected(self, client):
        assert _post_with_image(client, b"fake", "malware.exe", "image/jpeg").status_code == 422

    def test_bad_mime_type_rejected(self, client):
        assert _post_with_image(client, b"fake", "doc.pdf", "application/pdf").status_code == 422

    def test_oversized_rejected(self, client):
        big = b"X" * (6 * 1024 * 1024)
        assert _post_with_image(client, big, "huge.jpg", "image/jpeg").status_code == 413

    def test_no_image_still_works(self, client):
        r = client.post("/reports",
                        data={"category": "pothole",
                              "description": "Pothole near the community centre entrance"},
                        content_type="multipart/form-data")
        assert r.status_code == 201

    def test_path_traversal_safe(self, client):
        r = _post_with_image(client, _TINY_JPEG, "../../etc/passwd.jpg", "image/jpeg")
        if r.status_code == 201:
            path = client.get(f"/reports/{r.get_json()['id']}").get_json()["image_path"]
            assert ".." not in path
