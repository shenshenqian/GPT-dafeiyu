#!/usr/bin/env python3
"""Validate, rebuild, preview and install the bundled Codex v2 pet packages."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT, CELL_W, CELL_H = 1536, 2288, 192, 208
ROWS = {
    'idle': (0, [280, 110, 110, 140, 140, 320]),
    'running-right': (1, [120] * 7 + [220]),
    'running-left': (2, [120] * 7 + [220]),
    'waving': (3, [140, 140, 140, 280]),
    'jumping': (4, [140, 140, 140, 140, 280]),
    'failed': (5, [140] * 7 + [240]),
    'waiting': (6, [150] * 5 + [260]),
    'running': (7, [120] * 5 + [220]),
    'review': (8, [150] * 5 + [280]),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def child_file(root: Path, name: str) -> Path:
    root = root.resolve()
    result = (root / name).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Asset path must stay inside its package/config directory.')
    return result


def load_pet(package: Path) -> tuple[dict, Path, Image.Image]:
    manifest = read_json(package / 'pet.json')
    atlas_path = child_file(package, manifest['spritesheetPath'])
    with Image.open(atlas_path) as opened:
        atlas = opened.convert('RGBA')
    return manifest, atlas_path, atlas


def validate(package: Path) -> dict:
    manifest, atlas_path, atlas = load_pet(package)
    errors = []
    if manifest.get('spriteVersionNumber') != 2:
        errors.append('spriteVersionNumber must be 2.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', manifest.get('id', package.name)):
        errors.append('Use a portable ASCII pet ID.')
    if not manifest.get('displayName', '').strip():
        errors.append('displayName is required.')
    if atlas_path.suffix.lower() not in {'.webp', '.png'}:
        errors.append('Atlas must be PNG or WebP.')
    if atlas.size != (WIDTH, HEIGHT):
        errors.append(f'Atlas must be {WIDTH}x{HEIGHT}.')
    used = {(row, col) for row, durations in ROWS.values() for col in range(len(durations))}
    used.add((0, 6))  # v2 neutral look frame
    used.update((row, col) for row in (9, 10) for col in range(8))
    if atlas.size == (WIDTH, HEIGHT):
        for row in range(11):
            for col in range(8):
                alpha = atlas.crop((col * CELL_W, row * CELL_H, (col + 1) * CELL_W, (row + 1) * CELL_H)).getchannel('A')
                populated = alpha.getbbox() is not None
                if populated != ((row, col) in used):
                    errors.append(f'Unexpected empty/populated cell at row {row}, column {col}.')
    raw = atlas.tobytes()
    residue = sum(1 for i in range(0, len(raw), 4) if raw[i + 3] == 0 and (raw[i] or raw[i + 1] or raw[i + 2]))
    if residue:
        errors.append(f'{residue} transparent pixels contain hidden RGB.')
    if atlas.getchannel('A').getextrema()[0] != 0:
        errors.append('Atlas has no fully transparent background pixels.')
    return {'ok': not errors, 'package': package.name, 'width': atlas.width, 'height': atlas.height,
            'spriteVersionNumber': manifest.get('spriteVersionNumber'), 'used_cells': len(used),
            'transparent_rgb_residue_pixels': residue, 'atlas_sha256': sha256(atlas_path), 'errors': errors}


def require_valid(package: Path) -> dict:
    report = validate(package)
    if not report['ok']:
        raise ValueError('; '.join(report['errors']))
    return report


def build(base: Path, config_path: Path, output: Path) -> dict:
    require_valid(base)
    config = read_json(config_path)
    manifest, _, source = load_pet(base)
    candidate = source.copy()
    changed = set()
    for state, filename in config['rows'].items():
        if state not in ROWS:
            raise ValueError(f'Unknown standard state: {state}')
        row, durations = ROWS[state]
        with Image.open(child_file(config_path.parent, filename)) as opened:
            strip = opened.convert('RGBA')
        if strip.size != (WIDTH, CELL_H):
            raise ValueError(f'{state}: prepared row must be {WIDTH}x{CELL_H}.')
        for col in range(len(durations), 8):
            if strip.crop((col * CELL_W, 0, (col + 1) * CELL_W, CELL_H)).getchannel('A').getbbox():
                raise ValueError(f'{state}: unused columns must remain transparent.')
        if row == 0:
            raise ValueError('This upgrade tool preserves idle and its neutral look frame; author a full atlas to change them.')
        candidate.paste(strip, (0, row * CELL_H))
        changed.add(row)
    if output.exists():
        raise ValueError('Output directory already exists. Choose a new output directory.')
    output.mkdir(parents=True)
    candidate.save(output / 'spritesheet.webp', lossless=True, exact=True, method=6)
    manifest.update(config['pet'])
    manifest.update(spriteVersionNumber=2, spritesheetPath='spritesheet.webp')
    (output / 'pet.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for key, destination in [('notice', 'NOTICE.txt'), ('readme', 'README.md')]:
        if config.get(key):
            shutil.copy2(child_file(config_path.parent, config[key]), output / destination)
    report = require_valid(output)
    _, _, decoded = load_pet(output)
    preserved = []
    for row in range(11):
        if row in changed:
            continue
        box = (0, row * CELL_H, WIDTH, (row + 1) * CELL_H)
        same = source.crop(box).tobytes() == decoded.crop(box).tobytes()
        preserved.append({'row': row, 'unchanged': same})
    if not all(item['unchanged'] for item in preserved):
        raise ValueError('Encoding changed an inherited row.')
    report['preserved_rows'] = preserved
    return report


def preview(package: Path, output: Path, compare: Path | None, embed: bool) -> dict:
    require_valid(package)
    variants = {'enhanced': package}
    if compare:
        require_valid(compare)
        variants['original'] = compare
    sources = {}
    for key, folder in variants.items():
        _, path, _ = load_pet(folder)
        if embed:
            mime = 'image/webp' if path.suffix.lower() == '.webp' else 'image/png'
            sources[key] = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
        else:
            sources[key] = os.path.relpath(path.resolve(), output.parent.resolve()).replace('\\', '/')
    template = (Path(__file__).resolve().parent.parent / 'templates/preview.html').read_text(encoding='utf-8')
    if len(variants) == 1:
        template = template.replace('<button data-version="original">原版对比</button>', '')
    template = template.replace('__ATLAS_SOURCES_JSON__', json.dumps(sources, ensure_ascii=False, separators=(',', ':')))
    manifest, _, _ = load_pet(package)
    template = template.replace('__PET_TITLE__', manifest['displayName'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template, encoding='utf-8')
    return {'ok': True, 'preview': output.name, 'embedded': embed, 'versions': list(variants)}


def install(package: Path, codex_home: Path) -> dict:
    report = require_valid(package)
    manifest, atlas_path, _ = load_pet(package)
    pet_id = manifest.get('id', package.name)
    target = child_file(codex_home / 'pets', pet_id)
    if target.exists():
        current = validate(target)
        if current['ok'] and current['atlas_sha256'] == report['atlas_sha256']:
            return {'ok': True, 'installed': pet_id, 'already_current': True}
        raise ValueError('A different pet with this ID already exists; it was not overwritten.')
    target.mkdir(parents=True)
    shutil.copy2(package / 'pet.json', target / 'pet.json')
    shutil.copy2(atlas_path, target / manifest['spritesheetPath'])
    for filename in ['NOTICE.txt', 'README.md']:
        if (package / filename).exists():
            shutil.copy2(package / filename, target / filename)
    require_valid(target)
    return {'ok': True, 'installed': pet_id, 'already_current': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('validate')
    check.add_argument('package', type=Path)
    check.add_argument('--report', type=Path)
    make = commands.add_parser('build')
    make.add_argument('--base', type=Path, required=True)
    make.add_argument('--config', type=Path, required=True)
    make.add_argument('--output', type=Path, required=True)
    show = commands.add_parser('preview')
    show.add_argument('package', type=Path)
    show.add_argument('--output', type=Path, required=True)
    show.add_argument('--compare', type=Path)
    show.add_argument('--embed', action='store_true', help='Embed images for a standalone HTML file.')
    put = commands.add_parser('install')
    put.add_argument('package', type=Path)
    put.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    args = parser.parse_args()
    try:
        if args.command == 'validate':
            result = validate(args.package)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        elif args.command == 'build':
            result = build(args.base, args.config, args.output)
        elif args.command == 'preview':
            result = preview(args.package, args.output, args.compare, args.embed)
        else:
            result = install(args.package, args.codex_home)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get('ok'):
            raise SystemExit(1)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
