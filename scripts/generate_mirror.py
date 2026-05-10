#!/usr/bin/env python3
"""
Generate mirrored (swap hands) layer from base layer.

Reads dasbob.keymap, extracts base layer bindings, mirrors them,
and replaces SWAP_HANDS_GEN layer content.

Usage:
    python generate_mirror.py [--keymap FILE]
"""

import argparse
import re
from pathlib import Path


def parse_bindings(bindings_str: str) -> list[str]:
    """Parse binding string into list of individual bindings."""
    bindings = []
    current = ""
    depth = 0

    for char in bindings_str:
        if char == '<':
            depth += 1
        elif char == '>':
            depth -= 1

        if char == '&' and depth == 0 and current.strip():
            bindings.append(current.strip())
            current = ""

        current += char

    if current.strip():
        bindings.append(current.strip())

    return bindings


def mirror_bindings(bindings: list[str], cols: int = 5, rows: int = 3, thumbs: int = 3) -> list[str]:
    """Mirror bindings for swap-hands layout.

    36-key layout:
    - 3 rows of 10 keys (5 left + 5 right)
    - 1 row of 6 thumb keys (3 left + 3 right)
    """
    mirrored = []

    # Mirror main rows (each row has cols*2 keys)
    row_size = cols * 2
    for row in range(rows):
        start = row * row_size
        end = start + row_size
        row_bindings = bindings[start:end]

        # Split into left and right halves, swap them
        left = row_bindings[:cols]
        right = row_bindings[cols:]

        # Reverse each half and swap positions
        mirrored.extend(reversed(right))
        mirrored.extend(reversed(left))

    # Mirror thumb row
    thumb_start = rows * row_size
    thumb_bindings = bindings[thumb_start:thumb_start + thumbs * 2]

    left_thumbs = thumb_bindings[:thumbs]
    right_thumbs = thumb_bindings[thumbs:]

    mirrored.extend(reversed(right_thumbs))
    mirrored.extend(reversed(left_thumbs))

    return mirrored


def swap_hrm_handedness(binding: str) -> str:
    """Swap hml <-> hmr for home row mods, and LSHFT <-> RSHFT."""
    result = binding

    # Swap hml <-> hmr
    if result.startswith('&hml '):
        result = result.replace('&hml ', '&hmr ', 1)
    elif result.startswith('&hmr '):
        result = result.replace('&hmr ', '&hml ', 1)

    # Swap LSHFT <-> RSHFT (for consistency when hands swap)
    if 'LSHFT' in result:
        result = result.replace('LSHFT', 'RSHFT')
    elif 'RSHFT' in result:
        result = result.replace('RSHFT', 'LSHFT')

    return result


def format_layer(bindings: list[str], cols: int = 5, rows: int = 3, thumbs: int = 3) -> str:
    """Format bindings as layer content."""
    lines = []
    row_size = cols * 2

    for row in range(rows):
        start = row * row_size
        row_bindings = bindings[start:start + row_size]
        lines.append("                " + " ".join(row_bindings))

    # Thumb row
    thumb_start = rows * row_size
    thumb_bindings = bindings[thumb_start:thumb_start + thumbs * 2]
    lines.append("                " + " ".join(thumb_bindings))

    return "\n".join(lines)


def process_keymap(keymap_path: Path) -> str:
    """Process keymap file and generate mirrored layer."""
    content = keymap_path.read_text()

    # Find base layer bindings
    base_match = re.search(
        r'layer_Base\s*\{[^}]*display-name\s*=\s*"Base"[^}]*bindings\s*=\s*<([^>]+)>',
        content,
        re.DOTALL
    )

    if not base_match:
        raise ValueError("Could not find Base layer bindings")

    base_bindings_str = base_match.group(1)
    bindings = parse_bindings(base_bindings_str)

    print(f"Found {len(bindings)} bindings in Base layer")

    if len(bindings) != 36:
        raise ValueError(f"Expected 36 bindings, found {len(bindings)}")

    # Mirror and swap HRM handedness
    mirrored = mirror_bindings(bindings)
    mirrored = [swap_hrm_handedness(b) for b in mirrored]

    # Format new layer content
    new_layer_content = format_layer(mirrored)

    # Replace SWAP_HANDS_GEN layer content
    pattern = r'(display-name\s*=\s*"SWAP_HANDS_GEN"[^}]*bindings\s*=\s*<)[^>]+(>)'

    def replacer(m):
        return m.group(1) + "\n" + new_layer_content + "\n            " + m.group(2)

    new_content, count = re.subn(pattern, replacer, content, flags=re.DOTALL)

    if count == 0:
        raise ValueError("Could not find SWAP_HANDS_GEN layer")

    print(f"Updated SWAP_HANDS_GEN layer")

    return new_content


def main():
    parser = argparse.ArgumentParser(description='Generate mirrored swap-hands layer')
    parser.add_argument('--keymap', '-k', default='config/dasbob.keymap',
                        help='Keymap file (default: config/dasbob.keymap)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Print changes without writing')

    args = parser.parse_args()

    keymap_path = Path(args.keymap)
    if not keymap_path.exists():
        print(f"Error: {keymap_path} not found")
        return 1

    try:
        new_content = process_keymap(keymap_path)

        if args.dry_run:
            print("\n--- Generated content ---")
            print(new_content)
        else:
            keymap_path.write_text(new_content)
            print(f"Updated {keymap_path}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
