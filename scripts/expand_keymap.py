#!/usr/bin/env python3
"""
ZMK Keymap Expander

Expands urob's zmk-helpers macros into standard DTS format compatible with
Nick Coutsos' Keymap Editor.

Usage:
    python expand_keymap.py [--output OUTPUT] [--commit COMMIT]

Outputs expanded keymap to stdout or specified file.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

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

# Positional groups
KEYS_L = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24]
KEYS_R = [5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 25, 26, 27, 28, 29]
THUMBS = [30, 31, 32, 33, 34, 35]

# Layer name to index mapping
LAYERS = {'DEF': 0, 'NAV': 1, 'FN': 2, 'NUM': 3, 'SYS': 4, 'MOUSE': 5}

# Behavior type to compatible string and binding-cells
BEHAVIOR_TYPES = {
    'hold_tap': ('zmk,behavior-hold-tap', 2),
    'mod_morph': ('zmk,behavior-mod-morph', 0),
    'tap_dance': ('zmk,behavior-tap-dance', 0),
    'tri_state': ('zmk,behavior-tri-state', 0),
    'adaptive_key': ('zmk,behavior-adaptive-key', 0),
    'macro': ('zmk,behavior-macro', 0),
}


def get_git_commit():
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return 'unknown'


def resolve_key_positions(pos_str):
    """Convert position names (LT1 LT2) to numbers."""
    positions = []
    for token in pos_str.split():
        token = token.strip()
        if token in KEY_POSITIONS:
            positions.append(KEY_POSITIONS[token])
        elif token == 'KEYS_L':
            positions.extend(KEYS_L)
        elif token == 'KEYS_R':
            positions.extend(KEYS_R)
        elif token == 'THUMBS':
            positions.extend(THUMBS)
        elif token.isdigit():
            positions.append(int(token))
    return positions


def resolve_layers(layer_str):
    """Convert layer names to indices."""
    layers = []
    for token in layer_str.split():
        token = token.strip()
        if token in LAYERS:
            layers.append(LAYERS[token])
        elif token.isdigit():
            layers.append(int(token))
    return layers


def parse_combo(line):
    """Parse ZMK_COMBO macro call."""
    # ZMK_COMBO(name, binding, positions, layers, timeout, idle[, hold, side])
    match = re.match(r'ZMK_COMBO\s*\(\s*(\w+)\s*,\s*(.+?)\s*,\s*(.+?)\s*,\s*(.+?)\s*,\s*(\w+)\s*,\s*(\w+)(?:\s*,\s*(\w+)\s*,\s*(\w+))?\s*\)', line)
    if not match:
        return None

    name = match.group(1)
    binding = match.group(2).strip()
    positions = resolve_key_positions(match.group(3))
    layers = resolve_layers(match.group(4))
    timeout = match.group(5)
    idle = match.group(6)
    hold = match.group(7)  # Optional HRM hold key
    side = match.group(8)  # Optional HRM side

    return {
        'name': name,
        'binding': binding,
        'positions': positions,
        'layers': layers,
        'timeout': timeout,
        'idle': idle,
        'hold': hold,
        'side': side,
    }


def expand_combo(combo, hrm_combos):
    """Expand combo to DTS format."""
    lines = []
    name = combo['name']

    # If combo has HRM (8-arg version), generate the hm_combo behavior first
    if combo['hold'] and combo['side']:
        hrm_name = f"hm_combo_{name}"
        side_positions = KEYS_L if combo['side'] == 'KEYS_L' else KEYS_R
        trigger_positions = side_positions + THUMBS

        hrm_combos.append({
            'name': hrm_name,
            'hold': combo['hold'],
            'tap': combo['binding'],
            'trigger_positions': trigger_positions,
        })
        binding = f"&{hrm_name} {combo['hold']} 0"
    else:
        binding = combo['binding']

    lines.append(f"        combo_{name} {{")
    lines.append(f"            bindings = <{binding}>;")
    lines.append(f"            key-positions = <{' '.join(map(str, combo['positions']))}>;")
    lines.append(f"            layers = <{' '.join(map(str, combo['layers']))}>;")

    # Resolve timeout/idle constants
    timeout = combo['timeout']
    if timeout == 'COMBO_TERM_FAST':
        timeout = '18'
    elif timeout == 'COMBO_TERM_SLOW':
        timeout = '30'

    idle = combo['idle']
    if idle == 'COMBO_IDLE_FAST':
        idle = '150'
    elif idle == 'COMBO_IDLE_SLOW':
        idle = '50'

    lines.append(f"            timeout-ms = <{timeout}>;")
    lines.append(f"            require-prior-idle-ms = <{idle}>;")
    lines.append("        };")

    return '\n'.join(lines)


def expand_hrm_combo_behavior(hrm):
    """Expand HRM combo behavior to DTS format."""
    lines = []
    lines.append(f"        {hrm['name']}: {hrm['name']} {{")
    lines.append('            compatible = "zmk,behavior-hold-tap";')
    lines.append('            #binding-cells = <2>;')
    lines.append(f"            bindings = <&kp>, <{hrm['tap']}>;")
    lines.append('            flavor = "balanced";')
    lines.append('            tapping-term-ms = <280>;')
    lines.append('            quick-tap-ms = <175>;')
    lines.append('            require-prior-idle-ms = <150>;')
    lines.append('            hold-trigger-on-release;')
    lines.append(f"            hold-trigger-key-positions = <{' '.join(map(str, hrm['trigger_positions']))}>;")
    lines.append("        };")
    return '\n'.join(lines)


def parse_leader_sequence(line):
    """Parse ZMK_LEADER_SEQUENCE macro call."""
    match = re.match(r'ZMK_LEADER_SEQUENCE\s*\(\s*(\w+)\s*,\s*(.+?)\s*,\s*(.+?)\s*\)', line)
    if not match:
        return None

    return {
        'name': match.group(1),
        'binding': match.group(2).strip(),
        'sequence': match.group(3).strip(),
    }


def expand_leader_sequences(sequences):
    """Expand leader sequences into leader behavior node."""
    lines = []
    lines.append("        leader: leader {")
    lines.append('            compatible = "zmk,behavior-leader-key";')
    lines.append('            #binding-cells = <0>;')
    lines.append('            ignore-keys = <LSHFT RSHFT>;')

    for seq in sequences:
        lines.append(f"            leader_sequence_{seq['name']} {{")
        lines.append(f"                bindings = <{seq['binding']}>;")
        lines.append(f"                sequence = <{seq['sequence']}>;")
        lines.append("            };")

    lines.append("        };")
    return '\n'.join(lines)


def parse_behavior(line, behavior_type):
    """Parse ZMK_HOLD_TAP, ZMK_MOD_MORPH, etc."""
    pattern = rf'ZMK_({behavior_type.upper()})\s*\(\s*(\w+)\s*,(.+)\)'
    match = re.match(pattern, line, re.IGNORECASE)
    if not match:
        # Try alternate pattern for multi-line or complex cases
        pattern = rf'ZMK_({behavior_type.upper()})\s*\(\s*(\w+)\s*,'
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            return {'name': match.group(2), 'type': behavior_type, 'props': 'INCOMPLETE'}
        return None

    return {
        'name': match.group(2),
        'type': behavior_type,
        'props': match.group(3).strip().rstrip(')'),
    }


def parse_keymap_files(config_dir):
    """Parse base.keymap and included files."""
    config_path = Path(config_dir)

    base_keymap = config_path / 'base.keymap'
    combos_file = config_path / 'combos.dtsi'
    leader_file = config_path / 'leader.dtsi'
    mouse_file = config_path / 'mouse.dtsi'

    result = {
        'combos': [],
        'leader_sequences': [],
        'behaviors': [],
        'layers': [],
        'mouse_config': '',
    }

    # Parse combos
    if combos_file.exists():
        content = combos_file.read_text()
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('ZMK_COMBO'):
                combo = parse_combo(line)
                if combo:
                    result['combos'].append(combo)

    # Parse leader sequences
    if leader_file.exists():
        content = leader_file.read_text()
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('ZMK_LEADER_SEQUENCE'):
                seq = parse_leader_sequence(line)
                if seq:
                    result['leader_sequences'].append(seq)

    # Parse mouse config (mostly passthrough)
    if mouse_file.exists():
        result['mouse_config'] = mouse_file.read_text()

    return result


def generate_header(commit_hash):
    """Generate file header with metadata."""
    timestamp = datetime.now().strftime('%Y-%m-%d')
    return f'''/*
 * ZMK Keymap - Expanded from urob/zmk-config
 *
 * Generated: {timestamp}
 * Source commit: {commit_hash}
 *
 * This file is auto-generated by expand_keymap.py for Keymap Editor compatibility.
 * Do not edit this file directly - edit the source and re-expand.
 */

#include <behaviors.dtsi>
#include <behaviors/num_word.dtsi>
#include <behaviors/unicode.dtsi>
#include <dt-bindings/zmk/keys.h>
#include <dt-bindings/zmk/bt.h>
#include <dt-bindings/zmk/outputs.h>
#include <dt-bindings/zmk/pointing.h>
#include <input/processors.dtsi>
#include <zephyr/dt-bindings/input/input-event-codes.h>

#define DEF 0
#define NAV 1
#define FN 2
#define NUM 3
#define SYS 4
#define MOUSE 5

#define KEYS_L 0 1 2 3 4 10 11 12 13 14 20 21 22 23 24
#define KEYS_R 5 6 7 8 9 15 16 17 18 19 25 26 27 28 29
#define THUMBS 30 31 32 33 34 35

#define QUICK_TAP_MS 175
'''


def generate_expanded_keymap(config_dir, commit_hash=None):
    """Generate complete expanded keymap."""
    if commit_hash is None:
        commit_hash = get_git_commit()

    parsed = parse_keymap_files(config_dir)

    output = []
    output.append(generate_header(commit_hash))

    # Mouse settings
    output.append('''
/* Mouse settings */
#define ZMK_POINTING_DEFAULT_MOVE_VAL 600
#define ZMK_POINTING_DEFAULT_SCRL_VAL 20

&mmv {
    acceleration-exponent = <1>;
    time-to-max-speed-ms = <500>;
    delay-ms = <0>;
};

&msc {
    acceleration-exponent = <0>;
    time-to-max-speed-ms = <300>;
    delay-ms = <0>;
};

#define U_MS_U &mmv MOVE_UP
#define U_MS_D &mmv MOVE_DOWN
#define U_MS_L &mmv MOVE_LEFT
#define U_MS_R &mmv MOVE_RIGHT
#define U_WH_U &msc SCRL_UP
#define U_WH_D &msc SCRL_DOWN
#define U_WH_L &msc SCRL_LEFT
#define U_WH_R &msc SCRL_RIGHT
''')

    # Start root node
    output.append('/ {')

    # Behaviors section
    output.append('    behaviors {')

    # Sticky key config
    output.append('''        sk {
            release-after-ms = <900>;
            quick-release;
        };

        sl {
            ignore-modifiers;
        };

        lt {
            flavor = "balanced";
            tapping-term-ms = <200>;
            quick-tap-ms = <QUICK_TAP_MS>;
        };

        mt {
            flavor = "tap-preferred";
            tapping-term-ms = <220>;
            quick-tap-ms = <220>;
            hold-trigger-key-positions = <0>;
        };
''')

    # Homerow mods
    output.append('''        /* Homerow mods */
        hml: hml {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&kp>, <&kp>;
            flavor = "balanced";
            tapping-term-ms = <280>;
            quick-tap-ms = <QUICK_TAP_MS>;
            require-prior-idle-ms = <150>;
            hold-trigger-on-release;
            hold-trigger-key-positions = <KEYS_R THUMBS>;
        };

        hmr: hmr {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&kp>, <&kp>;
            flavor = "balanced";
            tapping-term-ms = <280>;
            quick-tap-ms = <QUICK_TAP_MS>;
            require-prior-idle-ms = <150>;
            hold-trigger-on-release;
            hold-trigger-key-positions = <KEYS_L THUMBS>;
        };
''')

    # HRM combo behaviors (generated from 8-arg combos)
    hrm_combos = []

    # Nav cluster behaviors
    output.append('''        /* Nav cluster */
        masked_home: masked_home {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp HOME>, <&kp HOME>;
            mods = <(MOD_LCTL)>;
        };

        masked_end: masked_end {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp END>, <&kp END>;
            mods = <(MOD_LCTL)>;
        };

        mt_home: mt_home {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&masked_home>, <&kp>;
            flavor = "tap-preferred";
            tapping-term-ms = <220>;
            quick-tap-ms = <220>;
            hold-trigger-key-positions = <0>;
        };

        mt_end: mt_end {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&masked_end>, <&kp>;
            flavor = "tap-preferred";
            tapping-term-ms = <220>;
            quick-tap-ms = <220>;
            hold-trigger-key-positions = <0>;
        };
''')

    # Magic shift and smart behaviors
    output.append('''        /* Magic shift & smart behaviors */
        magic_shift: magic_shift {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&kp>, <&magic_shift_tap>;
            flavor = "balanced";
            tapping-term-ms = <200>;
            quick-tap-ms = <QUICK_TAP_MS>;
        };

        magic_shift_tap: magic_shift_tap {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&shift_repeat>, <&caps_word>;
            mods = <(MOD_LSFT)>;
        };

        shift_repeat: shift_repeat {
            compatible = "zmk,behavior-adaptive-key";
            #binding-cells = <0>;
            bindings = <&sk LSHFT>;
            repeat {
                trigger-keys = <A B C D E F G H I J K L M N O P Q R S T U V W X Y Z>;
                bindings = <&key_repeat>;
                max-prior-idle-ms = <1200>;
                strict-modifiers;
            };
        };

        smart_num: smart_num {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&mo>, <&num_dance>;
            flavor = "balanced";
            tapping-term-ms = <200>;
            quick-tap-ms = <QUICK_TAP_MS>;
        };

        num_dance: num_dance {
            compatible = "zmk,behavior-tap-dance";
            #binding-cells = <0>;
            bindings = <&num_word NUM>, <&sl NUM>;
            tapping-term-ms = <200>;
        };

        smart_mouse: smart_mouse {
            compatible = "zmk,behavior-tri-state";
            #binding-cells = <0>;
            bindings = <&tog MOUSE>, <&none>, <&tog MOUSE>;
            ignored-key-positions = <LT1 LT2 LH0 LH1 RT1 RT2 RT3 RM0 RM1 RM2 RM3 RM4 RB1 RB2 RB3 RH0 RH1>;
            ignored-layers = <MOUSE NAV FN>;
        };
''')

    # Morphs and other behaviors
    output.append('''        /* Morphs */
        comma_morph: comma_morph {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp COMMA>, <&comma_inner_morph>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };

        comma_inner_morph: comma_inner_morph {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp SEMICOLON>, <&kp LESS_THAN>;
            mods = <(MOD_LCTL|MOD_RCTL)>;
        };

        dot_morph: dot_morph {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp DOT>, <&dot_inner_morph>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };

        dot_inner_morph: dot_inner_morph {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp COLON>, <&kp GREATER_THAN>;
            mods = <(MOD_LCTL|MOD_RCTL)>;
        };

        qexcl: qexcl {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp QMARK>, <&kp EXCL>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };

        lpar_lt: lpar_lt {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp LPAR>, <&kp LT>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };

        rpar_gt: rpar_gt {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp RPAR>, <&kp GT>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };

        lt_spc: lt_spc {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            bindings = <&mo>, <&spc_morph>;
            flavor = "balanced";
            tapping-term-ms = <200>;
            quick-tap-ms = <QUICK_TAP_MS>;
        };

        spc_morph: spc_morph {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp SPACE>, <&dot_spc>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };

        bs_del: bs_del {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp BSPC>, <&kp DEL>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
            keep-mods = <MOD_RSFT>;
        };

        copy_cut: copy_cut {
            compatible = "zmk,behavior-tap-dance";
            #binding-cells = <0>;
            bindings = <&kp LC(INS)>, <&kp LC(X)>;
            tapping-term-ms = <200>;
        };

        swapper: swapper {
            compatible = "zmk,behavior-tri-state";
            #binding-cells = <0>;
            bindings = <&kt LALT>, <&kp TAB>, <&kt LALT>;
            ignored-key-positions = <LT2 RT2 RM1 RM2 RM3>;
        };
''')

    # Macros
    output.append('''        /* Macros */
        dot_spc: dot_spc {
            compatible = "zmk,behavior-macro";
            #binding-cells = <0>;
            wait-ms = <0>;
            tap-ms = <5>;
            bindings = <&kp DOT &kp SPACE &sk LSHFT>;
        };

        leader_sft: leader_sft {
            compatible = "zmk,behavior-macro";
            #binding-cells = <0>;
            bindings = <&sk LSHFT &leader>;
        };
''')

    # Leader key with sequences
    if parsed['leader_sequences']:
        output.append('')
        output.append(expand_leader_sequences(parsed['leader_sequences']))

    # HRM combo behaviors (if any 8-arg combos)
    for combo in parsed['combos']:
        if combo['hold'] and combo['side']:
            side_positions = KEYS_L if combo['side'] == 'KEYS_L' else KEYS_R
            hrm = {
                'name': f"hm_combo_{combo['name']}",
                'hold': combo['hold'],
                'tap': combo['binding'],
                'trigger_positions': side_positions + THUMBS,
            }
            output.append('')
            output.append(expand_hrm_combo_behavior(hrm))
            hrm_combos.append(hrm)

    output.append('    };')  # Close behaviors

    # Combos section
    output.append('')
    output.append('    combos {')
    output.append('        compatible = "zmk,combos";')

    for combo in parsed['combos']:
        output.append('')
        output.append(expand_combo(combo, hrm_combos))

    output.append('    };')  # Close combos

    # Conditional layers
    output.append('')
    output.append('''    conditional_layers {
        compatible = "zmk,conditional-layers";
        sys_layer {
            if-layers = <FN NUM>;
            then-layer = <SYS>;
        };
    };''')

    # Keymap (layers) - using urob's Colemak-DH layout
    output.append('')
    output.append('''    keymap {
        compatible = "zmk,keymap";

        layer_Base {
            display-name = "Base";
            bindings = <
//╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮ ╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮
    &kp Q         &kp W         &kp F         &kp P         &kp B           &kp J         &kp L         &kp U         &kp Y         &kp SQT
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &hml LGUI A   &hml LALT R   &hml LSHFT S  &hml LCTRL T  &kp G           &kp M         &hmr LCTRL N  &hmr RSHFT E  &hmr LALT I   &hmr LGUI O
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &kp Z         &kp X         &kp C         &kp D         &kp V           &kp K         &kp H         &comma_morph  &dot_morph    &qexcl
//╰─────────────┼─────────────┴─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┴─────────────┴─────────────╯
                                &none         &lt_spc NAV 0 &lt FN RET      &smart_num NUM 0 &magic_shift LSHFT 0 &none
//                            ╰─────────────┴─────────────┴─────────────╯ ╰─────────────┴─────────────┴─────────────╯
            >;
        };

        layer_Nav {
            display-name = "Nav";
            bindings = <
//╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮ ╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮
    &kp LA(F4)    &trans        &kp LS(TAB)   &swapper      &trans          &kp PG_UP     &mt LC(BSPC) BSPC &mt LC(HOME) UP &mt LC(DEL) DEL &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &sk LGUI      &sk LALT      &sk LSHFT     &sk LCTRL     &trans          &kp PG_DN     &mt_home 0 LEFT &mt LC(END) DOWN &mt_end 0 RIGHT &kp RET
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &trans        &trans        &trans        &trans        &trans          &kp INS       &kp TAB       &trans        &trans        &trans
//╰─────────────┼─────────────┴─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┴─────────────┴─────────────╯
                                &trans        &trans        &trans          &trans        &kp K_CANCEL  &trans
//                            ╰─────────────┴─────────────┴─────────────╯ ╰─────────────┴─────────────┴─────────────╯
            >;
        };

        layer_Fn {
            display-name = "Fn";
            bindings = <
//╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮ ╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮
    &kp F12       &kp F7        &kp F8        &kp F9        &trans          &trans        &kp C_PREV    &kp C_VOL_UP  &kp C_NEXT    &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &hml LGUI F11 &hml LALT F4  &hml LSHFT F5 &hml LCTRL F6 &trans          &trans        &hmr LCTRL LG(LC(LEFT)) &hmr RSHFT C_VOL_DN &hmr LALT LG(LC(RIGHT)) &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &kp F10       &kp F1        &kp F2        &kp F3        &trans          &kp LG(LC(LS(A))) &kp LG(LC(LS(Q))) &kp LA(GRAVE) &trans &trans
//╰─────────────┼─────────────┴─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┴─────────────┴─────────────╯
                                &trans        &trans        &trans          &kp C_MUTE    &kp C_PP      &trans
//                            ╰─────────────┴─────────────┴─────────────╯ ╰─────────────┴─────────────┴─────────────╯
            >;
        };

        layer_Num {
            display-name = "Num";
            bindings = <
//╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮ ╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮
    &trans        &kp N7        &kp N8        &kp N9        &trans          &trans        &trans        &trans        &trans        &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &hml LGUI N0  &hml LALT N4  &hml LSHFT N5 &hml LCTRL N6 &trans          &trans        &trans        &trans        &trans        &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &trans        &kp N1        &kp N2        &kp N3        &trans          &trans        &trans        &trans        &trans        &trans
//╰─────────────┼─────────────┴─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┴─────────────┴─────────────╯
                                &trans        &trans        &trans          &trans        &trans        &trans
//                            ╰─────────────┴─────────────┴─────────────╯ ╰─────────────┴─────────────┴─────────────╯
            >;
        };

        layer_Sys {
            display-name = "Sys";
            bindings = <
//╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮ ╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮
    &bt BT_SEL 0  &bt BT_SEL 1  &bt BT_SEL 2  &bt BT_SEL 3  &bt BT_CLR      &trans        &trans        &trans        &trans        &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &trans        &trans        &trans        &trans        &bootloader     &bootloader   &trans        &trans        &trans        &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &trans        &trans        &trans        &trans        &sys_reset      &sys_reset    &trans        &trans        &trans        &trans
//╰─────────────┼─────────────┴─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┴─────────────┴─────────────╯
                                &trans        &trans        &trans          &trans        &trans        &trans
//                            ╰─────────────┴─────────────┴─────────────╯ ╰─────────────┴─────────────┴─────────────╯
            >;
        };

        layer_Mouse {
            display-name = "Mouse";
            bindings = <
//╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮ ╭─────────────┬─────────────┬─────────────┬─────────────┬─────────────╮
    &trans        &trans        &trans        &trans        &trans          &trans        &kp PG_UP     U_MS_U        &kp PG_DN     &trans
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &trans        &trans        &trans        &trans        &trans          U_WH_L        U_MS_L        U_MS_D        U_MS_R        U_WH_R
//├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    &trans        &trans        &trans        &trans        &trans          &trans        &mkp LCLK     &mkp MCLK     &mkp RCLK     &trans
//╰─────────────┼─────────────┴─────────────┼─────────────┼─────────────┤ ├─────────────┼─────────────┼─────────────┴─────────────┴─────────────╯
                                &trans        &trans        &trans          U_WH_U        U_WH_D        &trans
//                            ╰─────────────┴─────────────┴─────────────╯ ╰─────────────┴─────────────┴─────────────╯
            >;
        };
    };''')

    output.append('};')  # Close root

    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(description='Expand ZMK keymap macros to DTS format')
    parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    parser.add_argument('--commit', '-c', help='Override commit hash in header')
    parser.add_argument('--config-dir', '-d', default='config', help='Config directory (default: config)')

    args = parser.parse_args()

    config_dir = Path(args.config_dir)
    if not config_dir.exists():
        print(f"Error: Config directory not found: {config_dir}", file=sys.stderr)
        sys.exit(1)

    expanded = generate_expanded_keymap(config_dir, args.commit)

    if args.output:
        Path(args.output).write_text(expanded)
        print(f"Expanded keymap written to: {args.output}", file=sys.stderr)
    else:
        print(expanded)


if __name__ == '__main__':
    main()
