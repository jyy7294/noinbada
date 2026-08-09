import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORKBOOK = next(ROOT.parent.glob("*.xlsx"))

class CandidateGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "candidates"
        command = [sys.executable, str(ROOT / "candidate_generator.py"), "--workbook", str(WORKBOOK),
            "--documents", str(FIXTURES / "raw_documents.csv"), "--aliases", str(FIXTURES / "seed_aliases.csv"),
            "--output-dir", str(self.output)]
        subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        with (self.output / "candidate_pool.csv").open(encoding="utf-8-sig", newline="") as handle:
            self.rows = list(csv.DictReader(handle))

    def tearDown(self): self.temp.cleanup()
    def candidate(self, term): return next(row for row in self.rows if row["candidate_keyword"] == term)

    def test_hashtag_and_plain_keyword_are_deduplicated(self):
        rows = [row for row in self.rows if row["normalized_keyword"] == "탕후루"]
        self.assertEqual(1, len(rows))

    def test_consumer_signal_candidates(self):
        self.assertEqual("소비 신호", self.candidate("두쫀쿠 레시피")["role_guess"])
        self.assertEqual("소비 신호", self.candidate("Hype Boy 챌린지")["role_guess"])
        self.assertEqual("소비 신호", self.candidate("Hype Boy 안무")["role_guess"])

    def test_expansion_context_and_excluded_trend(self):
        self.assertEqual("확산 맥락", self.candidate("뉴진스의 하입보이요")["role_guess"])
        self.assertNotIn("TR-2022-002", {row["trend_id"] for row in self.rows})

    def test_stopwords_are_not_candidates(self):
        self.assertNotIn("사람", {row["candidate_keyword"] for row in self.rows})

    def test_pipeline_blocks_empty_scores(self):
        command = [sys.executable, str(ROOT / "pipeline.py"), "--workbook", str(WORKBOOK),
            "--documents", str(FIXTURES / "raw_documents.csv"), "--aliases", str(FIXTURES / "seed_aliases.csv"),
            "--output-dir", str(self.output)]
        finished = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(2, finished.returncode)
        self.assertIn("점수 검토", finished.stdout)

if __name__ == "__main__": unittest.main()
