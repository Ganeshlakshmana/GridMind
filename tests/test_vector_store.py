import unittest
import numpy as np

from db.vector_store import CustomVectorEncoder, IncidentVectorStore, search_similar_incidents

class TestVectorStore(unittest.TestCase):
    def test_custom_vector_encoder(self):
        texts = [
            "Inverter output dropped to zero.",
            "Battery state of charge is low.",
            "System went completely offline."
        ]
        encoder = CustomVectorEncoder()
        encoder.fit(texts)
        
        self.assertGreater(len(encoder.vocabulary), 0)
        embeddings = encoder.encode(texts)
        self.assertEqual(embeddings.shape, (3, len(encoder.vocabulary)))
        
        # Test unit norm
        for emb in embeddings:
            norm = np.linalg.norm(emb)
            if norm > 0:
                self.assertAlmostEqual(norm, 1.0, places=5)

    def test_incident_vector_store_search(self):
        store = IncidentVectorStore()
        
        # Search query matching battery issue
        results = store.search("battery charge dropped rapidly", k=2)
        self.assertEqual(len(results), 2)
        
        # Check that the top result is a battery related action
        self.assertEqual(results[0]["action"], "reset_battery_management")
        
    def test_search_similar_incidents_tool(self):
        # Test the LangChain tool interface directly
        res = search_similar_incidents.invoke({"query_text": "inverter fault output zero"})
        self.assertIn("query", res)
        self.assertIn("results", res)
        self.assertEqual(res["query"], "inverter fault output zero")
        self.assertGreater(len(res["results"]), 0)
        self.assertEqual(res["results"][0]["action"], "restart_inverter")

if __name__ == "__main__":
    import os
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    unittest.main()
