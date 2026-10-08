import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import neon_api as cli


class Behavior(unittest.TestCase):
    def test_dry_run_no_auth_or_network(self):
        with (
            patch("neon_api.request_json") as req,
            patch.dict(os.environ, {}, clear=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["delete", "/projects/synthetic"]), 0)
            req.assert_not_called()

    def test_branch_scoping(self):
        with (
            patch("neon_api.request_json", return_value=(200, {"branches": []})) as req,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            cli.main(["branches", "--project-id", "synthetic"])
            self.assertEqual(req.call_args.args[0], "/projects/synthetic/branches")

    def test_org_key_probe(self):
        with (
            patch("neon_api.request_json", return_value=(200, {"projects": []})) as req,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            cli.main(["validate"])
            self.assertEqual(req.call_count, 1)
            self.assertIn("/projects", req.call_args.args[0])

    def test_execute_sends_once(self):
        with (
            patch("neon_api.request_json", return_value=(200, {})) as req,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            cli.main(["delete", "/projects/synthetic", "--execute"])
            req.assert_called_once()
