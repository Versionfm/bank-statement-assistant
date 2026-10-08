import subprocess


def test_inference_is_private_gpu_backed_and_reproducible() -> None:
    rendered = subprocess.run(
        ["kubectl", "kustomize", "deploy/k8s/inference"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "kind: Deployment" in rendered
    assert "name: vllm" in rendered
    assert "runtimeClassName: nvidia" in rendered
    assert 'nvidia.com/gpu: "1"' in rendered
    assert "Qwen/Qwen3-8B-AWQ" in rendered
    assert "4da05a8edb55c6046cce958586c33b61da07bb79" in rendered
    assert (
        "image: vllm/vllm-openai@sha256:"
        "a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9"
    ) in rendered
    assert "runAsUser: 65534" in rendered
    assert "enableServiceLinks: false" in rendered
    assert "chown 65534:65534 /models" in rendered
    assert "chown -R" not in rendered
    assert "type: ClusterIP" in rendered
    assert "kind: PersistentVolumeClaim" in rendered


def test_inference_uses_bounded_single_sequence_serving() -> None:
    rendered = subprocess.run(
        ["kubectl", "kustomize", "deploy/k8s/inference"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert 'MAX_MODEL_LEN: "8192"' in rendered
    assert 'MAX_NUM_SEQS: "1"' in rendered
    assert 'GPU_MEMORY_UTILIZATION: "0.90"' in rendered
    assert "--enable-prefix-caching" in rendered
    assert "--scheduling-policy priority" in rendered
