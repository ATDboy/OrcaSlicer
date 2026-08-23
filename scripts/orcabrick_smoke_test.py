#!/usr/bin/env python3
"""Prove that OrcaBrick changes sliced G-code when Bricklaying is enabled."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


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
    if completed.returncode != 0:
        raise RuntimeError(
            "OrcaBrick CLI slicing failed with exit code "
            f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )

    raw_gcode = sorted(output_directory.rglob("*.gcode"))
    if raw_gcode:
        return raw_gcode[0].read_text(encoding="utf-8", errors="replace")

    archives = sorted(output_directory.rglob("*.3mf"))
    for archive in archives:
        if not zipfile.is_zipfile(archive):
            continue
        with zipfile.ZipFile(archive) as package:
            names = [name for name in package.namelist() if name.lower().endswith(".gcode")]
            if names:
                return package.read(names[0]).decode("utf-8", errors="replace")

    raise RuntimeError(
        f"Slicing succeeded but produced no readable G-code under {output_directory}"
    )


def staggered_z_values(gcode: str) -> list[float]:
    values: list[float] = []
    marker = "set Z for staggered perimeter"
    for line in gcode.splitlines():
        if marker not in line:
            continue
        match = re.search(r"(?:^|\s)Z(-?\d+(?:\.\d+)?)", line)
        if match:
            values.append(float(match.group(1)))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--workdir", required=True, type=Path)
    args = parser.parse_args()

    executable = args.exe.resolve()
    repository = args.repo.resolve()
    workdir = args.workdir.resolve()
    if not executable.is_file():
        raise RuntimeError(f"OrcaBrick executable not found: {executable}")

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
            # The proof also validates the Bricklaying-specific Z marker, so
            # force explanatory comments on instead of relying on a profile default.
            "gcode_comments": "1",
            "staggered_perimeter_flow_ratio": "1",
        }
    )
    process_off = dict(process)
    process_off.update({"name": "OrcaBrick smoke test OFF", "staggered_perimeters": "0"})
    process_on = dict(process)
    process_on.update({"name": "OrcaBrick smoke test ON", "staggered_perimeters": "1"})

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

    off_values = staggered_z_values(gcode_off)
    on_values = staggered_z_values(gcode_on)
    if off_values:
        raise RuntimeError(
            f"Bricklaying OFF unexpectedly produced {len(off_values)} staggered Z moves"
        )
    if not on_values:
        raise RuntimeError(
            "Bricklaying ON produced no 'set Z for staggered perimeter' moves; "
            "the checkbox is not changing generated G-code"
        )
    if gcode_on == gcode_off:
        raise RuntimeError("Bricklaying ON and OFF produced identical G-code")

    half_layer_values = [
        value for value in on_values if abs((value / 0.2) - round(value / 0.2)) > 0.1
    ]
    if not half_layer_values:
        raise RuntimeError(
            "Bricklaying emitted marked Z moves, but none were between 0.20 mm nominal layers"
        )

    summary = {
        "result": "PASS",
        "staggered_move_count": len(on_values),
        "first_staggered_z_values_mm": on_values[:10],
        "model": model.name,
        "layer_height_mm": 0.2,
        "wall_loops": 3,
    }
    summary_path = workdir / "orcabrick-smoke-test.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ORCABRICK SMOKE TEST FAILED: {error}", file=sys.stderr)
        sys.exit(1)
