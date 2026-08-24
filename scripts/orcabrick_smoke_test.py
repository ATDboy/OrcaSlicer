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
    expected_cpack = (
        'set (CPACK_PACKAGE_FILE_NAME '
        '"OrcaBrick_Setup_${ORCA_VERSION_MAJOR}.${ORCA_VERSION_MINOR}.'
        '${ORCA_VERSION_PATCH}_build_${ORCABRICK_BUILD}")'
    )
    if expected_cpack not in cmake_text:
        raise RuntimeError("CMake installer name is not tied to ORCABRICK_BUILD")

    workflow_text = (
        repository / ".github" / "workflows" / "build_orca.yml"
    ).read_text(encoding="utf-8")
    expected_upload = (
        "${{ github.workspace }}/${{ env.BUILD_DIR }}/"
        "OrcaBrick_Setup_*${{ env.ARCH_SUFFIX }}.exe"
    )
    if expected_upload not in workflow_text:
        raise RuntimeError("Installer artifact upload path does not match CPack output")
    if workflow_text.index("Prove Bricklaying changes sliced G-code") > workflow_text.index(
        "Create installer Win"
    ):
        raise RuntimeError("Bricklaying proof must run before installer creation")

    required_source_wiring = {
        "src/libslic3r/PrintConfig.cpp": (
            'this->add("staggered_perimeters", coBool)',
            'this->add("staggered_perimeter_flow_ratio", coFloat)',
        ),
        "src/libslic3r/PerimeterGenerator.cpp": (
            "perimeter_generator.config->staggered_perimeters",
            "cur_path.z_offset = 0.5",
        ),
        "src/libslic3r/GCode.cpp": (
            "path.z_offset * path.height",
            "m_config.staggered_perimeter_flow_ratio",
        ),
        "src/libslic3r/PrintObject.cpp": (
            'opt_key == "staggered_perimeters"',
            'opt_key == "staggered_perimeter_flow_ratio"',
        ),
        "src/slic3r/GUI/Tab.cpp": (
            'append_single_option_line("staggered_perimeters")',
            'append_single_option_line("staggered_perimeter_flow_ratio")',
        ),
    }
    for relative_path, snippets in required_source_wiring.items():
        source = (repository / relative_path).read_text(encoding="utf-8")
        missing = [snippet for snippet in snippets if snippet not in source]
        if missing:
            raise RuntimeError(
                f"{relative_path} is missing OrcaBrick wiring: {', '.join(missing)}"
            )


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
        "off_half_layer_perimeter_count": len(off_events),
        "on_half_layer_perimeter_count": len(on_events),
        "extruding_inner_wall_half_layer_count": sum(
            event["extrudes_before_next_z"] and event["is_inner_wall"]
            for event in on_events
        ),
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
