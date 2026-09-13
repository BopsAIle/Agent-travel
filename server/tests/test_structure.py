"""Khoá lại các ranh giới kiến trúc sau khi tái cấu trúc.

Mục đích không phải kiểm tra logic nghiệp vụ, mà là làm cho việc trôi ngược lại
cấu trúc phẳng cũ bị báo lỗi ngay: mọi module phải import được, phụ thuộc phải
đi đúng một chiều, và chỉ config.py được đọc biến môi trường.
"""
import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = SERVER_ROOT / "app"


def app_modules():
    return sorted(
        m.name for m in pkgutil.walk_packages([str(APP_ROOT)], prefix="app.")
    )


def python_files():
    return sorted(
        p for p in APP_ROOT.rglob("*.py") if "__pycache__" not in p.parts
    )


def imported_modules(path):
    """Các module mà file này import (chỉ lấy dạng `from X import ...` / `import X`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
    return out


@pytest.mark.parametrize("name", app_modules())
def test_moi_module_import_duoc(name):
    importlib.import_module(name)


# Tầng dưới không được biết tầng trên. api -> graph -> domain -> core/db/memory.
CAM = {
    "app/core": ("app.api", "app.graph", "app.domain"),
    "app/domain": ("app.api", "app.graph"),
    "app/graph": ("app.api",),
    "app/schemas": ("app.api", "app.graph", "app.domain", "app.core", "app.db", "app.memory"),
}


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p))
def test_phu_thuoc_dung_mot_chieu(path):
    rel = path.relative_to(SERVER_ROOT).as_posix()
    tang = next((t for t in CAM if rel.startswith(t + "/")), None)
    if tang is None:
        return
    vi_pham = [
        mod
        for mod in imported_modules(path)
        for cam in CAM[tang]
        if mod == cam or mod.startswith(cam + ".")
    ]
    assert not vi_pham, f"{rel} import ngược lên tầng trên: {sorted(set(vi_pham))}"


def test_chi_config_doc_bien_moi_truong():
    """os.getenv / load_dotenv chỉ được xuất hiện trong app/core/config.py."""
    pham_quy = []
    for path in python_files():
        if path.name == "config.py" and path.parent.name == "core":
            continue
        src = path.read_text(encoding="utf-8")
        for token in ("os.getenv(", "os.environ", "load_dotenv("):
            if token in src:
                pham_quy.append(f"{path.relative_to(SERVER_ROOT).as_posix()}: {token}")
    assert not pham_quy, "Đọc env ngoài app/core/config.py:\n" + "\n".join(pham_quy)


def test_moi_node_nam_o_file_rieng():
    """Mỗi node của graph phải ở một module riêng dưới app/graph/nodes/."""
    from app.graph import nodes

    for ten in nodes.__all__:
        if ten.isupper():
            continue
        ham = getattr(nodes, ten)
        assert ham.__module__.startswith("app.graph.nodes."), (
            f"{ten} đang nằm ở {ham.__module__}"
        )


def test_khong_con_url_microservice_hardcode():
    """Địa chỉ service phải lấy từ config để đổi được qua biến môi trường."""
    pham_quy = []
    for path in python_files():
        if path.name == "config.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if '"http://' in line or "'http://" in line:
                pham_quy.append(f"{path.relative_to(SERVER_ROOT).as_posix()}: {line.strip()}")
    assert not pham_quy, "URL hardcode:\n" + "\n".join(pham_quy)
