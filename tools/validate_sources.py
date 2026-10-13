"""Offline syntax and source-catalog validation. Does not run scrapers."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def content_hash(path: Path) -> str:
    data = path.read_bytes()
    try:
        data = data.decode('utf-8-sig').replace('\r\n', '\n').encode('utf-8')
    except UnicodeDecodeError:
        pass
    return hashlib.sha256(data).hexdigest()


def validate(root: Path) -> dict:
    names = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard'], text=True
    ).splitlines()
    failures = []
    python_count = notebook_count = 0
    for name in sorted(set(names)):
        path = root / name
        if path.suffix == '.py':
            try:
                compile(path.read_bytes(), str(path), 'exec')
                python_count += 1
            except (SyntaxError, UnicodeError) as exc:
                failures.append({'path': name, 'error': str(exc)})
        elif path.suffix == '.ipynb':
            try:
                notebook = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(notebook.get('cells'), list):
                    raise ValueError('Notebook has no cell list')
                notebook_count += 1
            except (ValueError, UnicodeError) as exc:
                failures.append({'path': name, 'error': str(exc)})
    catalog_path = root / 'docs/country_website_catalog.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else []
    for entry in catalog:
        for name in entry['scripts']:
            if not (root / name).is_file():
                failures.append({'path': name, 'error': 'Catalog references missing script'})
    manifest_path = root / 'docs/source_sync_manifest.json'
    checked_hashes = 0
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest['files']:
            path = root / entry['path']
            if not path.is_file() or content_hash(path) != entry['final_sha256']:
                failures.append({'path': entry['path'], 'error': 'Source manifest hash mismatch'})
            checked_hashes += 1
    return {'python_files': python_count, 'notebooks': notebook_count,
            'catalog_entries': len(catalog), 'checked_hashes': checked_hashes, 'failures': failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--json-output', type=Path)
    args = parser.parse_args()
    result = validate(args.root)
    if args.json_output:
        args.json_output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return bool(result['failures'])


if __name__ == '__main__':
    sys.exit(main())
