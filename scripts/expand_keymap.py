#!/usr/bin/env python3
"""
ZMK Keymap Expander

Parses urob's zmk-helpers macro-based keymap and expands to standard DTS format
compatible with Nick Coutsos' Keymap Editor.

Usage:
    python expand_keymap.py [--config-dir DIR] [--output FILE]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Key position mappings (36-key layout)
KEY_POSITIONS = {
    'LT4': 0, 'LT3': 1, 'LT2': 2, 'LT1': 3, 'LT0': 4,
    'RT0': 5, 'RT1': 6, 'RT2': 7, 'RT3': 8, 'RT4': 9,
    'LM4': 10, 'LM3': 11, 'LM2': 12, 'LM1': 13, 'LM0': 14,
    'RM0': 15, 'RM1': 16, 'RM2': 17, 'RM3': 18, 'RM4': 19,
    'LB4': 20, 'LB3': 21, 'LB2': 22, 'LB1': 23, 'LB0': 24,
    'RB0': 25, 'RB1': 26, 'RB2': 27, 'RB3': 28, 'RB4': 29,
    'LH2': 30, 'LH1': 31, 'LH0': 32,
    'RH0': 33, 'RH1': 34, 'RH2': 35,
}

POSITION_GROUPS = {
    'KEYS_L': [0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
    'KEYS_R': [5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 25, 26, 27, 28, 29],
    'THUMBS': [30, 31, 32, 33, 34, 35],
}

# ZMK behavior types -> (compatible string, binding-cells)
BEHAVIOR_TYPES = {
    'HOLD_TAP': ('zmk,behavior-hold-tap', 2),
    'MOD_MORPH': ('zmk,behavior-mod-morph', 0),
    'TAP_DANCE': ('zmk,behavior-tap-dance', 0),
    'TRI_STATE': ('zmk,behavior-tri-state', 0),
    'ADAPTIVE_KEY': ('zmk,behavior-adaptive-key', 0),
    'MACRO': ('zmk,behavior-macro', 0),
}


@dataclass
class MacroDef:
    """Represents a #define macro."""
    name: str
    params: Optional[List[str]] = None  # None = simple macro, list = parameterized
    body: str = ""
    is_multiline: bool = False


@dataclass
class ParseState:
    """Parser state accumulator."""
    macros: Dict[str, MacroDef] = field(default_factory=dict)
    behaviors: List[str] = field(default_factory=list)
    combos: List[str] = field(default_factory=list)
    layers: List[str] = field(default_factory=list)
    conditional_layers: List[str] = field(default_factory=list)
    leader_sequences: List[str] = field(default_factory=list)
    node_overrides: List[str] = field(default_factory=list)  # &node { } outside root
    raw_passthrough: List[str] = field(default_factory=list)  # DTS that passes through


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return 'unknown'


def resolve_positions(text: str, macros: Dict[str, MacroDef]) -> str:
    """Replace position names and groups with numbers."""
    result = text

    # Expand position groups first
    for group_name, positions in POSITION_GROUPS.items():
        result = re.sub(
            rf'\b{group_name}\b',
            ' '.join(map(str, positions)),
            result
        )

    # Then individual positions
    for pos_name, pos_num in KEY_POSITIONS.items():
        result = re.sub(rf'\b{pos_name}\b', str(pos_num), result)

    return result


def strip_comments(text: str) -> str:
    """Remove C-style comments from text."""
    # Remove // comments (but preserve the content before them)
    result = re.sub(r'\s*//[^\n]*', '', text)
    # Remove /* */ comments
    result = re.sub(r'/\*.*?\*/', '', result, flags=re.DOTALL)
    return result


def normalize_whitespace(text: str) -> str:
    """Normalize excessive whitespace from macro expansion."""
    # Replace multiple spaces with single space
    result = re.sub(r'  +', ' ', text)
    # Fix double semicolons
    result = re.sub(r';\s*;', ';', result)
    return result.strip()


def expand_simple_macro(text: str, macros: Dict[str, MacroDef], strip_macro_comments: bool = True) -> str:
    """Expand simple (non-parameterized) macros in text."""
    result = text
    changed = True
    iterations = 0

    while changed and iterations < 50:  # Prevent infinite loops
        changed = False
        iterations += 1
        for name, macro in macros.items():
            if macro.params is None:  # Simple macro
                pattern = rf'\b{re.escape(name)}\b'
                # Strip comments from macro body before substitution
                body = macro.body
                if strip_macro_comments:
                    body = re.sub(r'\s*//.*$', '', body)
                new_result = re.sub(pattern, body, result)
                if new_result != result:
                    result = new_result
                    changed = True

    return result


