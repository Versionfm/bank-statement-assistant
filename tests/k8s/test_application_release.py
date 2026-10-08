import re
import subprocess
from pathlib import Path


def _run(*args: str) -> str:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_release_image_reference_is_stable_and_source_fingerprinted() -> None:
    first = _run("bash", "scripts/release-image-ref.sh")
    second = _run("bash", "scripts/release-image-ref.sh")

    assert first == second
    assert re.fullmatch(r"bank-statement-assistant:bsa-[0-9a-f]{12}", first)


def test_release_renderer_injects_one_immutable_image_into_every_application_workload() -> None:
    image = f"bank-statement-assistant:sha-{'a' * 64}"

    application = _run("bash", "scripts/render-k3s-release.sh", "application", image)
    migration = _run("bash", "scripts/render-k3s-release.sh", "migration", image)

    assert application.count(f"image: {image}") == 3
    assert f"image: {image}" in migration
    assert "RELEASE_IMAGE" not in application
    assert "RELEASE_IMAGE" not in migration
    assert "bank-statement-assistant:local" not in application
    assert "bank-statement-assistant:local" not in migration


def test_release_renderer_rejects_a_mutable_or_malformed_image_reference() -> None:
    result = subprocess.run(
        ["bash", "scripts/render-k3s-release.sh", "application", "bank-statement-assistant:local"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "immutable release image" in result.stderr


def test_deployment_verifies_the_imported_and_running_image_identity() -> None:
    source = Path("scripts/deploy-k3s.sh").read_text(encoding="utf-8")

    assert "k3s ctr images inspect" in source
    assert ".status.containerStatuses[0].imageID" in source
    assert "extract_image_digest" in source
    assert "docker image inspect" in source


def test_worker_readiness_probe_allows_database_check_to_complete() -> None:
    manifest = Path("deploy/k8s/application/worker-deployment.yaml").read_text(encoding="utf-8")

    assert 'command: ["bsa-schema-ready"]' in manifest
    assert "timeoutSeconds: 5" in manifest


def test_stop_script_requires_explicit_mode_and_confirmation() -> None:
    source = Path("scripts/stop-k3s.sh").read_text(encoding="utf-8")

    assert "--services|--cluster" in source
    assert "--confirm" in source
    assert "kubectl scale deployment/web deployment/worker deployment/vllm" in source
    assert "sudo systemctl stop k3s" in source
    assert "kubectl delete" not in source
    assert "kubectl delete pvc" not in source.lower()
