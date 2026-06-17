import unittest

from agent.analysis_features import cluster_unknown_errors, extract_timeline_events, render_error_clusters, render_timeline


class AnalysisFeaturesTest(unittest.TestCase):
    def test_clusters_repeated_unknown_errors(self):
        text = """
        2026-06-17 23:01:01 app ERROR CustomBusinessException: order 123 failed for user 88
        2026-06-17 23:01:02 app ERROR CustomBusinessException: order 124 failed for user 89
        2026-06-17 23:01:03 app ERROR CustomBusinessException: order 125 failed for user 90
        """

        clusters = cluster_unknown_errors(text)

        self.assertTrue(clusters)
        self.assertEqual(clusters[0].count, 3)
        self.assertIn("custombusinessexception", clusters[0].signature)
        self.assertIn("出现 3 次", render_error_clusters(clusters))

    def test_extracts_timeline_events(self):
        text = """
        2026-06-17 23:01:01 nginx error upstream timed out
        2026-06-17 23:02:09 app warning slow request
        """

        events = extract_timeline_events(text)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].timestamp, "2026-06-17 23:01:01")
        self.assertIn("故障时间线", render_timeline(events))


if __name__ == "__main__":
    unittest.main()