def parse_macro_definition(line: str, lines_iter) -> Optional[MacroDef]:
    """Parse a #define directive, handling multi-line macros."""
    match = re.match(r'#define\s+(\w+)(?:\(([^)]*)\))?\s*(.*)', line)
    if not match:
        return None

    name = match.group(1)
    params_str = match.group(2)
    body = match.group(3).strip()

    params = None
    if params_str is not None:
        params = [p.strip() for p in params_str.split(',') if p.strip()]

    # Handle multi-line macros (ending with \)
    is_multiline = body.endswith('\\')
    while body.endswith('\\'):
        body = body[:-1].strip()
        try:
            next_line = next(lines_iter).rstrip()
            body += ' ' + next_line.strip()
        except StopIteration:
            break

    if body.endswith('\\'):
        body = body[:-1].strip()

    return MacroDef(name=name, params=params, body=body, is_multiline=is_multiline)


def expand_parameterized_macro(name: str, args: List[str], macro: MacroDef) -> str:
    """Expand a parameterized macro with given arguments."""
    if macro.params is None or len(args) != len(macro.params):
        return f"/* ERROR: macro {name} param mismatch */"

    result = macro.body
    for param, arg in zip(macro.params, args):
        # Handle token pasting (##)
        result = re.sub(rf'{param}\s*##\s*(\w+)', arg + r'\1', result)
        result = re.sub(rf'(\w+)\s*##\s*{param}', r'\1' + arg, result)
        # Regular substitution
        result = re.sub(rf'\b{param}\b', arg, result)

    return result


def parse_zmk_behavior(text: str, behavior_type: str, macros: Dict[str, MacroDef]) -> Optional[str]:
    """Parse and expand a ZMK_* behavior macro to DTS."""
    # Match ZMK_BEHAVIOR_TYPE(name, props...)
    # Props can span multiple "lines" in the joined text
    pattern = rf'ZMK_{behavior_type}\s*\(\s*(\w+)\s*,\s*(.+?)\s*\)\s*$'
    match = re.match(pattern, text, re.DOTALL)
    if not match:
        # Try without trailing )
        pattern = rf'ZMK_{behavior_type}\s*\(\s*(\w+)\s*,\s*(.+)'
        match = re.match(pattern, text, re.DOTALL)
        if not match:
            return None

    name = match.group(1)
    props_raw = match.group(2).rstrip(')')

    compatible, binding_cells = BEHAVIOR_TYPES[behavior_type]

    # Expand macros first, then parse properties
    props_expanded = expand_simple_macro(props_raw, macros)
    props_expanded = resolve_positions(props_expanded, macros)
    props_expanded = strip_comments(props_expanded)
    props_expanded = normalize_whitespace(props_expanded)

    # Parse properties (semicolon-separated)
    props = []
    for prop in re.split(r';\s*', props_expanded):
        prop = prop.strip()
        if prop:
            props.append(prop)

    # Build DTS node
    lines = [
        f'        {name}: {name} {{',
        f'            compatible = "{compatible}";',
        f'            #binding-cells = <{binding_cells}>;',
    ]

    for prop in props:
        # Skip empty props
        if not prop:
            continue
        lines.append(f'            {prop};')

    lines.append('        };')

    return '\n'.join(lines)


def parse_zmk_combo(text: str, macros: Dict[str, MacroDef]) -> Optional[str]:
    """Parse ZMK_COMBO macro to DTS."""
    # ZMK_COMBO(name, binding, positions, layers, timeout, idle[, hold, side])
    pattern = r'ZMK_COMBO\s*\(\s*(\w+)\s*,\s*(.+?)\s*,\s*(.+?)\s*,\s*(.+?)\s*,\s*(\w+)\s*,\s*(\w+)(?:\s*,\s*(\w+(?:\([^)]*\))?)\s*,\s*(\w+))?\s*\)'
    match = re.match(pattern, text)
    if not match:
        return None

    name = match.group(1)
    binding = expand_simple_macro(match.group(2).strip(), macros)
    positions = resolve_positions(match.group(3), macros)
    layers_str = match.group(4)
    timeout = expand_simple_macro(match.group(5), macros)
    idle = expand_simple_macro(match.group(6), macros)
    hold = match.group(7)  # Optional
    side = match.group(8)  # Optional

    # Resolve layer names to numbers
    layers = []
    for token in layers_str.split():
        token = token.strip()
        if token in macros and macros[token].params is None:
            layers.append(macros[token].body)
        else:
            layers.append(token)

    # Convert positions to list of numbers
    pos_nums = []
    for token in positions.split():
        token = token.strip()
        if token.isdigit():
            pos_nums.append(token)

    lines = [
        f'        combo_{name} {{',
        f'            bindings = <{binding}>;',
        f'            key-positions = <{" ".join(pos_nums)}>;',
        f'            layers = <{" ".join(layers)}>;',
        f'            timeout-ms = <{timeout}>;',
        f'            require-prior-idle-ms = <{idle}>;',
        '        };',
    ]

    return '\n'.join(lines)


