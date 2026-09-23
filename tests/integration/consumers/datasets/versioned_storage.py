"""Exercise actual local lakeFS commits using retained synthetic research inputs."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import os
import sys
from http.client import HTTPResponse
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

# third party library imports
import msgspec
from lakefs_sdk import ApiClient, Configuration

# project library imports
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryReader
from market_data.storage import DatasetVersion, LakeFSStorage, RawStore, VersionedObject
from research.experiments import AttemptStore
from research.studies import BacktestRun, ResearchInputs
from serialization import DomainCodec


class _Service:
    """Own explicit local administrative setup without retaining private credentials."""

    def __init__(self, endpoint: str, credentials: Path) -> None:
        """Read only the specifically selected private local-test credentials."""
        fields = msgspec.json.decode(credentials.read_bytes(), type=dict[str, msgspec.Raw])
        self.access = msgspec.json.decode(fields["access_key_id"], type=str)
        self.secret = msgspec.json.decode(fields["secret_access_key"], type=str)
        self.endpoint = endpoint

    def request(
        self,
        method: str,
        path: str,
        payload: bytes | None = None,
        *,
        content_type: str = "application/json",
    ) -> bytes:
        """Send a bounded local service request without logging authorization headers."""
        request = Request(
            self.endpoint + path,
            data=payload,
            method=method,
            headers={
                "Authorization": "Basic "
                + base64.b64encode(f"{self.access}:{self.secret}".encode()).decode(),
                "Content-Type": content_type,
            },
        )
        response: object = urlopen(request, timeout=20)
        if not isinstance(response, HTTPResponse):
            raise TypeError("expected local HTTP response")
        with response:
            return response.read(10_000_000)

    def upload(self, repository: str, branch: str, path: str, payload: bytes) -> None:
        """Upload exact bytes to an explicit disposable test branch."""
        boundary = "research-" + uuid4().hex
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="content"; filename="object"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + payload
            + f"\r\n--{boundary}--\r\n".encode()
        )
        self.request(
            "POST",
            f"/repositories/{repository}/branches/{branch}/objects?path={quote(path)}",
            body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def commit(self, repository: str, branch: str, message: str) -> str:
        """Commit the explicit branch and return its immutable storage identity."""
        fields = msgspec.json.decode(
            self.request(
                "POST",
                f"/repositories/{repository}/branches/{branch}/commits",
                DomainCodec().encode_json({"message": message}),
            ),
            type=dict[str, msgspec.Raw],
        )
        return msgspec.json.decode(fields["id"], type=str)


def main() -> None:
    """Reopen exact dataset/feature bytes before and after a new-branch correction.

    Raises:
        AssertionError: Version pinning, digest verification or reader semantics changed.
    """
    source, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    codec = DomainCodec()
    service = _Service(
        os.environ.get("ALPHA_LAKEFS_ENDPOINT", "http://127.0.0.1:18000/api/v1"),
        Path(os.environ["ALPHA_LAKEFS_CREDENTIALS"]),
    )
    client = ApiClient(
        Configuration(host=service.endpoint, username=service.access, password=service.secret)
    )
    try:
        storage = LakeFSStorage(client)
        if len(sys.argv) > 3:
            version = codec.decode_json((output / "version.json").read_bytes(), DatasetVersion)
            storage.materialize(version, output / sys.argv[3], max_bytes=10_000_000)
            if len(sys.argv) > 4 and sys.argv[4] == "verify-collection":
                fields = msgspec.json.decode(
                    (output / "repository.json").read_bytes(), type=dict[str, str]
                )
                try:
                    service.request(
                        "GET",
                        f"/repositories/{fields['repository']}/refs/{fields['discarded']}"
                        "/objects?path=features/disposable.json",
                    )
                except HTTPError as error:
                    assert error.code == 410
                else:
                    raise AssertionError("expired disposable object survived collection")
                print("Expired control returns HTTP 410; retained bytes survived collection")
            print("Reopened retained version", version.commit_id)
            return
        selected = BacktestRun.read(source / "configured.json")
        reader = QueryReader.read(
            source / "snapshots",
            RawStore(source / "raw"),
            readers=SourceAdapters(),
            identity=selected.snapshot_id,
            precedence=(selected.economics.binding,),
            max_bytes=2_000_000,
        )
        features = codec.encode_json(ResearchInputs.collect(selected, reader).features)
        repository = "research-" + uuid4().hex[:16]
        service.request(
            "POST",
            "/repositories",
            DomainCodec().encode_json(
                {
                    "name": repository,
                    "storage_namespace": os.environ.get("ALPHA_LAKEFS_NAMESPACE", "local://")
                    + repository,
                    "default_branch": "main",
                }
            ),
        )
        paths = tuple(
            sorted(
                p
                for name in ("raw", "snapshots")
                for p in (source / name).rglob("*")
                if p.is_file()
            )
        )
        objects: list[VersionedObject] = []
        payloads = {str(path.relative_to(source)): path.read_bytes() for path in paths}
        payloads["features/diagnostics.json"] = features
        for path, payload in sorted(payloads.items()):
            service.upload(repository, "main", path, payload)
            objects.append(
                VersionedObject(
                    path=path, sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload)
                )
            )
        commit = service.commit(
            repository, "main", "Retain published synthetic dataset and causal features"
        )
        version = storage.resolve(repository, "main", kind="branch", objects=tuple(objects))
        assert version.commit_id == commit
        (output / "version.json").write_bytes(codec.encode_json(version))
        service.request(
            "POST",
            f"/repositories/{repository}/tags",
            DomainCodec().encode_json({"id": "retained-research", "ref": commit}),
        )
        assert (
            storage.resolve(repository, "retained-research", kind="tag", objects=tuple(objects))
            == version
        )
        service.request(
            "POST",
            f"/repositories/{repository}/branches",
            DomainCodec().encode_json({"name": "correction", "source": commit}),
        )
        service.upload(repository, "correction", "features/diagnostics.json", b"[]")
        corrected = service.commit(
            repository, "correction", "Alter a new branch without rewriting pinned history"
        )
        assert corrected != commit
        storage.materialize(version, output / "reopened", max_bytes=10_000_000)
        reopened = QueryReader.read(
            output / "reopened/snapshots",
            RawStore(output / "reopened/raw"),
            readers=SourceAdapters(),
            identity=selected.snapshot_id,
            precedence=(selected.economics.binding,),
            max_bytes=2_000_000,
        )
        assert codec.encode_json(ResearchInputs.collect(selected, reopened).features) == features
        assert (output / "reopened/features/diagnostics.json").read_bytes() == features
        try:
            storage.resolve(repository, "correction", kind="branch", objects=tuple(objects))
        except ValueError:
            pass
        else:
            raise AssertionError("changed feature bytes satisfied the pinned manifest")
        # A retained branch keeps referenced objects alive; commit timestamps never
        # replace the market events' embedded availability clocks.
        service.request(
            "POST",
            f"/repositories/{repository}/branches",
            DomainCodec().encode_json({"name": "retained", "source": commit}),
        )
        service.request(
            "PUT",
            f"/repositories/{repository}/settings/gc_rules",
            DomainCodec().encode_json(
                {
                    "default_retention_days": 0,
                    "branches": [{"branch_id": "retained", "retention_days": 365}],
                }
            ),
        )
        service.upload(repository, "main", "features/disposable.json", b'{"retire":true}')
        discarded = service.commit(repository, "main", "Commit a disposable collector control")
        service.request(
            "DELETE",
            f"/repositories/{repository}/branches/main/objects?path=features/disposable.json",
        )
        service.commit(repository, "main", "Retire the unreferenced collector control")
        (output / "repository.json").write_bytes(
            DomainCodec().encode_json(
                {
                    "repository": repository,
                    "commit": commit,
                    "correction": corrected,
                    "discarded": discarded,
                }
            )
        )
        assert AttemptStore(source / "configured-attempts").histories()
        print("Verified lakeFS dataset/feature pin and correction isolation:", commit)
    finally:
        client.close()


if __name__ == "__main__":
    main()
