import io
import json
import unittest
from unittest.mock import patch

from scripts import generate_pacman


SVG_NS = "{http://www.w3.org/2000/svg}"


class GeneratePacmanTests(unittest.TestCase):
    def test_pacman_turns_to_face_each_orthogonal_step(self):
        route = [(2, 2), (3, 2), (3, 3), (2, 3), (2, 2)]

        keyframes = generate_pacman._animation_keyframes(route, face_movement=True)

        self.assertIn("translate(36px, 54px) rotate(0deg)", keyframes)
        self.assertIn("translate(48px, 54px) rotate(90deg)", keyframes)
        self.assertIn("translate(48px, 66px) rotate(180deg)", keyframes)
        self.assertIn("translate(36px, 66px) rotate(270deg)", keyframes)

    def test_animation_duration_scales_with_route_length(self):
        route = [(column, 0) for column in range(200)]

        self.assertEqual(generate_pacman._animation_duration(route), 200 * 0.35)
        self.assertGreater(generate_pacman._animation_duration(route), 36)

    def test_commit_tile_changes_color_at_pacman_arrival(self):
        counts = [[0] * 7 for _ in range(52)]
        counts[0][0] = 5
        counts[1][0] = 8
        route = [(0, 0), (1, 0), (2, 0), (0, 0)]

        rules = generate_pacman._tile_animation_rules(counts, route, "60s")
        pacman_frames = generate_pacman._animation_keyframes(route)

        self.assertIn(
            "@keyframes eat-1-0 { 0% { fill: #26a641; "
            "animation-timing-function: steps(1, end); }33.333% { fill: #161b22; } }",
            rules,
        )
        self.assertIn("33.333% { transform: translate(24px, 30px); }", pacman_frames)
        self.assertNotIn("0.150%", rules)

    def test_fetch_contributions_uses_latest_52_weeks(self):
        weeks = [
            {"contributionDays": [{"contributionCount": week} for _ in range(7)]}
            for week in range(53)
        ]
        payload = {
            "data": {
                "viewer": {
                    "login": "octocat",
                    "contributionsCollection": {
                        "contributionCalendar": {"weeks": weeks}
                    },
                }
            }
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))

        with patch.object(generate_pacman.urllib.request, "urlopen", return_value=response):
            login, counts = generate_pacman.fetch_contributions("test-token")

        self.assertEqual(login, "octocat")
        self.assertEqual(len(counts), 52)
        self.assertEqual([len(week) for week in counts], [7] * 52)
        self.assertEqual(counts[0], [1] * 7)
        self.assertEqual(counts[-1], [52] * 7)

    def test_graphql_errors_are_not_silently_ignored(self):
        response = io.BytesIO(
            json.dumps({"errors": [{"message": "invalid token"}]}).encode("utf-8")
        )
        with patch.object(generate_pacman.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid token"):
                generate_pacman.fetch_contributions("test-token")

    def test_svg_has_fixed_grid_and_eats_only_populated_tiles(self):
        counts = [[0] * 7 for _ in range(52)]
        counts[0][0] = 10
        counts[2][2] = 5

        root = generate_pacman.build_svg("octocat", counts)
        tiles = root.findall(f".//{SVG_NS}rect")
        populated = root.find(f".//{SVG_NS}rect[@class='tile tile-0-0']")
        empty = root.find(f".//{SVG_NS}rect[@class='tile']")
        css = root.find(f"{SVG_NS}style").text

        self.assertEqual(len(tiles), 52 * 7)
        self.assertIsNotNone(populated)
        self.assertIsNotNone(empty)
        self.assertIn("@keyframes eat-0-0", css)
        self.assertNotIn("@keyframes eat-0-1", css)
        self.assertIn("rotate(", css)
        self.assertIn("transform-origin: center", css)
        self.assertEqual(root.attrib["viewBox"], "0 0 646 135")

    def test_route_prioritizes_contribution_count_and_shuffles_ties_stably(self):
        counts = [[0] * 7 for _ in range(52)]
        counts[0][0] = 10
        counts[1][1] = 10
        counts[4][2] = 20

        route = generate_pacman._movement_route(counts)
        first_visit = {cell: route.index(cell) for cell in set(route)}

        self.assertLess(first_visit[(4, 2)], first_visit[(0, 0)])
        self.assertLess(first_visit[(4, 2)], first_visit[(1, 1)])
        self.assertEqual(route, generate_pacman._movement_route(counts))
        self.assertEqual(route[0], (4, 2))
        self.assertEqual(route[0], route[-1])
        for (column, row), (next_column, next_row) in zip(route, route[1:]):
            self.assertEqual(abs(column - next_column) + abs(row - next_row), 1)

        tied_counts = [[1] * 7 for _ in range(52)]
        tied_route = generate_pacman._movement_route(tied_counts)
        serpentine = [
            (column, row if column % 2 == 0 else 6 - row)
            for column in range(52)
            for row in range(7)
        ]
        self.assertNotEqual(tied_route, serpentine)


if __name__ == "__main__":
    unittest.main()
