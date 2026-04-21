from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from yaml import safe_load

REPO_ROOT = Path(__file__).resolve().parents[2]

from apps.manager.config_schema import (  # noqa: E402
    DockerConfig,
    JobsConfig,
    MinioConfig,
    TritonConfig,
    WebsocketConfig,
)
from src.Domains.Models.Actions.AnalyzeModelV2Action import (  # noqa: E402
    AnalyzeModelV2Action,
)
from src.Domains.Models.Actions.GeneratePipelineAction import (  # noqa: E402
    GeneratePipelineAction,
)
from src.Domains.Models.Actions.ScaffoldModelAction import (  # noqa: E402
    ScaffoldModelAction,
)
from src.Domains.Models.Actions.ValidateModelAction import (  # noqa: E402
    ValidateModelAction,
)
from src.Domains.Models.Schemas.ModelAnalysisReport import (  # noqa: E402
    ModelCategory,
)


@dataclass(frozen=True)
class _ScaffoldArgs:
    name: str
    fmt: str
    path: str
    overwrite: bool
    dry_run: bool


@dataclass(frozen=True)
class _AnalyzeArgs:
    miniopath: str
    name: str
    category: str
    fmt: str | None
    dry_run: bool


@dataclass(frozen=True)
class _PipelineArgs:
    name: str
    overwrite: bool
    dry_run: bool


@dataclass(frozen=True)
class _ConfigValidateArgs:
    base_dir: str
    dry_run: bool


@dataclass(frozen=True)
class _ModelValidateArgs:
    name: str
    vm_id: str
    vm_ip: str | None
    container_id: str
    ws_uri: str


def _cmd_manager_test(dry_run: bool) -> int:
    cmd = ["pytest"]
    cwd = REPO_ROOT / "apps" / "manager"
    if dry_run:
        print(f"[dry-run] (cd {cwd}) {' '.join(cmd)}")
        return 0
    return subprocess.call(cmd, cwd=str(cwd))


def _cmd_model_scaffold(args: _ScaffoldArgs) -> int:
    target_root = REPO_ROOT / "infra" / "models" / args.name
    weights_dir = target_root / "1" / "weights"
    dst_weights = weights_dir / f"model{Path(args.path).suffix}"
    dst_config = target_root / "config.pbtxt"

    if args.dry_run:
        print("[dry-run] Scaffold Triton model repository")
        print(f"[dry-run] - name: {args.name}")
        print(f"[dry-run] - format: {args.fmt}")
        print(f"[dry-run] - source: {args.path}")
        print(f"[dry-run] - overwrite: {args.overwrite}")
        print(f"[dry-run] - mkdir -p {weights_dir}")
        print(f"[dry-run] - copy {args.path} -> {dst_weights}")
        print(f"[dry-run] - write {dst_config}")
        return 0

    ScaffoldModelAction(
        repo_root=str(REPO_ROOT),
        name=args.name,
        fmt=args.fmt,  # type: ignore[arg-type]
        source_path=args.path,
        overwrite=args.overwrite,
    ).run()
    return 0


def _cmd_model_analyze(args: _AnalyzeArgs) -> int:
    if args.dry_run:
        print("[dry-run] Analyze model")
        print(f"[dry-run] - miniopath: {args.miniopath}")
        print(f"[dry-run] - name: {args.name}")
        print(f"[dry-run] - category: {args.category}")
        if args.fmt:
            print(f"[dry-run] - format: {args.fmt}")
        return 0

    category = ModelCategory(args.category)
    report = AnalyzeModelV2Action(
        miniopath=args.miniopath,
        name=args.name,
        category=category,
        format=args.fmt,
    ).run()
    print(report.model_dump_json(indent=2))
    return 0


