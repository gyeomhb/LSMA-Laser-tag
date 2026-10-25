import unittest

from movement_limits import movement_block_reason


class MovementLimitsTest(unittest.TestCase):
    def sample(self, x=400, y=300, age=0.02, tag=5):
        return {"frame_age_seconds": age, "error": None,
                "markers": [{"id": tag, "center_pixels": [x, y]}]}

    def test_inside_bounds(self):
        self.assertIsNone(movement_block_reason(self.sample(), 0.01, 5))
        self.assertIsNone(movement_block_reason(self.sample(50.1, 599.9), 0, 5))

    def test_all_edges_and_outside_block(self):
        for x, y in [(50, 300), (900, 300), (400, 50), (400, 600),
                     (49, 300), (901, 300), (400, 49), (400, 601)]:
            with self.subTest(x=x, y=y):
                self.assertIn("boundary", movement_block_reason(self.sample(x, y), 0, 5))

    def test_missing_wrong_duplicate_or_stale_tag_blocks(self):
        for sample, elapsed, tag in [
            (None, 0, 5), (self.sample(), 0, None), (self.sample(tag=8), 0, 5),
            (self.sample(age=0.6), 0, 5), (self.sample(), 0.6, 5),
            ({"error": "offline"}, 0, 5),
            (self.sample(float("nan"), 100), 0, 5),
            (self.sample(age=float("nan")), 0, 5),
        ]:
            self.assertIsNotNone(movement_block_reason(sample, elapsed, tag))
        sample = self.sample()
        sample["markers"] *= 2
        self.assertIsNotNone(movement_block_reason(sample, 0, 5))



if __name__ == "__main__":
    unittest.main()
