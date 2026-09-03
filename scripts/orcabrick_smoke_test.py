#!/usr/bin/env python3
"""Prove that OrcaBrick creates real staggered, extruding wall paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

LAYER_HEIGHT_MM = 0.2
MOTION_RE = re.compile(r"^\s*G(?:0|1|2|3)\b", re.IGNORECASE)
WORD_RE = re.compile(
    r"(?:^|\s)([XYZE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))",
    re.IGNORECASE,
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def profile_index(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in directory.glob("*.json"):
        data = load_json(path)
        name = data.get("name")
        if isinstance(name, str) and name:
            result[name] = path
        result.setdefault(path.stem, path)
    return result


def resolve_profile(path: Path) -> dict[str, Any]:
    index = profile_index(path.parent)
    visiting: set[Path] = set()

    def resolve(current: Path) -> dict[str, Any]:
        current = current.resolve()
        if current in visiting:
            raise RuntimeError(f"Profile inheritance cycle at {current}")
        visiting.add(current)
        child = load_json(current)
        inherited = child.get("inherits")
        merged: dict[str, Any] = {}
        if isinstance(inherited, str) and inherited:
            parent = index.get(inherited)
            if parent is None:
                raise RuntimeError(
                    f"Cannot resolve inherited profile {inherited!r} for {current.name}"
                )
            merged.update(resolve(parent))
        merged.update(child)
        merged.pop("inherits", None)
        visiting.remove(current)
        return merged

    return resolve(path)


def write_profile(path: Path, profile: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_slice(
    executable: Path,
    model: Path,
    machine: Path,
    process: Path,
    filament: Path,
    output_directory: Path,
) -> str:
    output_directory.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "--debug",
        "3",
        "--slice",
        "0",
        "--no-check",
        "--allow-newer-file",
        "--load-settings",
        f"{machine};{process}",
        "--load-filaments",
        str(filament),
        "--outputdir",
        str(output_directory),
        str(model),
    ]
    completed = subprocess.run(
        command,
        cwd=executable.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    (output_directory / "slice-stdout.txt").write_text(
        completed.stdout, encoding="utf-8", errors="replace"
    )
    (output_directory / "slice-stderr.txt").write_text(
        completed.stderr, encoding="utf-8", errors="replace"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "OrcaBrick CLI slicing failed with exit code "
            f"{completed.returncode}; see saved stdout/stderr"
        )

    raw_gcode = sorted(output_directory.rglob("*.gcode"))
    if raw_gcode:
        return raw_gcode[0].read_text(encoding="utf-8", errors="replace")

    archives = sorted(output_directory.rglob("*.3mf"))
    for archive in archives:
        if not zipfile.is_zipfile(archive):
            continue
        with zipfile.ZipFile(archive) as package:
            names = [
                name for name in package.namelist() if name.lower().endswith(".gcode")
            ]
            if names:
                return package.read(names[0]).decode("utf-8", errors="replace")

    raise RuntimeError(
        f"Slicing succeeded but produced no readable G-code under {output_directory}"
    )


def motion_words(raw_line: str) -> dict[str, float]:
    command = raw_line.split(";", 1)[0]
    if not MOTION_RE.search(command):
        return {}
    return {axis.upper(): float(value) for axis, value in WORD_RE.findall(command)}


def motion_z_values(gcode: str) -> list[float]:
    return [
        words["Z"]
        for raw_line in gcode.splitlines()
        if (words := motion_words(raw_line)) and "Z" in words
    ]


def rounded_unique(values: list[float]) -> list[float]:
    return sorted({round(value, 5) for value in values})


def staggered_events(gcode: str) -> list[dict[str, Any]]:
    """Find real half-layer inner-wall extrusion without relying on comments.

    TYPE comments describe the active extrusion role and normally appear before
    the travel to a perimeter. Every explicit half-layer Z move is followed
    until the next Z change; it counts only when an XY+E extrusion occurs while
    the active role is Inner wall.
    """
    lines = gcode.splitlines()
    events: list[dict[str, Any]] = []
    active_type: str | None = None

    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.lower().startswith(";type:"):
            active_type = stripped.split(":", 1)[1].strip()

        words = motion_words(raw_line)
        z_value = words.get("Z")
        if z_value is None or not is_between_nominal_layers(z_value):
            continue

        extrusion_type = active_type
        extrudes_before_next_z = False
        extrusion_line = None
        for later_index in range(index + 1, len(lines)):
            later_line = lines[later_index]
            later_stripped = later_line.strip()
            if later_stripped.lower().startswith(";type:"):
                extrusion_type = later_stripped.split(":", 1)[1].strip()

            later_words = motion_words(later_line)
            if not later_words:
                continue
            if "Z" in later_words:
                break
            if (
                ("X" in later_words or "Y" in later_words)
                and "E" in later_words
                and later_words["E"] > 0
            ):
                extrudes_before_next_z = True
                extrusion_line = later_index + 1
                break

        events.append(
            {
                "z_move_line": index + 1,
                "z_mm": z_value,
                "extrudes_before_next_z": extrudes_before_next_z,
                "first_extrusion_line": extrusion_line,
                "extrusion_type": extrusion_type,
                "is_inner_wall": (extrusion_type or "").lower() == "inner wall",
            }
        )
    return events


def is_between_nominal_layers(value: float) -> bool:
    scaled = value / LAYER_HEIGHT_MM
    return abs(scaled - round(scaled)) > 0.25


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def parser_self_test() -> None:
    off = "G1 Z0.2 ; ensure Z matches planned layer height\nG1 X10 Y0 E0.5\n"
    on = (
        ";TYPE:Inner wall\n"
        "G1 X0 Y0 Z0.3\n"
        "G1 E0.1\n"
        "G1 X10 Y0 E0.5\n"
        "G1 Z0.4\n"
    )
    assert staggered_events(off) == []
    events = staggered_events(on)
    assert len(events) == 1
    assert events[0]["z_mm"] == 0.3
    assert events[0]["extrudes_before_next_z"]
    assert events[0]["is_inner_wall"]
    assert is_between_nominal_layers(0.3)
    assert not is_between_nominal_layers(0.4)

    outer = (
        ";TYPE:Outer wall\n"
        "G1 X0 Y0 Z0.3\n"
        "G1 X10 Y0 E0.5\n"
    )
    assert len(staggered_events(outer)) == 1
    assert not staggered_events(outer)[0]["is_inner_wall"]


def source_self_test(repository: Path) -> None:
    """Catch version and packaging drift before starting the hour-long build."""
    version_text = (repository / "version.inc").read_text(encoding="utf-8")
    build_match = re.search(r'set\(ORCABRICK_BUILD\s+"([0-9]+)"\)', version_text)
    version_match = re.search(
        r'set\(SoftFever_VERSION\s+"([^"]+)"\)', version_text
    )
    if build_match is None or version_match is None:
        raise RuntimeError("version.inc is missing OrcaBrick build metadata")

    build = build_match.group(1)
    version = version_match.group(1)
    if "${" in version:
        raise RuntimeError(
            "SoftFever_VERSION must be literal because GitHub Actions reads "
            "version.inc without evaluating CMake variables"
        )
    expected_suffix = f"+OrcaBrick{build}"
    if not version.endswith(expected_suffix):
        raise RuntimeError(
            f"SoftFever_VERSION {version!r} does not match ORCABRICK_BUILD {build}"
        )

    cmake_text = (repository / "CMakeLists.txt").read_text(encoding="utf-8")
    expected_cpack = 'set (CPACK_PACKAGE_FILE_NAME "OrcaBrick_Setup")'
    if expected_cpack not in cmake_text:
        raise RuntimeError("CMake installer name is not the stable OrcaBrick name")

    workflow_text = (
        repository / ".github" / "workflows" / "build_orca.yml"
    ).read_text(encoding="utf-8")
    expected_upload = (
        "${{ github.workspace }}/${{ env.BUILD_DIR }}/"
        "OrcaBrick_Setup${{ env.ARCH_SUFFIX }}.exe"
    )
    if expected_upload not in workflow_text:
        raise RuntimeError("Installer artifact upload path does not match CPack output")
    if workflow_text.index("Prove Bricklaying changes sliced G-code") > workflow_text.index(
        "Create installer Win"
    ):
        raise RuntimeError("Bricklaying proof must run before installer creation")

    # Every OrcaBrick build must ship an installable for Windows *and* Linux.
    orcabrick_workflow = (
        repository / ".github" / "workflows" / "orcabrick_windows.yml"
    ).read_text(encoding="utf-8")
    # ThumbnailsParams holds a const member with no initialiser, so default-initialising it is
    # ill-formed wherever std::vector's default constructor is not user-provided - which is the
    # case on Ubuntu 22.04's libstdc++ 11. It compiled on 24.04 by luck and broke the
    # older-glibc AppImage build. Every other site brace-initialises it; keep it that way.
    if "ThumbnailsParams thumbnail_params;" in (
        repository / "src" / "OrcaSlicer.cpp"
    ).read_text(encoding="utf-8"):
        raise RuntimeError(
            "src/OrcaSlicer.cpp default-initialises ThumbnailsParams, which does not compile "
            "against libstdc++ 11; brace-initialise it or drop it if it is unused"
        )

    # A variable reference's iterator range covers its subscript ("foo[0]"), so looking it up
    # in print_config_def returns nullptr for every indexed access. The asserts that guarded
    # that are compiled out of a release build and the next line dereferences the null, so a
    # percent value read as {option[index]} used to segfault. Keep the subscript stripped.
    parser_source = (repository / "src" / "libslic3r" / "PlaceholderParser.cpp").read_text(
        encoding="utf-8"
    )
    if "config_key_of(opt)" not in parser_source or parser_source.count(
        "std::string opt_key(opt.it_range.begin(), opt.it_range.end());"
    ):
        raise RuntimeError(
            "PlaceholderParser builds a config key straight from the variable's iterator "
            "range again; an indexed percent value will dereference a null ConfigOptionDef"
        )

    # config.option<T>() returns nullptr when the stored option is not a T - it cannot cast a
    # scalar into a vector - and small_perimeter_speed is a scalar unless the printer declares
    # extruder variants. Writing through that pointer segfaulted the whole test binary.
    if 'option<ConfigOptionFloatsOrPercentsNullable>("small_perimeter_speed")' in (
        repository / "tests" / "libslic3r" / "test_placeholder_parser.cpp"
    ).read_text(encoding="utf-8"):
        raise RuntimeError(
            "tests/libslic3r/test_placeholder_parser.cpp casts the scalar small_perimeter_speed "
            "into a vector option; install the vector with set_key_value instead"
        )

    # The Linux build resolves webkit from the host, so the ABI the deps script installs is the
    # ABI every distro running the AppImage must have. It has to match what CMake requires, or
    # the build fails at configure time on distros carrying both, and the AppImage refuses to
    # start on Arch, Fedora and Debian 13, which ship only 4.1.
    cmake_webkit = re.search(
        r"pkg_check_modules\(webkit2gtk REQUIRED webkit2gtk-([0-9.]+)\)",
        (repository / "src" / "slic3r" / "CMakeLists.txt").read_text(encoding="utf-8"),
    )
    if cmake_webkit is None:
        raise RuntimeError("src/slic3r/CMakeLists.txt no longer states a webkit2gtk ABI")
    debian_deps = (repository / "scripts" / "linux.d" / "debian").read_text(encoding="utf-8")
    preferred = re.search(r'apt show --quiet libwebkit2gtk-([0-9.]+)-dev', debian_deps)
    if preferred is None or preferred.group(1) != cmake_webkit.group(1):
        raise RuntimeError(
            f"scripts/linux.d/debian prefers webkit2gtk-{preferred.group(1) if preferred else '?'} "
            f"but the build requires {cmake_webkit.group(1)}"
        )

    for job, marker in (("build_windows_x64", "windows-latest"),
                        ("build_linux_x86_64", "ubuntu-24.04"),
                        # the AppImage for distros older than Ubuntu 24.04; without it the
                        # only Linux build links against glibc 2.39 and refuses to start on
                        # Debian 12, Ubuntu 22.04, Mint 21 or openSUSE Leap
                        ("build_linux_x86_64_compat", "ORCA_DOCKER_BASE_IMAGE: ubuntu:22.04"),
                        # without this job the unit tests compile nowhere and run nowhere:
                        # CMake defaults BUILD_TESTS to OFF and no build leg passes -t or ctest
                        ("unit_tests", "scripts/run_unit_tests.sh")):
        if job not in orcabrick_workflow or marker not in orcabrick_workflow:
            raise RuntimeError(
                f"OrcaBrick workflow lost the {job} job ({marker}); the Windows installer, "
                "both Linux AppImages and the unit tests are all required"
            )

    # For nine builds the only thing CI ran from this script was --self-test, which reads
    # sources and slices nothing, so nothing ever checked that Bricklaying reaches the G-code.
    # Keep the proof wired to a real binary.
    if "--exe build/package/bin/orca-slicer" not in orcabrick_workflow:
        raise RuntimeError(
            "no job runs the G-code proof against a built slicer any more; without it a wrong "
            "Preview cannot be told apart from a wrong slice"
        )

    # The cache action re-evaluates its key in the post-job save step, once the build has filled
    # deps/build with the installed dependency tree; hashing deps/** then fails and takes the
    # whole job down after the AppImage has already been built and uploaded. Builds 27 and 29
    # both died there. The key has to be resolved once, before the build, and passed as a
    # literal.
    if "steps.deps_cache_key.outputs.key" not in orcabrick_workflow:
        raise RuntimeError(
            "the Ubuntu 22.04 job hashes deps/** in its cache key again; its post-job save will "
            "fail once the build has filled deps/build"
        )

    required_source_wiring = {
        "src/libslic3r/PrintConfig.cpp": (
            'this->add("staggered_perimeters", coBool)',
            'this->add("staggered_perimeter_flow_ratio", coFloat)',
        ),
        "src/libslic3r/PerimeterGenerator.cpp": (
            "perimeter_generator.config->staggered_perimeters",
            "cur_path.staggered_z_offset = 0.5",
            # never raise a wall the layer above does not cover
            "if (!is_covered_from_above(cur_path))",
            # never raise a wall on a layer whose height is not the configured one
            "const double configured_layer_height",
        ),
        "src/libslic3r/GCode.cpp": (
            "path.staggered_z_offset * path.height",
            "m_config.staggered_perimeter_flow_ratio",
        ),
        "src/libslic3r/GCode/GCodeProcessor.cpp": (
            "void GCodeProcessor::split_staggered_preview_layers()",
            "split_staggered_preview_layers();",
            # the fail-safe: never commit a renumbering that breaks libvgcode's binary search
            "if (zs[i] < zs[i - 1])",
            # a scarf or sloped seam ramps through a continuum of Zs and must not be split,
            # but a ragged raised band must still split - path.height varies across a layer
            "clears_the_gap",
            "lowest_raised - nominal_z >= 0.4f * (raised_z - nominal_z)",
            # the renumbering is a static so tests/fff_print/test_orcabrick_preview.cpp can
            # drive it directly instead of the contract being checked only by eye in Preview
            "bool GCodeProcessor::split_staggered_preview_layers(std::vector<GCodeProcessorResult::MoveVertex> &moves,",
        ),
        # The two halves of a Bricklaying layer cover the same moves and differ only in the Z
        # they declare, so the viewer has to be told the Zs and has to cut above them.
        "src/libvgcode/src/Layers.cpp": (
            "void Layers::set_zs(const std::vector<float>& zs, const std::vector<uint8_t>& upper_half)",
            "m_explicit_zs = true;",
        ),
        "src/libvgcode/src/ViewerImpl.cpp": (
            "m_layers.set_zs(gcode_data.layer_zs, gcode_data.layer_upper_half);",
            "const bool  cut_above_layer = m_layers.has_explicit_zs();",
            "if (cut_above_layer && v.position[2] > max_extrusion_z)",
            # without these the layer under the raised step is dimmed to DUMMY_COLOR and the
            # model turns black as the slider passes each half layer
            "m_layers.print_layer_start(m_layers.get_view_range()[1]) : 0;",
            "top_first_it->layer_id < top_layer_start",
        ),
        "src/libvgcode/src/Layers.hpp": (
            "std::size_t print_layer_start(std::size_t layer_id) const",
        ),
        "src/slic3r/GUI/LibVGCode/LibVGCodeWrapper.cpp": (
            "ret.layer_zs = result.preview_layer_zs;",
            "ret.layer_upper_half = result.preview_layer_upper_half;",
        ),
        "tests/fff_print/CMakeLists.txt": (
            "test_orcabrick_preview.cpp",
        ),
        "src/libslic3r/PrintObject.cpp": (
            'opt_key == "staggered_perimeters"',
            'opt_key == "staggered_perimeter_flow_ratio"',
        ),
        "src/slic3r/GUI/Tab.cpp": (
            'append_single_option_line("staggered_perimeters")',
            'append_single_option_line("staggered_perimeter_flow_ratio")',
        ),
        # The themed model colour, and the two places that resolve an automatic filament colour.
        "src/slic3r/GUI/Widgets/StateColor.cpp": (
            "wxColour StateColor::ModelColor()",
        ),
        "src/slic3r/GUI/Preferences.cpp": (
            "PreferencesDialog::create_item_model_color()",
        ),
        "src/slic3r/GUI/3DScene.cpp": (
            "const wxColour accent = StateColor::ModelColor();",
        ),
    }

    # Theme tokens that must never be painted straight onto a device context or a
    # window: those bypass StateColor and so ignore the accent colour entirely.
    unthemed_literals = {
        "src/slic3r/GUI/Widgets/TabCtrl.cpp": ('wxColour c("#009688")',),
        "src/slic3r/GUI/MultiTaskManagerPage.cpp": (
            "dc.SetPen(wxPen(wxColour(0, 150, 136)))",
            "dc.SetTextForeground(wxColour(0, 150, 136))",
        ),
        "src/slic3r/GUI/MultiMachineManagerPage.cpp": (
            "dc.SetPen(wxPen(wxColour(0, 150, 136)))",
        ),
        "src/slic3r/GUI/Widgets/SwitchButton.cpp": (
            "dc.SetBrush(wxBrush(wxColour(0, 150, 136)))",
        ),
        "src/slic3r/GUI/GLSelectionRectangle.cpp": ("set_color(ColorRGBA::ORCA())",),
        "src/slic3r/GUI/IMSlider.cpp": ("BRAND_COLOR",),
    }
    for relative_path, literals in unthemed_literals.items():
        source = (repository / relative_path).read_text(encoding="utf-8")
        present = [literal for literal in literals if literal in source]
        if present:
            raise RuntimeError(
                f"{relative_path} paints a theme token directly, so it ignores the accent "
                f"colour: {', '.join(present)}"
            )

    # The Bricklaying unit test shipped for weeks referencing an ExtrusionRole that does
    # not exist, because no CI leg compiled tests/ until the Linux job was added. Linux
    # now gates it, and this catches the same mistake before a 40-minute build does.
    extrusion_roles = set(
        re.findall(
            r"^\s*(er[A-Za-z]+),",
            (repository / "src" / "libslic3r" / "ExtrusionEntity.hpp").read_text(
                encoding="utf-8"
            ),
            re.M,
        )
    )
    extrusion_test = repository / "tests" / "fff_print" / "test_extrusion_entity.cpp"
    unknown_roles = sorted(
        set(re.findall(r"\ber[A-Z][A-Za-z]*\b", extrusion_test.read_text(encoding="utf-8")))
        - extrusion_roles
    )
    if unknown_roles:
        raise RuntimeError(
            f"{extrusion_test.name} uses ExtrusionRole values that do not exist in "
            f"ExtrusionEntity.hpp: {', '.join(unknown_roles)}"
        )
    if "staggered_z_offset" not in extrusion_test.read_text(encoding="utf-8"):
        raise RuntimeError(
            "The Bricklaying metadata test must cover staggered_z_offset, the field the "
            "feature actually uses; z_offset alone belongs to sloped and scarf paths"
        )
    processor_header = (
        repository / "src" / "libslic3r" / "GCode" / "GCodeProcessor.hpp"
    ).read_text(encoding="utf-8")
    processor_source = (
        repository / "src" / "libslic3r" / "GCode" / "GCodeProcessor.cpp"
    ).read_text(encoding="utf-8")
    gcode_source = (repository / "src" / "libslic3r" / "GCode.cpp").read_text(
        encoding="utf-8"
    )
    preview_sources = processor_header + processor_source + gcode_source
    if "tail_is_raised" in preview_sources:
        raise RuntimeError(
            "split_staggered_preview_layers() must not require the raised walls to be the "
            "layer's tail: perimeters are emitted before infill, so a nominal extrusion always "
            "follows them and no layer would ever be split"
        )
    if "ORCABRICK_LAYER_CHANGE" in preview_sources or "m_preview_layer_id" in preview_sources:
        raise RuntimeError(
            "The G-code marker and the unconditional preview counter are forbidden: they split "
            "every layer regardless of wall order, which is what produced non-monotonic layer "
            "groups and black or vanishing geometry. Preview layers are now split by "
            "GCodeProcessor::split_staggered_preview_layers(), which only splits a layer whose "
            "raised extrusions form a contiguous tail and verifies the resulting Zs first."
        )

    for relative_path, snippets in required_source_wiring.items():
        source = (repository / relative_path).read_text(encoding="utf-8")
        missing = [snippet for snippet in snippets if snippet not in source]
        if missing:
            raise RuntimeError(
                f"{relative_path} is missing OrcaBrick wiring: {', '.join(missing)}"
            )


PREVIEW_SPLIT_RE = re.compile(
    r"OrcaBrick: Preview shows (\d+) layers for (\d+) printed ones \((\d+) split"
)


def preview_split_report(slice_directory: Path) -> dict[str, Any] | None:
    """What GCodeProcessor::split_staggered_preview_layers() did on the real slice.

    It is the one step between "the G-code raises the walls" - which the Z ladders
    below establish - and "Preview shows them on their own slider step". The slicer
    logs it at info level, and run_slice() captures both streams, so read it back
    rather than inferring it from a screenshot.
    """
    for stream in ("slice-stdout.txt", "slice-stderr.txt"):
        path = slice_directory / stream
        if not path.is_file():
            continue
        match = PREVIEW_SPLIT_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            return {
                "stream": stream,
                "preview_layers": int(match.group(1)),
                "printed_layers": int(match.group(2)),
                "split_layers": int(match.group(3)),
            }
    return None


def run_proof(executable: Path, repository: Path, workdir: Path) -> int:
    if not executable.is_file():
        raise RuntimeError(f"OrcaBrick executable not found: {executable}")

    workdir.mkdir(parents=True, exist_ok=True)
    vendor = repository / "resources" / "profiles" / "SecKit"
    machine = resolve_profile(vendor / "machine" / "SecKit Go3 0.4 nozzle.json")
    process = resolve_profile(vendor / "process" / "0.20mm Standard @SecKit.json")
    filament = resolve_profile(vendor / "filament" / "SecKit Generic PLA.json")

    process.update(
        {
            "layer_height": "0.2",
            "initial_layer_print_height": "0.2",
            "wall_generator": "arachne",
            "wall_loops": "3",
            "spiral_mode": "0",
            "alternate_extra_wall": "0",
            "only_one_wall_first_layer": "0",
            "gcode_comments": "1",
            "staggered_perimeter_flow_ratio": "1",
        }
    )
    process_off = dict(process)
    process_off.update(
        {"name": "OrcaBrick proof OFF", "staggered_perimeters": "0"}
    )
    process_on = dict(process)
    process_on.update(
        {"name": "OrcaBrick proof ON", "staggered_perimeters": "1"}
    )

    profiles = workdir / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    machine_path = profiles / "machine.json"
    filament_path = profiles / "filament.json"
    process_off_path = profiles / "process-off.json"
    process_on_path = profiles / "process-on.json"
    write_profile(machine_path, machine)
    write_profile(filament_path, filament)
    write_profile(process_off_path, process_off)
    write_profile(process_on_path, process_on)

    model = repository / "tests" / "data" / "test_stl" / "ASCII" / "20mmbox-LF.stl"
    gcode_off = run_slice(
        executable,
        model,
        machine_path,
        process_off_path,
        filament_path,
        workdir / "off",
    )
    gcode_on = run_slice(
        executable,
        model,
        machine_path,
        process_on_path,
        filament_path,
        workdir / "on",
    )
    (workdir / "brick-off.gcode").write_text(
        gcode_off, encoding="utf-8", errors="replace"
    )
    (workdir / "brick-on.gcode").write_text(
        gcode_on, encoding="utf-8", errors="replace"
    )

    off_events = staggered_events(gcode_off)
    on_events = staggered_events(gcode_on)
    preview_marker = ";ORCABRICK_LAYER_CHANGE"
    off_preview_markers = gcode_off.count(preview_marker)
    on_preview_markers = gcode_on.count(preview_marker)
    event_z_values = [
        float(event["z_mm"]) for event in on_events if event["z_mm"] is not None
    ]
    half_layer_values = rounded_unique(event_z_values)
    non_extruding_events = [
        event for event in on_events if not event["extrudes_before_next_z"]
    ]
    non_inner_wall_events = [event for event in on_events if not event["is_inner_wall"]]

    errors: list[str] = []
    if gcode_on == gcode_off:
        errors.append("Bricklaying ON and OFF produced identical G-code")
    if off_preview_markers:
        errors.append(
            f"Bricklaying OFF unexpectedly contains {off_preview_markers} preview half-layer markers"
        )
    if on_preview_markers:
        errors.append(
            f"Bricklaying ON unexpectedly contains {on_preview_markers} synthetic preview markers"
        )
    if off_events:
        errors.append(
            f"Bricklaying OFF unexpectedly contains {len(off_events)} half-layer perimeter moves"
        )
    if len(on_events) < 5:
        errors.append(
            f"Bricklaying ON contains only {len(on_events)} half-layer perimeter moves; expected at least 5"
        )
    if non_extruding_events:
        errors.append(
            f"{len(non_extruding_events)} half-layer perimeter moves are not followed by XY+E extrusion before the next Z move"
        )
    if non_inner_wall_events:
        errors.append(
            f"{len(non_inner_wall_events)} half-layer perimeter moves do not extrude an Inner wall"
        )
    if len(half_layer_values) < 3:
        errors.append(
            "Bricklaying ON does not contain at least three distinct half-layer perimeter heights"
        )

    summary = {
        "result": "FAIL" if errors else "PASS",
        "errors": errors,
        "model": model.name,
        "layer_height_mm": LAYER_HEIGHT_MM,
        "wall_loops": 3,
        "flow_ratio": 1.0,
        "off_sha256": sha256_text(gcode_off),
        "on_sha256": sha256_text(gcode_on),
        "off_explicit_z_count": len(motion_z_values(gcode_off)),
        "on_explicit_z_count": len(motion_z_values(gcode_on)),
        "off_preview_half_layer_marker_count": off_preview_markers,
        "on_preview_half_layer_marker_count": on_preview_markers,
        "off_half_layer_perimeter_count": len(off_events),
        "on_half_layer_perimeter_count": len(on_events),
        "extruding_inner_wall_half_layer_count": sum(
            event["extrudes_before_next_z"] and event["is_inner_wall"]
            for event in on_events
        ),
        # The two Z ladders side by side answer the question a screenshot cannot: OFF should
        # climb 0.2, 0.4, 0.6 ...; ON should climb the same ladder with a rung between each
        # pair. If ON's ladder equals OFF's, nothing is raised and the slice is at fault, not
        # the Preview.
        # null means the slicer never logged the line - not that nothing was split.
        # Deliberately not an error: a diagnostic must not cost the build its installer.
        "preview_split_on": preview_split_report(workdir / "on"),
        "preview_split_off": preview_split_report(workdir / "off"),
        "nominal_layer_z_mm": rounded_unique(motion_z_values(gcode_off))[:24],
        "all_layer_z_mm_on": rounded_unique(motion_z_values(gcode_on))[:48],
        "distinct_half_layer_perimeter_z_mm": half_layer_values,
        "first_half_layer_events": on_events[:10],
    }
    summary_path = workdir / "orcabrick-gcode-proof.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))

    if errors:
        raise RuntimeError("; ".join(errors))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()

    if args.self_test:
        parser_self_test()
        if args.repo is not None:
            source_self_test(args.repo.resolve())
        print("OrcaBrick proof parser self-test: PASS")
        return 0

    if args.exe is None or args.repo is None or args.workdir is None:
        parser.error("--exe, --repo and --workdir are required unless --self-test is used")

    workdir = args.workdir.resolve()
    try:
        return run_proof(
            args.exe.resolve(),
            args.repo.resolve(),
            workdir,
        )
    except Exception as error:
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "orcabrick-gcode-proof-error.txt").write_text(
            f"{type(error).__name__}: {error}\n", encoding="utf-8"
        )
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ORCABRICK G-CODE PROOF FAILED: {error}", file=sys.stderr)
        sys.exit(1)