def _cmd_model_pipeline(args: _PipelineArgs) -> int:
    pipeline_name = f"{args.name}_PIPELINE"
    pipeline_root = REPO_ROOT / "infra" / "models" / pipeline_name
    if args.dry_run:
        print("[dry-run] Generate pipeline ensemble")
        print(f"[dry-run] - model: {args.name}")
        print(f"[dry-run] - pipeline: {pipeline_name}")
        print(f"[dry-run] - write: {pipeline_root}/config.pbtxt")
        print("[dry-run] - ensure step models exist:")
        print("[dry-run]   - MINIO_DOWNLOAD_IMG_TO_BYTES")
        print("[dry-run]   - BYTES_TO_UINT8")
        print("[dry-run]   - MINIO_UPLOAD_IMG_BYTES")
        return 0

    GeneratePipelineAction(repo_root=str(REPO_ROOT), name=args.name, overwrite=args.overwrite).run()
    print(f"Pipeline generado: infra/models/{pipeline_name}")
    return 0


def _cmd_manager_dev(dry_run: bool) -> int:
    dev_server = REPO_ROOT / "apps" / "manager" / "dev_server.py"
    if dry_run:
        print(f"[dry-run] {sys.executable} {dev_server}")
        return 0
    return subprocess.call([sys.executable, str(dev_server)])


def _cmd_config_validate(args: _ConfigValidateArgs) -> int:
    base = Path(args.base_dir)
    cfg_dir = base / "config"
    paths = {
        "jobs": cfg_dir / "jobs.yaml",
        "docker": cfg_dir / "docker.yaml",
        "websocket": cfg_dir / "websocket.yaml",
        "triton": cfg_dir / "triton.yaml",
        "minio": cfg_dir / "minio.yaml",
    }

    if args.dry_run:
        print("[dry-run] Validate config YAML with Pydantic schemas")
        for k, p in paths.items():
            print(f"[dry-run] - read {k}: {p}")
        return 0

    def load_yaml(p: Path) -> dict:
        if not p.exists():
            return {}
        with open(p, encoding="utf-8") as f:
            return safe_load(f) or {}

    JobsConfig(**load_yaml(paths["jobs"]))
    DockerConfig(**load_yaml(paths["docker"]))
    WebsocketConfig(**load_yaml(paths["websocket"]))
    TritonConfig(**load_yaml(paths["triton"]))
    MinioConfig(**load_yaml(paths["minio"]))

    print("Configuration is valid ✅")
    return 0


