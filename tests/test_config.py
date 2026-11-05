import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proofcrew.config import Config


MODEL_IDS = {
    "planner_model": "nvidia/Nemotron-3-Ultra-550b-a55b",
    "worker_model": "nvidia/nemotron-3-super-120b-a12b",
    "screener_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
}


class TestConfigModels(unittest.TestCase):
    def test_default_models_match_live_ids(self):
        config = Config.from_env({})
        for field, model_id in MODEL_IDS.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(config, field), model_id)

    def test_env_example_documents_live_ids(self):
        example = Path(__file__).resolve().parents[1] / ".env.example"
        documented = {}
        for line in example.read_text().splitlines():
            if line.startswith("# MODEL_"):
                name, value = line[2:].split("=", 1)
                documented[name] = value

        self.assertEqual(
            documented,
            {
                "MODEL_PLANNER": MODEL_IDS["planner_model"],
                "MODEL_WORKER": MODEL_IDS["worker_model"],
                "MODEL_SCREENER": MODEL_IDS["screener_model"],
            },
        )

    def test_env_model_overrides_are_preserved(self):
        config = Config.from_env(
            {
                "MODEL_PLANNER": "custom/planner",
                "MODEL_WORKER": "custom/worker",
                "MODEL_SCREENER": "custom/screener",
            }
        )
        self.assertEqual(config.planner_model, "custom/planner")
        self.assertEqual(config.worker_model, "custom/worker")
        self.assertEqual(config.screener_model, "custom/screener")


if __name__ == "__main__":
    unittest.main()
