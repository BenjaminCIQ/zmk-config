default:
    @just --list --unsorted

config := absolute_path('config')
build := absolute_path('.build')
out := absolute_path('firmware')
draw := absolute_path('draw')

build_matrix := "build.yaml"

# parse build.yaml and filter targets by expression
_parse_targets $expr: _check_yq_version
    #!/usr/bin/env bash
    attrs="[.board, .shield, .snippet, .\"artifact-name\", .\"cmake-args\"]"
    filter="(($attrs | map(. // [.]) | combinations), ((.include // {})[] | $attrs)) | join(\",\")"
    echo "$(yq -r "$filter" {{build_matrix}} | grep -v "^," | grep -i "${expr/#all/.*}")"

# build firmware for single board & shield combination
_build_single $board $shield $snippet $artifact cmake_args *west_args:
    #!/usr/bin/env bash
    set -euo pipefail
    artifact="${artifact:-${shield:+${shield// /+}-}${board//\//_}}"
    build_dir="{{ build / '$artifact' }}"

    echo "Building firmware for $artifact..."
    west build -s zmk/app -d "$build_dir" -b $board {{ west_args }} ${snippet:+-S "$snippet"} -- \
        -DZMK_CONFIG="{{ config }}" ${shield:+-DSHIELD="$shield"} {{ cmake_args }}

    if [[ -f "$build_dir/zephyr/zmk.uf2" ]]; then
        mkdir -p "{{ out }}" && cp "$build_dir/zephyr/zmk.uf2" "{{ out }}/$artifact.uf2"
    else
        mkdir -p "{{ out }}" && cp "$build_dir/zephyr/zmk.bin" "{{ out }}/$artifact.bin"
    fi

# build firmware for matching targets
build expr *west_args:
    #!/usr/bin/env bash
    set -euo pipefail
    targets=$(just build_matrix={{build_matrix}} _parse_targets {{ expr }})

    [[ -z $targets ]] && echo "No matching targets found. Aborting..." >&2 && exit 1
    echo "$targets" | while IFS=, read -r board shield snippet artifact cmake_args; do
        just _build_single "$board" "$shield" "$snippet" "$artifact" "$cmake_args" {{ west_args }}
    done

# clear build cache and artifacts
clean:
    rm -rf {{ build }} {{ out }}

# clear all automatically generated files
clean-all: clean
    rm -rf .west zmk

# clear nix cache
clean-nix:
    nix-collect-garbage --delete-old

# parse & plot keymap (auto-detects layers from parsed keymap)
draw: _check_yq_version
    #!/usr/bin/env bash
    set -euo pipefail
    keymap -c "{{ draw }}/config.yaml" parse -z "{{ config }}/dasbob.keymap" --virtual-layers Combos >"{{ draw }}/dasbob.yaml"
    yq -Yi '.combos.[].l = ["Combos"]' "{{ draw }}/dasbob.yaml"
    keymap -c "{{ draw }}/config.yaml" draw "{{ draw }}/dasbob.yaml" -n "33333+3 3+33333" >"{{ draw }}/dasbob.svg"

    jq_expr='
        def extract_label: if type == "string" then . else .t end;
        def is_transparent: type == "object" and (.type == "trans" or .type == "held");

        # Get layer names dynamically (exclude Combos virtual layer)
        (.layers | keys | map(select(. != "Combos"))) as $layer_names |
        ($layer_names[0] // "Base") as $base_name |
        ($layer_names[1] // null) as $l1_name |
        ($layer_names[2] // null) as $l2_name |
        ($layer_names[3] // null) as $l3_name |
        ($layer_names[4] // null) as $l4_name |

        # Build layer arrays conditionally
        [.layers[$base_name]] as $base_arr |
        (if $l1_name then [.layers[$l1_name]] else [] end) as $l1_arr |
        (if $l2_name then [.layers[$l2_name]] else [] end) as $l2_arr |
        (if $l3_name then [.layers[$l3_name]] else [] end) as $l3_arr |
        (if $l4_name then [.layers[$l4_name]] else [] end) as $l4_arr |

        .layers = {
        ($base_name): [
            ($base_arr + $l1_arr + $l2_arr + $l3_arr + $l4_arr) | transpose[] |
            (.[0] | if type == "string" then {t: .} else . end) as $base |
            (.[1] // null | if . == null or is_transparent then null else extract_label end) as $l1 |
            (.[2] // null | if . == null or is_transparent then null else extract_label end) as $l2 |
            (.[3] // null | if . == null or is_transparent then null else extract_label end) as $l3 |
            (.[4] // null | if . == null or is_transparent then null else extract_label end) as $l4 |
            $base
            + (if $l1 == null then {} else {tr: $l1} end)
            + (if $l2 == null then {} else {tl: $l2} end)
            + (if $l3 == null then {} else {bl: $l3} end)
            + (if $l4 == null then {} else {br: $l4} end)
        ],
        Combos: .layers.Combos
        } |
        .combos = [.combos[] | .l = ["Combos"]]
    '
    yq -y "$jq_expr" "{{ draw }}/dasbob.yaml" >"{{ draw }}/overview.yaml"
    keymap -c "{{ draw }}/config.yaml" draw "{{ draw }}/overview.yaml" -n "33333+3 3+33333" >"{{ draw }}/overview.svg"
    sed -i '/<text.*class="label"/d' "{{ draw }}/overview.svg"

# initialize west
init:
    west init -l config
    west update --fetch-opt=--filter=blob:none
    west zephyr-export

# List build targets. The sed chain removes version and build variants,
# and prints the shield (if given) or otherwise the board name.
list:
    @just build_matrix={{build_matrix}} _parse_targets all \
        | sed 's|[@/][^,]*,|,|' \
        | sed 's|\([^,]*\),\([^,]\+\),.*|\2|' \
        | sed 's|\([^,]*\),,.*|\1|' \
        | sort \
        | column

# update west
update:
    west update --fetch-opt=--filter=blob:none

# upgrade zephyr-sdk and python dependencies
upgrade-sdk:
    nix flake update --flake .

# warn user if they are using golang-yq and not python-yq
[no-exit-message]
_check_yq_version:
    #!/usr/bin/env bash
    if yq --help 2>&1 | grep -qi 'eval'; then
        echo "This script requires python-yq, but PATH contains golang-yq" >&2
        echo "Please install python-yq or use the included nix shell" >&2
        exit 1
    fi

[no-cd]
test $testpath *FLAGS:
    #!/usr/bin/env bash
    set -euo pipefail
    testcase=$(basename "$testpath")
    build_dir="{{ build / "tests" / '$testcase' }}"
    config_dir="{{ '$(pwd)' / '$testpath' }}"
    cd {{ justfile_directory() }}

    if [[ "{{ FLAGS }}" != *"--no-build"* ]]; then
        echo "Running $testcase..."
        rm -rf "$build_dir"
        west build -s zmk/app -d "$build_dir" -b native_sim//zmk_test_mock -- \
            -DCONFIG_ASSERT=y -DZMK_CONFIG="$config_dir"
    fi

    ${build_dir}/zephyr/zmk.exe | sed -e "s/.*> //" |
        tee ${build_dir}/keycode_events.full.log |
        sed -n -f ${config_dir}/events.patterns > ${build_dir}/keycode_events.log
    if [[ "{{ FLAGS }}" == *"--verbose"* ]]; then
        cat ${build_dir}/keycode_events.log
    fi

    if [[ "{{ FLAGS }}" == *"--auto-accept"* ]]; then
        cp ${build_dir}/keycode_events.log ${config_dir}/keycode_events.snapshot
    fi
    diff -auZ ${config_dir}/keycode_events.snapshot ${build_dir}/keycode_events.log