def parse_zmk_layer(text: str, macros: Dict[str, MacroDef]) -> Optional[str]:
    """Parse ZMK_LAYER or ZMK_BASE_LAYER macro to DTS."""
    # ZMK_BASE_LAYER(name, bindings with commas between rows)
    pattern = r'ZMK_(?:BASE_)?LAYER\s*\(\s*(\w+)\s*,\s*(.+?)\s*\)\s*$'
    match = re.match(pattern, text, re.DOTALL)
    if not match:
        return None

    name = match.group(1)
    bindings_raw = match.group(2)

    # Expand macros in bindings
    bindings = expand_simple_macro(bindings_raw, macros)
    bindings = resolve_positions(bindings, macros)

    # Process line by line
    lines_out = []
    for line in bindings.split('\n'):
        original_line = line
        line = line.rstrip(',').strip()

        # Keep visual comment lines (row separators)
        if line.startswith('//╭') or line.startswith('//├') or line.startswith('//╰'):
            lines_out.append(line)
        elif line.startswith('//'):
            # Skip inline comments
            continue
        elif line:
            # Strip inline comments from binding lines
            line = re.sub(r'\s*//.*$', '', line)
            # Remove all commas (including mid-line between halves)
            line = line.replace(',', '')
            if line.strip():
                lines_out.append('    ' + line.strip())

    bindings_formatted = '\n'.join(lines_out)

    result = f'''        layer_{name} {{
            display-name = "{name}";
            bindings = <
{bindings_formatted}
            >;
        }};'''

    return result


def parse_zmk_conditional_layer(text: str, macros: Dict[str, MacroDef]) -> Optional[str]:
    """Parse ZMK_CONDITIONAL_LAYER macro to DTS."""
    pattern = r'ZMK_CONDITIONAL_LAYER\s*\(\s*(\w+)\s*,\s*(\w+)\s+(\w+)\s*,\s*(\w+)\s*\)'
    match = re.match(pattern, text)
    if not match:
        return None

    name = match.group(1)
    if_layer1 = expand_simple_macro(match.group(2), macros)
    if_layer2 = expand_simple_macro(match.group(3), macros)
    then_layer = expand_simple_macro(match.group(4), macros)

    return f'''        {name}_layer {{
            if-layers = <{if_layer1} {if_layer2}>;
            then-layer = <{then_layer}>;
        }};'''


def parse_zmk_leader_sequence(text: str, macros: Dict[str, MacroDef]) -> Optional[str]:
    """Parse ZMK_LEADER_SEQUENCE macro to DTS."""
    pattern = r'ZMK_LEADER_SEQUENCE\s*\(\s*(\w+)\s*,\s*(.+?)\s*,\s*(.+?)\s*\)'
    match = re.match(pattern, text)
    if not match:
        return None

    name = match.group(1)
    binding = match.group(2).strip()
    sequence = match.group(3).strip()

    return f'''            leader_sequence_{name} {{
                bindings = <{binding}>;
                sequence = <{sequence}>;
            }};'''


def read_file_content(filepath: Path, config_dir: Path) -> str:
    """Read file content, trying relative to config_dir."""
    if filepath.is_absolute() and filepath.exists():
        return filepath.read_text()

    # Try relative to config_dir
    full_path = config_dir / filepath
    if full_path.exists():
        return full_path.read_text()

    return ""


def process_includes(content: str, config_dir: Path, processed: set = None) -> str:
    """Process #include directives, inlining local files."""
    if processed is None:
        processed = set()

    lines = []
    for line in content.split('\n'):
        # Local include: #include "file.dtsi"
        match = re.match(r'#include\s+"([^"]+)"', line)
        if match:
            filename = match.group(1)
            if filename not in processed:
                processed.add(filename)
                included_content = read_file_content(Path(filename), config_dir)
                if included_content:
                    # Recursively process includes
                    included_content = process_includes(included_content, config_dir, processed)
                    lines.append(f'/* === Included from {filename} === */')
                    lines.append(included_content)
                    lines.append(f'/* === End {filename} === */')
                else:
                    lines.append(f'/* Include not found: {filename} */')
            continue

        # System include: keep as-is but we'll handle specially
        if re.match(r'#include\s+<', line):
            lines.append(line)
            continue

        lines.append(line)

    return '\n'.join(lines)


