# Dasbob Keyboard Configuration

This directory contains a standalone, Editor-native keymap for the Dasbob keyboard.

## Why Standalone?

Nick Coutsos' [Keymap Editor](https://nickcoutsos.github.io/keymap-editor/) requires:
- A single root node in the keymap file
- All behaviors and combos defined as explicit DTS nodes (not C preprocessor macros)

urob's zmk-config uses helper macros (`ZMK_COMBO`, `ZMK_HOLD_TAP`, etc.) that expand at compile time. The Editor cannot parse these, so we expand them manually into standard DTS format using `scripts/expand_keymap.py`.

## Files

- `dasbob.keymap` - Active keymap. Edit in Keymap Editor or by hand.
- `dasbob_urob_baseline.keymap` - Auto-generated vanilla urob config (Colemak-DH). Always matches upstream.
- `SYNC_LOG.md` - Record of sync decisions (accepted/rejected changes).

## Features

Ported from urob's config:
- Homerow mods (hml/hmr) with positional filtering
- Smart behaviors: numword, smart_mouse, magic_shift
- Leader key with German umlauts (ä, ö, ü, ß)
- 28+ combos for common operations
- Swapper (alt-tab) behavior
- Conditional layers

Dasbob-specific:
- Workman alpha layout (Base) with Graphite and QWERTY overlays (mutually exclusive toggles on Sys)
- Autoshift on punctuation (;,./\) on Base/QWERTY; Graphite uses `as_pair` for layout-specific tap/hold symbols
- Comma/question on NUM layer pos 25 (below apostrophe column)
- Inner thumbs: space on LH1 (31), backspace/del on RH1 (34)
- UNDER added to numword continue-list

## Upstream Sync Workflow

### 1. Pull upstream changes

```bash
git fetch upstream
git merge upstream/main
```

### 2. Re-generate baseline

```bash
python scripts/expand_keymap.py --config-dir config --output config/dasbob_urob_baseline.keymap
```

### 3. See what urob changed this sync

```bash
git diff HEAD~1 -- config/dasbob_urob_baseline.keymap
```

### 4. Compare baseline to your keymap

```bash
diff config/dasbob_urob_baseline.keymap config/dasbob.keymap
```

This shows ALL differences: your customizations + rejected upstream changes.

### 5. Decide on new changes

For each new upstream change:
- **Accept**: Port to `dasbob.keymap`, adapting for Workman layout
- **Reject**: Note in `SYNC_LOG.md` with reason

### 6. Commit and test

```bash
git add config/dasbob_urob_baseline.keymap config/dasbob.keymap config/SYNC_LOG.md
git commit -m "Sync upstream urob/zmk-config"
git push  # Triggers CI build
```

## Keymap Editor Usage

1. Open https://nickcoutsos.github.io/keymap-editor/
2. Connect your GitHub repo
3. Select `config/dasbob.keymap`
4. Edit layers, combos, and behaviors visually
5. Commit changes through the Editor

The Editor can modify:
- Layer bindings
- Combo triggers and bindings
- Basic behavior parameters

It cannot modify:
- Complex macro definitions
- Leader key sequences
- Conditional layer logic

For those, edit `dasbob.keymap` directly.

## Build

CI builds automatically on push to `config/**` or `build.yaml`.

Local build requires nix:
```bash
nix build
```

Firmware outputs to `firmware/` directory.

## Parser

The `scripts/expand_keymap.py` script expands urob's macro-based config to Editor-compatible DTS:

```bash
# Generate baseline (vanilla urob)
python scripts/expand_keymap.py --config-dir config --output config/dasbob_urob_baseline.keymap

# Preview to stdout
python scripts/expand_keymap.py --config-dir config
```

If urob adds new macro types, the parser may need updates.
