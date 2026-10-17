"""Private immutable, bounded attachment bytes. User filenames never form paths."""

import hashlib
import os
from pathlib import Path
import re
import tempfile

from .workflow_models import StoredBlob

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 5
MAX_REQUEST_BYTES = MAX_FILE_BYTES * MAX_FILES
SUPPORTED_MIMES = frozenset({"text/plain", "text/markdown", "text/csv", "application/pdf"})


class StorageError(ValueError):
    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


class BlobStore:
    def __init__(self, data_dir, *, max_bytes=MAX_FILE_BYTES):
        self.root = Path(data_dir).resolve() / "uploads"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.max_bytes = max_bytes

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid storage key")
        result = self.root / key
        if result.is_symlink():
            raise ValueError("Invalid storage key")
        return result

    def put_stream(self, stream, *, mime):
        if mime not in SUPPORTED_MIMES:
            raise StorageError("Unsupported attachment type.")
        digest, size = hashlib.sha256(), 0
        fd, filename = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        temporary = Path(filename)
        try:
            with os.fdopen(fd, "wb") as output:
                while True:
                    block = stream.read(64 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if size > self.max_bytes:
                        raise StorageError("Attachment exceeds 10 MiB.", 413)
                    digest.update(block)
                    output.write(block)
                if not size:
                    raise StorageError("Attachment is empty.")
                output.flush()
                os.fsync(output.fileno())
            key = digest.hexdigest()
            target = self.path(key)
            # link is an atomic publish-if-absent; never overwrites existing bytes.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if (
                    target.stat().st_size != size
                    or hashlib.sha256(target.read_bytes()).hexdigest() != key
                ):
                    raise StorageError("Stored attachment integrity check failed.", 503)
            return StoredBlob(key=key, sha256=key, byte_size=size, mime=mime)
        finally:
            temporary.unlink(missing_ok=True)
