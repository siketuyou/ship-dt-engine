from __future__ import annotations

import importlib.util
import io
import py_compile
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile

from .deps import PROJECT_ROOT
from fetchers.base_fetcher import BaseFetcher
from fetchers.naming import fetcher_class_name, normalize_fetcher_name


def _normalize_fetcher_name(name: str) -> str:
    return normalize_fetcher_name(name)


def _stage_fetcher(file: UploadFile, fetcher_name: str) -> Path:
    stage_root = PROJECT_ROOT / "fetchers" / "__staging__"
    stage_dir = stage_root / f"{fetcher_name}_{uuid.uuid4().hex}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    content = file.file.read()
    filename = Path(file.filename or f"{fetcher_name}_fetcher.py").name

    if filename.lower().endswith(".zip"):
        _stage_from_zip(content, stage_dir, fetcher_name)
    else:
        _stage_from_py(content, filename, stage_dir, fetcher_name)

    return stage_dir


def _stage_from_py(content: bytes, filename: str, stage_dir: Path, fetcher_name: str) -> None:
    (stage_dir / "__init__.py").write_text("", encoding="utf-8")
    original_dest = stage_dir / filename
    loader_dest = stage_dir / f"{fetcher_name}_fetcher.py"
    original_dest.write_bytes(content)
    if loader_dest != original_dest:
        loader_dest.write_bytes(content)


def _stage_from_zip(content: bytes, stage_dir: Path, fetcher_name: str) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        zf.extractall(stage_dir)
    _flatten_if_needed(stage_dir, fetcher_name)
    if not (stage_dir / "__init__.py").exists():
        (stage_dir / "__init__.py").write_text("", encoding="utf-8")


def _flatten_if_needed(stage_dir: Path, fetcher_name: str) -> None:
    """If the entry point is inside a single subdirectory, move everything up one level."""
    entry_point = f"{fetcher_name}_fetcher.py"
    if (stage_dir / entry_point).exists():
        return
    subdirs = [d for d in stage_dir.iterdir() if d.is_dir() and not d.name.startswith("__")]
    if len(subdirs) == 1 and (subdirs[0] / entry_point).exists():
        for item in list(subdirs[0].iterdir()):
            shutil.move(str(item), str(stage_dir / item.name))
        subdirs[0].rmdir()


def _validate_fetcher(stage_dir: Path, fetcher_name: str) -> None:
    loader_path = stage_dir / f"{fetcher_name}_fetcher.py"
    if not loader_path.exists():
        raise ValueError(f"未生成采集器入口文件: {loader_path.name}")

    py_compile.compile(str(loader_path), doraise=True)

    module_name = f"_fetcher_validation_{fetcher_name}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name, loader_path,
        submodule_search_locations=[str(stage_dir)],
    )
    if spec is None or spec.loader is None:
        raise ValueError("采集器模块无法加载，请检查文件结构")

    # Temporarily add stage_dir to sys.path so intra-package imports resolve.
    sys.path.insert(0, str(stage_dir))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(stage_dir))

    class_name = fetcher_class_name(fetcher_name)
    fetcher_cls = getattr(module, class_name, None)
    if fetcher_cls is None:
        raise ValueError(f"采集器类缺失，期望类名: {class_name}")
    if not isinstance(fetcher_cls, type):
        raise ValueError(f"{class_name} 不是有效类定义")
    if not issubclass(fetcher_cls, BaseFetcher):
        raise ValueError(f"{class_name} 必须继承 BaseFetcher")


def _promote_fetcher(stage_dir: Path, fetcher_name: str) -> str:
    dest_dir = PROJECT_ROOT / "fetchers" / fetcher_name
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.move(str(stage_dir), str(dest_dir))
    return fetcher_name
