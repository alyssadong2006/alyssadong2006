#!/usr/bin/env python3
"""Generate an animated Pac-Man SVG from the authenticated GitHub user's contributions."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


GRAPHQL_URL = "https://api.github.com/graphql"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "generated" / "pacman-commits.svg"
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

QUERY = """
query {
  viewer {
    login
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            contributionCount
          }
        }
      }
    }
  }
}
"""

COLORS = ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353")
CELL_SIZE = 10
GAP = 2
GRID_X = 12
GRID_Y = 12
COLUMNS = 52
ROWS = 7
SECONDS_PER_STEP = 0.35
MIN_ANIMATION_SECONDS = 60


def _tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def fetch_contributions(token: str) -> tuple[str, list[list[int]]]:
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps({"query": QUERY}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "pacman-profile-svg-generator",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL request failed ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach GitHub GraphQL API: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("GitHub GraphQL API returned invalid JSON") from error

    if payload.get("errors"):
        messages = "; ".join(str(item.get("message", item)) for item in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL query failed: {messages}")

    try:
        viewer = payload["data"]["viewer"]
        weeks = viewer["contributionsCollection"]["contributionCalendar"]["weeks"]
        login = viewer["login"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("GitHub GraphQL response is missing contribution calendar data") from error

    counts = [
        [int(day["contributionCount"]) for day in week["contributionDays"]]
        for week in weeks[-COLUMNS:]
    ]
    if not login or not counts:
        raise RuntimeError("GitHub returned an empty user or contribution calendar")

    # GraphQL calendars can contain 53 weeks; use the most recent 52 and pad
    # unusually short responses so the output always has a fixed grid.
    counts = [[0] * ROWS for _ in range(COLUMNS - len(counts))] + counts
    counts = [(week + [0] * ROWS)[:ROWS] for week in counts]
    return str(login), counts


def _contribution_color(count: int) -> str:
    if count <= 0:
        return COLORS[0]
    if count <= 3:
        return COLORS[1]
    if count <= 6:
        return COLORS[2]
    if count <= 9:
        return COLORS[3]
    return COLORS[4]


def _movement_route(counts: list[list[int]]) -> list[tuple[int, int]]:
    contributions = [
        (column, row, counts[column][row] if column < len(counts) and row < len(counts[column]) else 0)
        for column in range(COLUMNS)
        for row in range(ROWS)
    ]
    populated = [cell for cell in contributions if cell[2] > 0]
    if not populated:
        populated = contributions

    seed = json.dumps(counts, separators=(",", ":"))
    rng = random.Random(seed)
    groups: dict[int, list[tuple[int, int, int]]] = {}
    for cell in populated:
        groups.setdefault(cell[2], []).append(cell)

    route = []
    for count in sorted(groups, reverse=True):
        group = groups[count]
        rng.shuffle(group)
        route.extend((column, row) for column, row, _ in group)

    path = [route[0]]
    for target_column, target_row in route[1:] + [route[0]]:
        column, row = path[-1]
        while column != target_column:
            column += 1 if target_column > column else -1
            path.append((column, row))
        while row != target_row:
            row += 1 if target_row > row else -1
            path.append((column, row))
    return path


def _animation_keyframes(route: list[tuple[int, int]], face_movement: bool = False) -> str:
    frames = []
    for index, (column, row) in enumerate(route):
        percentage = _route_percentage(index, len(route))
        x = GRID_X + column * (CELL_SIZE + GAP)
        y = GRID_Y + row * (CELL_SIZE + GAP)
        transform = f"translate({x}px, {y}px)"
        if face_movement and len(route) > 1:
            next_index = index + 1 if index + 1 < len(route) else 1
            next_column, next_row = route[next_index]
            dx = next_column - column
            dy = next_row - row
            angle = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}.get(
                (dx, dy), 0
            )
            transform += f" rotate({angle}deg)"
        frames.append(f"{percentage:.3f}% {{ transform: {transform}; }}")
    if len(route) == 1:
        column, row = route[0]
        x = GRID_X + column * (CELL_SIZE + GAP)
        y = GRID_Y + row * (CELL_SIZE + GAP)
        frames.append(f"100% {{ transform: translate({x}px, {y}px); }}")
    return " ".join(frames)


def _animation_duration(route: list[tuple[int, int]]) -> float:
    return max(MIN_ANIMATION_SECONDS, len(route) * SECONDS_PER_STEP)


def _route_percentage(index: int, route_length: int) -> float:
    return index / max(route_length - 1, 1) * 100


def build_svg(login: str, counts: list[list[int]], demo: bool = False) -> ET.Element:
    width = GRID_X * 2 + COLUMNS * (CELL_SIZE + GAP) - GAP
    height = GRID_Y + ROWS * (CELL_SIZE + GAP) - GAP + 23
    root = ET.Element(
        _tag("svg"),
        {
            "viewBox": f"0 0 {width} {height}",
            "width": str(width),
            "height": str(height),
            "role": "img",
            "aria-labelledby": "title description",
        },
    )
    ET.SubElement(root, _tag("title"), {"id": "title"}).text = (
        "Pac-Man contribution calendar preview"
        if demo
        else f"Pac-Man contribution calendar for {login}"
    )
    ET.SubElement(root, _tag("desc"), {"id": "description"}).text = (
        "Preview animation with sample contribution levels. Run the GitHub Actions workflow to load live data."
        if demo
        else f"Pac-Man visits higher-contribution days first in the last 52 weeks for GitHub user {login}."
    )

    route = _movement_route(counts)
    duration = _animation_duration(route)
    duration_css = f"{duration:g}s"
    style = ET.SubElement(root, _tag("style"))
    style.text = (
        ":root { --empty-color: #ebedf0; --label-color: #57606a; } "
        ".background { fill: #ffffff; } "
        ".tile-empty { fill: var(--empty-color); } "
        ".footer { fill: var(--label-color); } "
        "@media (prefers-color-scheme: dark) { "
        ":root { --empty-color: #161b22; --label-color: #8b949e; } "
        ".background { fill: #0d1117; } } "
        "@keyframes slide { "
        + _animation_keyframes(route, face_movement=True)
        + " } "
        "@keyframes ghost-slide { "
        + _animation_keyframes(route)
        + " } "
        "@keyframes chomp { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } } "
        "@keyframes close-mouth { 0%, 49% { opacity: 0; } 50%, 100% { opacity: 1; } } "
        ".pacman { animation: slide "
        + duration_css
        + " linear infinite; transform-box: fill-box; transform-origin: center; } "
        ".ghost { animation: ghost-slide "
        + duration_css
        + " linear 1s infinite both; } "
        ".open-mouth { animation: chomp 0.32s steps(1, end) infinite; } "
        ".closed-mouth { animation: close-mouth 0.32s steps(1, end) infinite; }"
    )

    # Populated tiles dissolve as Pac-Man reaches them.
    style.text += " " + _tile_animation_rules(counts, route, duration)

    ET.SubElement(
        root,
        _tag("rect"),
        {"class": "background", "width": str(width), "height": str(height)},
    )

    grid = ET.SubElement(root, _tag("g"), {"aria-hidden": "true"})
    for column in range(COLUMNS):
        for row in range(ROWS):
            count = counts[column][row] if column < len(counts) and row < len(counts[column]) else 0
            classes = f"tile tile-{column}-{row}" if count else "tile tile-empty"
            fill = "var(--empty-color)" if count == 0 else _contribution_color(count)
            tile = ET.SubElement(
                grid,
                _tag("rect"),
                {
                    "class": classes,
                    "x": str(GRID_X + column * (CELL_SIZE + GAP)),
                    "y": str(GRID_Y + row * (CELL_SIZE + GAP)),
                    "width": str(CELL_SIZE),
                    "height": str(CELL_SIZE),
                    "rx": "2",
                    "fill": fill,
                    "data-count": str(count),
                },
            )
            tile.set("aria-label", f"{count} contributions")

    characters = ET.SubElement(root, _tag("g"), {"aria-hidden": "true"})
    pacman = ET.SubElement(characters, _tag("g"), {"class": "pacman"})
    ET.SubElement(
        pacman,
        _tag("circle"),
        {"cx": "5", "cy": "5", "r": "4.5", "fill": "#facc15", "class": "closed-mouth"},
    )
    ET.SubElement(
        pacman,
        _tag("path"),
        {
            "d": "M5 5 L9.5 2.2 A4.5 4.5 0 1 0 9.5 7.8 Z",
            "fill": "#facc15",
            "class": "open-mouth",
        },
    )
    ghost = ET.SubElement(characters, _tag("g"), {"class": "ghost"})
    ET.SubElement(
        ghost,
        _tag("path"),
        {
            "d": "M1 10 V4.5 A4 4 0 0 1 9 4.5 V10 L7 8.5 L5 10 L3 8.5 Z",
            "fill": "#f472b6",
        },
    )
    for x in ("3.5", "6.5"):
        ET.SubElement(ghost, _tag("circle"), {"cx": x, "cy": "5", "r": "0.8", "fill": "#fff"})

    footer = ET.SubElement(root, _tag("text"), {
        "class": "footer",
        "x": str(GRID_X),
        "y": str(height - 6),
        "fill": "var(--label-color)",
        "font-family": "monospace",
        "font-size": "9",
    })
    footer.text = "PREVIEW - RUN WORKFLOW FOR LIVE DATA" if demo else f"CONTRIBUTIONS / {login.upper()}"
    return root


def _tile_animation_rules(
    counts: list[list[int]], route: list[tuple[int, int]], duration: float
) -> str:
    rules = []
    route_length = len(route)
    seen: set[tuple[int, int]] = set()
    for index, (column, row) in enumerate(route):
        if (column, row) in seen:
            continue
        seen.add((column, row))
        count = counts[column][row] if column < len(counts) and row < len(counts[column]) else 0
        if count <= 0:
            continue
        eaten_at = _route_percentage(index, route_length)
        fade_end = min(eaten_at + 0.05 / duration * 100, 100)
        keyframes = f"0%, {eaten_at:.3f}% {{ opacity: 1; }}"
        if eaten_at == 0:
            keyframes = "0% { opacity: 0; }"
            fade_end = 0
        else:
            keyframes += f"{fade_end:.3f}% {{ opacity: 0; }}"
        keyframes += "100% { opacity: 0; }"
        rules.append(
            f".tile-{column}-{row} {{ animation: eat-{column}-{row} "
            f"{duration:g}s linear infinite; }}"
            f"@keyframes eat-{column}-{row} {{ {keyframes} }}"
        )
    return " ".join(rules)


def write_svg(output: Path, login: str, counts: list[list[int]], demo: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(build_svg(login, counts, demo=demo))
    ET.indent(tree, space="  ")
    tree.write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="SVG output path")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Create a clearly labeled preview without requesting GitHub data",
    )
    args = parser.parse_args()

    if args.demo:
        sample = [
            [((column * 7 + row * 3) % 12) if (column + row) % 3 else 0 for row in range(ROWS)]
            for column in range(COLUMNS)
        ]
        write_svg(args.output, "preview", sample, demo=True)
        return 0

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN is required. Add it as an Actions secret or run with --demo.", file=sys.stderr)
        return 1

    try:
        login, counts = fetch_contributions(token)
        write_svg(args.output, login, counts)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(f"Failed to generate contribution SVG: {error}", file=sys.stderr)
        return 1
    print(f"Generated {args.output} for {login}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
