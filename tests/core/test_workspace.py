import os
import unittest
from tempfile import TemporaryDirectory

from prospere.core.constants import WorkspaceConfig
from prospere.core.models import Identity, WorkspaceContext
from prospere.core.workspace import WorkspaceManager


class TestWorkspaceManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()
        self.orig_root = WorkspaceConfig.ROOT_DIR

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _make_manager(self, user: str = "alice") -> WorkspaceManager:
        context = WorkspaceContext(user=user, snapshot="snap1", scenario="scen1")
        wm = WorkspaceManager(context)
        wm.user_root = os.path.join(self.tmp_dir.name, user)
        return wm

    def test_ensure_structure_creates_dirs(self) -> None:
        wm = self._make_manager("bob")
        wm.ensure_structure()

        self.assertTrue(os.path.isdir(wm.user_root))
        self.assertTrue(os.path.isdir(wm.get_datasets_root()))
        self.assertTrue(os.path.isdir(wm.get_scenarios_root()))

    def test_get_identity_path(self) -> None:
        wm = self._make_manager()
        path = wm.get_identity_path()
        self.assertIn("alice", path)
        self.assertTrue(path.endswith("identity.json"))

    def test_get_datasets_root(self) -> None:
        wm = self._make_manager()
        root = wm.get_datasets_root()
        self.assertIn("alice", root)
        self.assertTrue(root.endswith("datasets"))

    def test_get_dataset_path_with_snapshot(self) -> None:
        wm = self._make_manager()
        path = wm.get_dataset_path("transactions.xlsx")
        self.assertIn("snap1", path)
        self.assertIn("transactions.xlsx", path)

    def test_get_dataset_path_no_snapshot(self) -> None:
        context = WorkspaceContext(user="alice")
        wm = WorkspaceManager(context)
        wm.user_root = os.path.join(self.tmp_dir.name, "alice")
        path = wm.get_dataset_path("data.xlsx")
        self.assertIn("default", path)

    def test_get_scenarios_root(self) -> None:
        wm = self._make_manager()
        root = wm.get_scenarios_root()
        self.assertIn("alice", root)
        self.assertIn("simulation", root)

    def test_get_scenario_dir_with_name(self) -> None:
        wm = self._make_manager()
        dir_path = wm.get_scenario_dir("my_scen")
        self.assertIn("my_scen", dir_path)
        self.assertIn("scenarios", dir_path)

    def test_get_scenario_dir_fallback(self) -> None:
        context = WorkspaceContext(user="alice")
        wm = WorkspaceManager(context)
        wm.user_root = os.path.join(self.tmp_dir.name, "alice")
        dir_path = wm.get_scenario_dir()
        self.assertIn("default", dir_path)

    def test_get_optimizations_dir(self) -> None:
        wm = self._make_manager()
        opt_dir = wm.get_optimizations_dir("scen1")
        self.assertIn("scen1", opt_dir)
        self.assertIn("optimization", opt_dir)

    def test_save_and_load_identity_roundtrip(self) -> None:
        wm = self._make_manager()
        ident = Identity(
            name="Alice",
            age="30",
            industry="Tech",
            location="Paris",
            family_status="Single",
            financial_goal="FIRE",
        )
        wm.save_identity(ident)

        loaded = wm.load_identity()
        self.assertEqual(loaded.name, "Alice")
        self.assertEqual(loaded.age, "30")
        self.assertEqual(loaded.industry, "Tech")
        self.assertEqual(loaded.location, "Paris")
        self.assertEqual(loaded.family_status, "Single")
        self.assertEqual(loaded.financial_goal, "FIRE")

    def test_load_identity_default_when_no_file(self) -> None:
        wm = self._make_manager()
        ident = wm.load_identity()
        self.assertEqual(ident.name, "alice")
        self.assertIsInstance(ident, Identity)


if __name__ == "__main__":
    unittest.main()