def collect_multiline_construct(start_line: str, lines_iter) -> str:
    """Collect a construct that may span multiple lines (parentheses/braces balanced)."""
    result = start_line

    # Count parens/braces
    open_parens = result.count('(') - result.count(')')
    open_braces = result.count('{') - result.count('}')

    while (open_parens > 0 or open_braces > 0):
        try:
            next_line = next(lines_iter)
            result += '\n' + next_line
            open_parens += next_line.count('(') - next_line.count(')')
            open_braces += next_line.count('{') - next_line.count('}')
        except StopIteration:
            break

    return result


def parse_content(content: str, config_dir: Path) -> ParseState:
    """Parse the full content and extract all components."""
    state = ParseState()

    # Pre-seed macros that come from #ifdef blocks (assume wireless)
    state.macros['_BT_SEL_KEYS_'] = MacroDef(
        name='_BT_SEL_KEYS_',
        body='&bt BT_SEL 0 &bt BT_SEL 1 &bt BT_SEL 2 &bt BT_SEL 3 &bt BT_CLR'
    )

    # First pass: collect all macro definitions
    lines = content.split('\n')
    lines_iter = iter(enumerate(lines))

    remaining_lines = []

    for idx, line in lines_iter:
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('//'):
            remaining_lines.append(line)
            continue

        # Parse #define
        if stripped.startswith('#define'):
            # Need to handle multi-line defines
            full_line = line
            while full_line.rstrip().endswith('\\'):
                try:
                    _, next_line = next(lines_iter)
                    full_line += '\n' + next_line
                except StopIteration:
                    break

            macro = parse_macro_definition(full_line.replace('\\\n', ' '), iter([]))
            if macro:
                state.macros[macro.name] = macro
            continue

        remaining_lines.append(line)

    # Second pass: process the non-macro content
    content = '\n'.join(remaining_lines)
    lines = content.split('\n')
    lines_iter = iter(lines)

    for line in lines_iter:
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('//') or stripped.startswith('/*'):
            continue

        # Skip system includes (we'll add our own header)
        if stripped.startswith('#include <'):
            continue

        # Skip #ifdef/#else/#endif (assume wireless config)
        if stripped.startswith('#if') or stripped.startswith('#else') or stripped.startswith('#endif'):
            continue

        # Node override outside root: &name { ... }
        if stripped.startswith('&') and '{' in stripped:
            full = collect_multiline_construct(line, lines_iter)
            # Resolve positions and expand macros
            full = resolve_positions(full, state.macros)
            full = expand_simple_macro(full, state.macros)
            full = strip_comments(full)
            # Normalize whitespace but preserve structure
            full = re.sub(r'  +', ' ', full)
            full = re.sub(r';\s*;', ';', full)
            state.node_overrides.append(full)
            continue

        # ZMK behavior macros
        for btype in BEHAVIOR_TYPES:
            if f'ZMK_{btype}' in stripped:
                full = collect_multiline_construct(line, lines_iter)
                expanded = parse_zmk_behavior(full.strip(), btype, state.macros)
                if expanded:
                    state.behaviors.append(expanded)
                break
        else:
            # ZMK_COMBO
            if 'ZMK_COMBO' in stripped:
                full = collect_multiline_construct(line, lines_iter)
                expanded = parse_zmk_combo(full.strip(), state.macros)
                if expanded:
                    state.combos.append(expanded)
                continue

            # ZMK_LAYER / ZMK_BASE_LAYER
            if 'ZMK_LAYER' in stripped or 'ZMK_BASE_LAYER' in stripped:
                full = collect_multiline_construct(line, lines_iter)
                expanded = parse_zmk_layer(full.strip(), state.macros)
                if expanded:
                    state.layers.append(expanded)
                continue

            # ZMK_CONDITIONAL_LAYER
            if 'ZMK_CONDITIONAL_LAYER' in stripped:
                expanded = parse_zmk_conditional_layer(stripped, state.macros)
                if expanded:
                    state.conditional_layers.append(expanded)
                continue

            # ZMK_LEADER_SEQUENCE
            if 'ZMK_LEADER_SEQUENCE' in stripped:
                expanded = parse_zmk_leader_sequence(stripped, state.macros)
                if expanded:
                    state.leader_sequences.append(expanded)
                continue

            # Local macro calls that generate behaviors (MAKE_HRM, SIMPLE_MORPH, etc.)
            for macro_name, macro in state.macros.items():
                if macro.params and macro_name in stripped:
                    # Try to parse as macro call
                    pattern = rf'{macro_name}\s*\(([^)]+)\)'
                    match = re.search(pattern, stripped)
                    if match:
                        args = [a.strip() for a in match.group(1).split(',')]
                        expanded_call = expand_parameterized_macro(macro_name, args, macro)
                        # The expanded call might be another ZMK_* macro
                        for btype in BEHAVIOR_TYPES:
                            if f'ZMK_{btype}' in expanded_call:
                                behavior = parse_zmk_behavior(expanded_call, btype, state.macros)
                                if behavior:
                                    state.behaviors.append(behavior)
                                break

    return state