def _cmd_model_validate(args: _ModelValidateArgs) -> int:
    print(
        f"Starting validation for model '{args.name}' against Triton "
        f"(vm_id={args.vm_id}, container_id={args.container_id}, ws_uri={args.ws_uri})..."
    )
    try:
        action = ValidateModelAction(
            repo_root=str(REPO_ROOT),
            model_name=args.name,
            vm_id=args.vm_id,
            vm_ip=args.vm_ip,
            container_id=args.container_id,
            ws_uri=args.ws_uri,
        )
        action.run()
        print(f"Validation completed for model '{args.name}'.")
        return 0
    except Exception as exc:
        print(f"❌ Validation failed for model '{args.name}': {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tcm", description="TCM manager CLI (minimal).")
    sub = parser.add_subparsers(dest="command", required=True)

    manager = sub.add_parser("manager", help="Manager commands")
    manager_sub = manager.add_subparsers(dest="manager_command", required=True)
    test = manager_sub.add_parser("test", help="Run manager tests (pytest)")
    test.add_argument("--dry-run", action="store_true", help="Print actions without executing.")
    dev = manager_sub.add_parser("dev", help="Run manager in development mode")
    dev.add_argument("--dry-run", action="store_true", help="Print actions without executing.")

    config = sub.add_parser("config", help="Config commands")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    validate = config_sub.add_parser("validate", help="Validate apps/manager/config/*.yaml")
    validate.add_argument(
        "--base-dir",
        default=str(REPO_ROOT / "apps" / "manager"),
        help="Base dir containing config/ (default: apps/manager).",
    )
    validate.add_argument("--dry-run", action="store_true", help="Print actions without executing.")

    model = sub.add_parser("model", help="Model tooling commands")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    scaffold = model_sub.add_parser("scaffold", help="Scaffold Triton model structure under infra/models/")
    scaffold.add_argument("--name", required=True)
    scaffold.add_argument("--format", dest="fmt", required=True, help="onnx|safetensors")
    scaffold.add_argument("--path", required=True, help="Path to model file (weights).")
    scaffold.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing weights file.",
    )
    scaffold.add_argument("--dry-run", action="store_true", help="Print actions without executing.")

    analyze = model_sub.add_parser("analyze", help="Analyze a model artifact and print a typed report.")
    analyze.add_argument("--miniopath", required=True, help="s3://bucket/key or local file path")
    analyze.add_argument("--name", required=True, help="Logical model name")
    analyze.add_argument(
        "--category",
        required=True,
        choices=[c.value for c in ModelCategory],
        help="Model category (LLM|ML).",
    )
    analyze.add_argument(
        "--format",
        dest="fmt",
        required=False,
        help="Override format (onnx|safetensors)",
    )
    analyze.add_argument("--dry-run", action="store_true", help="Print actions without executing.")

    pipeline = model_sub.add_parser("pipeline", help="Generate a Triton ensemble pipeline scaffold.")
    pipeline.add_argument("--name", required=True, help="Base model name (must already be scaffolded).")
    pipeline.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing pipeline/step files.",
    )
    pipeline.add_argument("--dry-run", action="store_true", help="Print actions without executing.")

    validate_model = model_sub.add_parser(
        "validate",
        help="Validate that a Triton model is deployed and responds correctly (smoke test).",
    )
    validate_model.add_argument("--name", required=True, help="Logical model name registered in Triton.")
    validate_model.add_argument("--vm-id", required=True, help="VM identifier used for routing.")
    validate_model.add_argument(
        "--vm-ip",
        required=False,
        help=(
            "Optional VM IP for routing. If omitted, the manager may try to derive it "
            "from its Docker cache; providing it makes validation more robust."
        ),
    )
    validate_model.add_argument("--container-id", required=True, help="Container identifier used for routing.")
    validate_model.add_argument(
        "--ws-uri",
        default="ws://127.0.0.1:8000/ws",
        help="WebSocket URI of the manager (default: ws://127.0.0.1:8000/ws).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "manager" and args.manager_command == "test":
        return _cmd_manager_test(dry_run=bool(args.dry_run))

    if args.command == "manager" and args.manager_command == "dev":
        return _cmd_manager_dev(dry_run=bool(args.dry_run))

    if args.command == "config" and args.config_command == "validate":
        return _cmd_config_validate(_ConfigValidateArgs(base_dir=str(args.base_dir), dry_run=bool(args.dry_run)))

    if args.command == "model" and args.model_command == "scaffold":
        scaffold_args = _ScaffoldArgs(
            name=str(args.name),
            fmt=str(args.fmt),
            path=str(args.path),
            overwrite=bool(args.overwrite),
            dry_run=bool(args.dry_run),
        )
        return _cmd_model_scaffold(scaffold_args)

    if args.command == "model" and args.model_command == "analyze":
        analyze_args = _AnalyzeArgs(
            miniopath=str(args.miniopath),
            name=str(args.name),
            category=str(args.category),
            fmt=str(args.fmt) if getattr(args, "fmt", None) else None,
            dry_run=bool(args.dry_run),
        )
        return _cmd_model_analyze(analyze_args)

    if args.command == "model" and args.model_command == "pipeline":
        return _cmd_model_pipeline(
            _PipelineArgs(
                name=str(args.name),
                overwrite=bool(args.overwrite),
                dry_run=bool(args.dry_run),
            )
        )

    if args.command == "model" and args.model_command == "validate":
        return _cmd_model_validate(
            _ModelValidateArgs(
                name=str(args.name),
                vm_id=str(args.vm_id),
                vm_ip=str(args.vm_ip) if getattr(args, "vm_ip", None) else None,
                container_id=str(args.container_id),
                ws_uri=str(args.ws_uri),
            )
        )

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())


def app() -> None:
    """Compatibility shim: allow `tcm = apps.manager.tcm_cli:app` if a Typer-style entrypoint is desired."""
    raise SystemExit(main())
