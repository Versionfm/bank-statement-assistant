from pathlib import Path


def test_postgres_initializes_local_path_volume_ownership() -> None:
    manifest = Path("deploy/k8s/base/postgres-statefulset.yaml").read_text(encoding="utf-8")

    assert "name: initialize-postgres-volume-permissions" in manifest
    assert "chown 70:70 /var/lib/postgresql/data" in manifest
    assert "runAsUser: 0" in manifest
    assert "runAsNonRoot: false" in manifest
    assert 'add: ["CHOWN", "FOWNER"]' in manifest
