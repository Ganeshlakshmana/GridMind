import unittest
from tools.geo import haversine_distance, get_grid_zone, grid_zone_clustering, nearest_neighbor_lookup

class TestGeoUtils(unittest.TestCase):
    def test_haversine_distance(self):
        # Center: 52.51, 13.40
        # North: 52.57, 13.40
        # Distance should be roughly 6.67 km
        dist = haversine_distance(52.51, 13.40, 52.57, 13.40)
        self.assertAlmostEqual(dist, 6.67, delta=0.5)

        # Distance to itself should be 0
        dist_self = haversine_distance(52.51, 13.40, 52.51, 13.40)
        self.assertEqual(dist_self, 0.0)

    def test_get_grid_zone(self):
        # Very close to North Centroid (52.57, 13.40)
        zone = get_grid_zone(52.569, 13.401)
        self.assertEqual(zone, "ZONE_NORTH")

        # Very close to West Centroid (52.51, 13.25)
        zone_west = get_grid_zone(52.51, 13.26)
        self.assertEqual(zone_west, "ZONE_WEST")

    def test_grid_zone_clustering(self):
        systems = [
            {"system_id": "SYS_001", "latitude": 52.57, "longitude": 13.40}, # North
            {"system_id": "SYS_002", "latitude": 52.46, "longitude": 13.40}, # South
            {"system_id": "SYS_003", "latitude": 52.51, "longitude": 13.25}, # West
        ]
        clusters = grid_zone_clustering(systems)
        self.assertIn("ZONE_NORTH", clusters)
        self.assertIn("ZONE_SOUTH", clusters)
        self.assertIn("ZONE_WEST", clusters)
        self.assertEqual(len(clusters["ZONE_NORTH"]), 1)
        self.assertEqual(clusters["ZONE_NORTH"][0]["system_id"], "SYS_001")

    def test_nearest_neighbor_lookup(self):
        systems = [
            {"system_id": "SYS_A", "latitude": 52.57, "longitude": 13.40}, # Dist ~6.67km from center
            {"system_id": "SYS_B", "latitude": 52.511, "longitude": 13.401}, # Dist <0.2km from center
            {"system_id": "SYS_C", "latitude": 52.46, "longitude": 13.40}, # Dist ~5.56km from center
        ]
        # Look up nearest to center (52.51, 13.40)
        nearest = nearest_neighbor_lookup(52.51, 13.40, systems, k=2)
        self.assertEqual(len(nearest), 2)
        self.assertEqual(nearest[0]["system_id"], "SYS_B")
        self.assertEqual(nearest[1]["system_id"], "SYS_C")

if __name__ == "__main__":
    unittest.main()
