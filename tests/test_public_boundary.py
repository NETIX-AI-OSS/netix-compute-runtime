# SPDX-License-Identifier: Apache-2.0
import importlib.metadata
import importlib.util
import unittest


class PublicBoundaryTests(unittest.TestCase):
    def test_no_model_runtime_dependencies(self):
        from netix_compute_runtime.process import RuntimeCancelled, wait_process
        from runtime.host_manager.supervisor import load_config
        self.assertTrue(callable(wait_process))
        self.assertTrue(callable(load_config))
        self.assertTrue(issubclass(RuntimeCancelled, RuntimeError))
        for name in ("vision_ai", "torch", "transformers", "django", "ultralytics"):
            self.assertIsNone(importlib.util.find_spec(name), name)
        self.assertFalse(importlib.metadata.requires("netix-compute-runtime"))
