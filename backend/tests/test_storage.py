from io import BytesIO
import importlib
import os
import pytest


def storage_module():
    assert importlib.util.find_spec("relay.storage"), "private bounded storage is missing"
    return importlib.import_module("relay.storage")


def test_content_addressed_private_stream_is_immutable(tmp_path):
    module = storage_module()
    store = module.BlobStore(tmp_path)
    blob = store.put_stream(BytesIO(b"first"), mime="text/plain")
    assert blob.sha256 == "a7937b64b8caa58f03721bb6bacf5c78cb235febe0e70b1b84cd99541461a08e"
    assert store.path(blob.key).read_bytes() == b"first"
    assert store.put_stream(BytesIO(b"first"), mime="text/plain").key == blob.key
    assert os.stat(store.path(blob.key)).st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        store.path("../../etc/passwd")


def test_stream_limits_leave_no_partial_file(tmp_path):
    module = storage_module()
    store = module.BlobStore(tmp_path, max_bytes=4)
    with pytest.raises(module.StorageError) as exc:
        store.put_stream(BytesIO(b"12345"), mime="text/plain")
    assert exc.value.status_code == 413
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]
    with pytest.raises(module.StorageError):
        store.put_stream(BytesIO(b""), mime="text/plain")
