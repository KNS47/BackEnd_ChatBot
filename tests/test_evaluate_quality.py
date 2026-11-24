import unittest
from collections import Counter

from evaluate_quality import classification_metrics, error_rate, evaluate_retrieval


class EvaluationMetricsTests(unittest.TestCase):
    def test_confusion_matrix_uses_positive_answer_class(self):
        confusion = Counter({(True, True): 4, (True, False): 3, (False, True): 1, (False, False): 2})
        self.assertEqual(classification_metrics(confusion), {
            "tp": 4, "tn": 2, "fp": 1, "fn": 3,
            "accuracy": 0.6, "precision": 0.8, "recall": 0.5714, "f1": 0.6667,
        })

    def test_retrieval_recall_counts_multiple_relevant_documents(self):
        result = evaluate_retrieval()
        complaint = next(row for row in result["per_query"] if len(row["relevant"]) == 2)
        self.assertEqual(complaint["recall_at_1"], 0.5)
        self.assertEqual(complaint["recall_at_3"], 1.0)
        self.assertEqual(complaint["reciprocal_rank"], 1.0)

    def test_error_rate_handles_insertion_substitution_and_deletion(self):
        self.assertEqual(error_rate("กขค", "กงคจ"), 2 / 3)
        self.assertEqual(error_rate(["เปิด", "เวลา", "08:45"], ["เปิด", "08:45"]), 1 / 3)