def generate_output(state: ParseState, commit_hash: str) -> str:
    """Generate the final expanded keymap file."""
    timestamp = datetime.now().strftime('%Y-%m-%d')

    lines = []

    # Header
    lines.append(f'''/*
 * ZMK Keymap - Expanded from urob/zmk-config
 *
 * Generated: {timestamp}
 * Source commit: {commit_hash}
 *
 * This file is auto-generated by expand_keymap.py for Keymap Editor compatibility.
 */

#include <behaviors.dtsi>
#include <behaviors/num_word.dtsi>
#include <behaviors/unicode.dtsi>
#include <dt-bindings/zmk/keys.h>
#include <dt-bindings/zmk/bt.h>
#include <dt-bindings/zmk/outputs.h>

/* Mouse settings - must be before pointing.h */
#define ZMK_POINTING_DEFAULT_MOVE_VAL 600
#define ZMK_POINTING_DEFAULT_SCRL_VAL 20

#include <dt-bindings/zmk/pointing.h>
#include <input/processors.dtsi>
#include <zephyr/dt-bindings/input/input-event-codes.h>
''')

    # Layer defines
    lines.append('#define DEF 0')
    lines.append('#define NAV 1')
    lines.append('#define FN 2')
    lines.append('#define NUM 3')
    lines.append('#define SYS 4')
    lines.append('#define MOUSE 5')
    lines.append('')
    lines.append('#define KEYS_L 0 1 2 3 4 10 11 12 13 14 20 21 22 23 24')
    lines.append('#define KEYS_R 5 6 7 8 9 15 16 17 18 19 25 26 27 28 29')
    lines.append('#define THUMBS 30 31 32 33 34 35')
    lines.append('')
    lines.append('#define QUICK_TAP_MS 175')
    lines.append('')

    # Node overrides (outside root)
    for override in state.node_overrides:
        lines.append(override)
        lines.append('')

    # Root node
    lines.append('/ {')

    # Behaviors
    lines.append('    behaviors {')
    for behavior in state.behaviors:
        lines.append(behavior)
        lines.append('')

    # Leader key (if we have sequences)
    if state.leader_sequences:
        lines.append('        leader: leader {')
        lines.append('            compatible = "zmk,behavior-leader-key";')
        lines.append('            #binding-cells = <0>;')
        lines.append('            ignore-keys = <LSHFT RSHFT>;')
        for seq in state.leader_sequences:
            lines.append(seq)
        lines.append('        };')
        lines.append('')

    lines.append('    };')  # Close behaviors
    lines.append('')

    # Combos
    if state.combos:
        lines.append('    combos {')
        lines.append('        compatible = "zmk,combos";')
        lines.append('')
        for combo in state.combos:
            lines.append(combo)
            lines.append('')
        lines.append('    };')
        lines.append('')

    # Conditional layers
    if state.conditional_layers:
        lines.append('    conditional_layers {')
        lines.append('        compatible = "zmk,conditional-layers";')
        for cl in state.conditional_layers:
            lines.append(cl)
        lines.append('    };')
        lines.append('')

    # Keymap layers
    lines.append('    keymap {')
    lines.append('        compatible = "zmk,keymap";')
    lines.append('')
    for layer in state.layers:
        lines.append(layer)
        lines.append('')
    lines.append('    };')

    lines.append('};')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Expand ZMK keymap macros to DTS format')
    parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    parser.add_argument('--config-dir', '-d', default='config', help='Config directory')
    parser.add_argument('--commit', '-c', help='Override commit hash')

    args = parser.parse_args()

    config_dir = Path(args.config_dir)
    base_keymap = config_dir / 'base.keymap'

    if not base_keymap.exists():
        print(f"Error: {base_keymap} not found", file=sys.stderr)
        sys.exit(1)

    # Read and process includes
    content = base_keymap.read_text()
    content = process_includes(content, config_dir)

    # Parse everything
    state = parse_content(content, config_dir)

    # Generate output
    commit_hash = args.commit or get_git_commit()
    output = generate_output(state, commit_hash)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Expanded keymap written to: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == '__main__':
    main()
