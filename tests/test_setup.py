"""Environment and project setup validation tests.

Verifies:
1. All expected project directories exist.
2. Core dependencies can be imported successfully.
3. Configuration variables and resolved paths are valid.
4. Project metadata matches expected values.
"""

import importlib
from pathlib import Path
import pytest
import config


class TestProjectDirectories:
    """Validate project structure and required directories exist."""

    @pytest.mark.parametrize(
        "dir_path",
        [
            config.DATA_DIR,
            config.RAW_DATA_DIR,
            config.PROCESSED_DATA_DIR,
            config.NOTEBOOKS_DIR,
            config.SRC_DIR,
            config.API_DIR,
            config.DASHBOARD_DIR,
            config.MODELS_DIR,
            config.TESTS_DIR,
        ],
    )
    def test_directory_exists(self, dir_path: Path) -> None:
        """Verify that directory exists and is indeed a directory."""
        assert dir_path.exists(), f"Directory does not exist: {dir_path}"
        assert dir_path.is_dir(), f"Path is not a directory: {dir_path}"


class TestDependencyImports:
    """Validate that all required third-party libraries can be imported."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "pandas",
            "numpy",
            "sklearn",
            "scipy",
            "joblib",
            "matplotlib",
            "seaborn",
            "flask",
            "flask_cors",
            "boto3",
            "dotenv",
            "pytest",
            "black",
            "flake8",
        ],
    )
    def test_module_importable(self, module_name: str) -> None:
        """Verify module can be dynamically imported without ImportError."""
        mod = importlib.import_module(module_name)
        assert mod is not None, f"Failed to import {module_name}"


class TestConfiguration:
    """Validate configuration parameters and paths."""

    def test_project_name(self) -> None:
        """Verify configured project name."""
        expected_name = "AIOps - Cloud Infrastructure Anomaly Detection"
        assert config.PROJECT_NAME == expected_name

    def test_project_root_validity(self) -> None:
        """Verify PROJECT_ROOT exists and contains essential marker files."""
        assert config.PROJECT_ROOT.exists()
        assert (config.PROJECT_ROOT / "config.py").is_file()
        assert (config.PROJECT_ROOT / "requirements.txt").is_file()
        assert (config.PROJECT_ROOT / "README.md").is_file()

    def test_paths_are_subpaths_of_root(self) -> None:
        """Ensure configured directories reside under the project root."""
        for directory in config.PROJECT_DIRECTORIES:
            is_subpath = (
                config.PROJECT_ROOT in directory.parents
                or directory == config.PROJECT_ROOT
            )
            assert is_subpath, f"{directory} not inside {config.PROJECT_ROOT}"
