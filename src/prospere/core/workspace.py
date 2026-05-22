import json
import os

from prospere.core.constants import WorkspaceConfig
from prospere.core.models import Identity, WorkspaceContext


class WorkspaceManager:
    """Manages the multi-user workspace directory structure and path resolution.

    Directory layout (mirrors the global ``scenarios/`` folder)::

        data/workspaces/{user}/
            identity.json
            datasets/
            scenarios/
                simulation/
                    {name}/
                        scenario.json
                        account_config.json
                        category_config.json
                        exports/
                optimization/
                    {name}/
                        config.json
                archive/
    """

    def __init__(self, context: WorkspaceContext):
        self.context = context
        self.user_root = os.path.join(WorkspaceConfig.ROOT_DIR, context.user)

    def ensure_structure(self) -> None:
        os.makedirs(self.user_root, exist_ok=True)
        os.makedirs(self.get_raw_dir(), exist_ok=True)
        os.makedirs(self.get_datasets_root(), exist_ok=True)
        os.makedirs(self.get_simulations_root(), exist_ok=True)
        os.makedirs(self.get_optimizations_root(), exist_ok=True)

    def _migrate_nested_optimizations(self, sim_path: str, opt_root: str) -> None:
        """Move nested optimizations to the top-level optimization root."""
        import shutil

        old_optim = os.path.join(sim_path, "optimizations")
        if os.path.isdir(old_optim):
            os.makedirs(opt_root, exist_ok=True)
            for entry in os.listdir(old_optim):
                src, dst = os.path.join(old_optim, entry), os.path.join(opt_root, entry)
                if not os.path.exists(dst):
                    shutil.move(src, dst)

    def _migrate_legacy_structure(self) -> None:
        """Move old flat scenario layout to the new simulation/optimization split."""
        import shutil

        sim_root = os.path.join(self.user_root, WorkspaceConfig.SIMULATION_DIR)
        opt_root = os.path.join(self.user_root, WorkspaceConfig.OPTIMIZATION_DIR)
        old_root = os.path.join(self.user_root, WorkspaceConfig.SCENARIOS_DIR)

        if os.path.isdir(sim_root) or not os.path.isdir(old_root):
            return

        for entry in os.listdir(old_root):
            old_path = os.path.join(old_root, entry)
            if not os.path.isdir(old_path) or entry in (
                "simulation",
                "optimization",
                "archive",
            ):
                continue

            if os.path.exists(os.path.join(old_path, "config.json")):
                new_path = os.path.join(opt_root, entry)
            else:
                new_path = os.path.join(sim_root, entry)
                self._migrate_nested_optimizations(old_path, opt_root)

            if not os.path.exists(new_path):
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.move(old_path, new_path)

    def get_identity_path(self) -> str:
        return os.path.join(self.user_root, WorkspaceConfig.IDENTITY_FILE)

    def get_raw_dir(self) -> str:
        return os.path.join(self.user_root, WorkspaceConfig.RAW_DIR)

    def get_datasets_root(self) -> str:
        return os.path.join(self.user_root, WorkspaceConfig.DATASETS_DIR)

    def get_dataset_dir(self) -> str:
        snapshot = self.context.snapshot or "default"
        return os.path.join(self.get_datasets_root(), snapshot)

    def get_dataset_path(self, filename: str) -> str:
        return os.path.join(self.get_dataset_dir(), filename)

    # ── simulation scenarios ──────────────────────────────────────────

    def get_scenarios_root(self) -> str:
        return self.get_simulations_root()

    def get_simulations_root(self) -> str:
        self._migrate_legacy_structure()
        return os.path.join(self.user_root, WorkspaceConfig.SIMULATION_DIR)

    def get_scenario_dir(self, scenario_name: str | None = None) -> str:
        name = scenario_name or self.context.scenario or "default"
        return os.path.join(self.get_simulations_root(), name)

    # ── optimization scenarios ────────────────────────────────────────

    def get_optimizations_root(self) -> str:
        return os.path.join(self.user_root, WorkspaceConfig.OPTIMIZATION_DIR)

    def get_optimizations_dir(self, scenario_name: str | None = None) -> str:
        name = scenario_name or self.context.scenario or "default"
        return os.path.join(self.get_optimizations_root(), name)

    # ── identity ──────────────────────────────────────────────────────

    def load_identity(self) -> Identity:
        path = self.get_identity_path()
        if not os.path.exists(path):
            return Identity(name=self.context.user)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return Identity(**data)
        except Exception:
            return Identity(name=self.context.user)

    def save_identity(self, identity: Identity) -> None:
        self.ensure_structure()
        path = self.get_identity_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(identity.__dict__, f, indent=4)
