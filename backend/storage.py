"""Локальное хранилище загруженных файлов (в volume backend, путь из настроек)."""

import os
import uuid

from config import settings

FILES_DIR = settings.files_dir

# Что вообще имеет смысл прикладывать к поставщику: накладные, прайсы, фото документов.
# Список закрытый — не потому что исполняемый файл сам себя запустит (мы его только
# отдаём обратно), а потому что хранилище не должно превращаться в свалку чего угодно.
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".txt",
}

# Размер читаемого куска при потоковой записи.
CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    """Файл больше разрешённого (`settings.max_upload_mb`)."""


class UploadNotAllowed(Exception):
    """Расширение не из белого списка."""


def ensure_dir() -> None:
    os.makedirs(FILES_DIR, exist_ok=True)


def _safe_target(original_name: str) -> tuple[str, str]:
    """Проверить расширение и вернуть (путь, расширение) под уникальным именем."""
    ext = os.path.splitext(original_name or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadNotAllowed(ext or "без расширения")
    ensure_dir()
    return os.path.join(FILES_DIR, f"{uuid.uuid4().hex}{ext}"), ext


def save_bytes(data: bytes, original_name: str) -> tuple[str, str]:
    """Сохранить готовые байты под уникальным именем. Возвращает (путь, оригинальное имя)."""
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise UploadTooLarge(len(data))
    path, _ = _safe_target(original_name)
    with open(path, "wb") as out_file:
        out_file.write(data)
    return path, original_name


async def save_upload(upload, original_name: str) -> tuple[str, str]:
    """Сохранить загружаемый файл ПОТОКОВО, не держа его целиком в памяти.

    Зачем: у контейнера `mem_limit: 512m`, а прежний код делал `await file.read()` —
    один запрос с большим файлом мог выесть всю память и увести бэкенд в OOM вместе с
    ручкой табло. Теперь читаем кусками и обрываемся на `settings.max_upload_mb`,
    удалив недописанный файл.
    """
    path, _ = _safe_target(original_name)
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with open(path, "wb") as out_file:
            while True:
                chunk = await upload.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise UploadTooLarge(written)
                out_file.write(chunk)
    except BaseException:
        delete_file(path)
        raise
    return path, original_name


def delete_file(path: str) -> None:
    """Удалить файл с диска, молча игнорируя отсутствие (идемпотентно)."""
    try:
        os.remove(path)
    except OSError:
        pass
