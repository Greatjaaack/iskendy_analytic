"""Локальное хранилище загруженных файлов (в volume backend, путь из настроек)."""

import os
import uuid

from config import settings

FILES_DIR = settings.files_dir


def ensure_dir() -> None:
    os.makedirs(FILES_DIR, exist_ok=True)


def save_bytes(data: bytes, original_name: str) -> tuple[str, str]:
    """Сохранить файл под уникальным именем. Возвращает (путь, оригинальное имя)."""
    ensure_dir()
    ext = os.path.splitext(original_name)[1]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(FILES_DIR, safe_name)
    with open(path, "wb") as out_file:
        out_file.write(data)
    return path, original_name


def delete_file(path: str) -> None:
    """Удалить файл с диска, молча игнорируя отсутствие (идемпотентно)."""
    try:
        os.remove(path)
    except OSError:
        pass
