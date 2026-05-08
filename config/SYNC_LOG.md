# Upstream Sync Log

Record of sync decisions when pulling from urob/zmk-config.

Format:
```
## YYYY-MM-DD - urob/zmk-config@<commit>

### Accepted
- Description of accepted change

### Rejected
- Description of rejected change (reason)
```

---

## 2026-05-08 - Initial Setup

### Baseline
- Generated `dasbob_urob_baseline.keymap` from current urob config
- Created `dasbob.keymap` with Workman layout modifications

### Dasbob Customizations (vs baseline)
- Workman alpha layout (instead of Colemak-DH)
- Autoshift on punctuation (;,./\) - replaces comma_morph/dot_morph
- UNDER added to numword continue-list
- German umlauts only (Greek letters available but not needed)
