from pathlib import Path
import ast


def test_es_image_does_not_install_browser():
    root = Path(__file__).resolve().parents[1]
    assert 'playwright' not in (root / 'requirements-es.txt').read_text().lower()
    assert 'python:3.11-slim' in (root / 'Dockerfile.es').read_text()
    module = ast.parse((root / 'app/main.py').read_text())
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or '').startswith('playwright') for node in module.body)
