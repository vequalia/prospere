import ast
import os
import unittest
from typing import Any


class TestConstantsArchitecture(unittest.TestCase):
    def _parse_constant_value(self, node: ast.Assign) -> Any:
        """Helper to extract literal values from AST assignments, supporting

        positive and negative literals.
        """
        if isinstance(node.value, ast.Constant):
            return node.value.value

        if isinstance(node.value, ast.UnaryOp) and isinstance(
            node.value.operand, ast.Constant
        ):
            # Support negative numeric literals like -3.0 or -1
            if isinstance(node.value.op, ast.USub):
                return -node.value.operand.value

        return None

    def _scan_file(
        self,
        file_path: str,
        src_root: str,
        constants_by_name: dict[str, list[tuple[str, Any]]],
        constants_by_value: dict[tuple[str, Any], list[tuple[str, str]]],
    ) -> None:
        """Parses a single python file and extracts all uppercase constants."""
        rel_path = os.path.relpath(file_path, src_root)

        with open(file_path, encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=file_path)
            except SyntaxError as e:
                self.fail(f"Failed to parse syntax of {rel_path}: {e}")

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue

            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue

                name = target.id
                if name.isupper():
                    val = self._parse_constant_value(node)
                    if val is not None:
                        # 1. Collect for Duplicate Name Check
                        constants_by_name.setdefault(name, []).append((rel_path, val))

                        # 2. Collect for Duplicate Value Check (strings & numbers)
                        if isinstance(val, str | int | float) and val != "":
                            val_key = (type(val).__name__, val)
                            constants_by_value.setdefault(val_key, []).append(
                                (rel_path, name)
                            )

    def test_no_duplicate_constants(self) -> None:
        """Statically inspects the production codebase to ensure no duplicate

        uppercase constant names or duplicate literal values exist across
        different modules, enforcing our strict hybrid architecture.
        """
        constants_by_name: dict[str, list[tuple[str, Any]]] = {}
        constants_by_value: dict[tuple[str, Any], list[tuple[str, str]]] = {}

        src_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../src/prospere")
        )

        for root, _, files in os.walk(src_root):
            for file in files:
                # Exclude special files and private assets
                if not file.endswith(".py") or file.startswith("__"):
                    continue

                file_path = os.path.join(root, file)
                self._scan_file(
                    file_path, src_root, constants_by_name, constants_by_value
                )

        # 1. Verify no duplicate constant names across multiple files
        name_violations = []
        for name, occurrences in constants_by_name.items():
            file_set = {occ[0] for occ in occurrences}
            if len(file_set) > 1:
                details = ", ".join(f"{f} (value: {v})" for f, v in occurrences)
                name_violations.append(
                    f"  - Constant '{name}' is duplicated in: {details}"
                )

        # 2. Verify no duplicate values assigned to constants across files
        value_violations = []
        for val_key, occurrences in constants_by_value.items():
            file_set = {occ[0] for occ in occurrences}
            if len(file_set) > 1:
                val_type, val = val_key
                details = ", ".join(f"{f} (as '{n}')" for f, n in occurrences)
                value_violations.append(
                    f"  - Value {repr(val)} ({val_type}) is duplicated in: {details}"
                )

        # Fail test with a helpful architectural guide if violations exist
        error_msg = ""
        if name_violations:
            error_msg += (
                "Duplicate constant NAMES detected across modules:\n"
                + "\n".join(name_violations)
                + "\n"
            )
        if value_violations:
            error_msg += (
                "Duplicate constant VALUES detected across modules:\n"
                + "\n".join(value_violations)
                + "\n"
            )

        if error_msg:
            self.fail(
                "[Architecture Violation] Constants must comply with the "
                "hybrid architecture standard. Please move shared constants to "
                "`src/prospere/core/constants.py` to eliminate duplication.\n\n"
                f"{error_msg}"
            )


if __name__ == "__main__":
    unittest.main()
