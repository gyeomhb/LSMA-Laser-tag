import unittest

from tracking_panel import coordinate_text


class TrackingPanelTest(unittest.TestCase):
    def sample(self, markers=None, age=0.05):
        return {"frame_age_seconds": age, "error": None,
                "markers": markers if markers is not None else [
                    {"id": 5, "center_pixels": [569.5, 297]},
                    {"id": 8, "center_pixels": [100, 200]},
                ]}

    def test_tag_identity_and_units(self):
        result = coordinate_text(self.sample())
        self.assertIn("Tag 5:  X = 569.5 px    Y = 297.0 px", result)
        self.assertIn("Tag 8:", result)

    def test_selected_tag(self):
        result = coordinate_text(self.sample(), marker_id=8)
        self.assertIn("Tag 8:", result)
        self.assertNotIn("Tag 5:", result)
        self.assertEqual(coordinate_text(self.sample(), marker_id=4), "Tag 4 not visible")

    def test_stale_coordinates_are_hidden(self):
        for sample, elapsed in [(self.sample(age=3), 0), (self.sample(), 3)]:
            result = coordinate_text(sample, elapsed)
            self.assertIn("stale", result)
            self.assertNotIn("569.5", result)

    def test_missing_data(self):
        self.assertIn("Waiting", coordinate_text(None))
        self.assertEqual(coordinate_text(self.sample(markers=[])), "No tags visible")
        self.assertIn("unavailable", coordinate_text({"error": "Connection timed out"}))

    def test_invalid_numbers_are_not_current_coordinates(self):
        self.assertIn("stale", coordinate_text(self.sample(age=float("nan"))))
        self.assertEqual(coordinate_text(self.sample(markers=[
            {"id": 5, "center_pixels": [float("nan"), 1]}])), "No tags visible")


if __name__ == "__main__":
    unittest.main()
