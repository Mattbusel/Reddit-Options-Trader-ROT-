"""Tests for configuration validation.

These tests verify the validate_secret_key() function works correctly.
This function is called from server.py's main() function at startup.
"""

import subprocess
import sys


def test_secret_key_validation_in_production_with_default_raises():
    """Test that default secret key raises RuntimeError in production."""
    code = """
import os
os.environ['RAILWAY_ENVIRONMENT'] = 'production'
os.environ['ROT_WEB_SECRET_KEY'] = 'change-me-in-production'

from rot.core.config import Settings, validate_secret_key

try:
    settings = Settings()
    validate_secret_key(settings)
    print("ERROR: Should have raised RuntimeError")
    exit(1)
except RuntimeError as e:
    if "must be set to a strong secret" in str(e):
        print("SUCCESS")
        exit(0)
    else:
        print(f"ERROR: Wrong error message: {e}")
        exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="."
    )

    assert result.returncode == 0, f"Test failed. stdout={result.stdout}, stderr={result.stderr}"
    assert "SUCCESS" in result.stdout


def test_secret_key_validation_with_strong_key_passes():
    """Test that a strong secret key (32+ chars) passes validation in production."""
    code = """
import os
os.environ['RAILWAY_ENVIRONMENT'] = 'production'
os.environ['ROT_WEB_SECRET_KEY'] = 'a' * 32

from rot.core.config import Settings, validate_secret_key

try:
    settings = Settings()
    validate_secret_key(settings)
    print("SUCCESS")
    exit(0)
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="."
    )

    assert result.returncode == 0, f"Test failed. stdout={result.stdout}, stderr={result.stderr}"
    assert "SUCCESS" in result.stdout


def test_secret_key_validation_with_short_key_raises():
    """Test that a short secret key raises RuntimeError in production."""
    code = """
import os
os.environ['RAILWAY_ENVIRONMENT'] = 'production'
os.environ['ROT_WEB_SECRET_KEY'] = 'short'

from rot.core.config import Settings, validate_secret_key

try:
    settings = Settings()
    validate_secret_key(settings)
    print("ERROR: Should have raised RuntimeError")
    exit(1)
except RuntimeError as e:
    if "must be at least 32 characters" in str(e):
        print("SUCCESS")
        exit(0)
    else:
        print(f"ERROR: Wrong error message: {e}")
        exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="."
    )

    assert result.returncode == 0, f"Test failed. stdout={result.stdout}, stderr={result.stderr}"
    assert "SUCCESS" in result.stdout


def test_default_secret_in_development_allows():
    """Test that default secret is allowed in development (with warning)."""
    code = """
import os
# Ensure we're NOT in production
os.environ.pop('RAILWAY_ENVIRONMENT', None)
os.environ.pop('ROT_ENV', None)
os.environ['ROT_WEB_SECRET_KEY'] = 'change-me-in-production'

from rot.core.config import Settings, validate_secret_key

try:
    settings = Settings()
    validate_secret_key(settings)  # Should not raise in development
    assert settings.web.secret_key == 'change-me-in-production'
    print("SUCCESS")
    exit(0)
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="."
    )

    assert result.returncode == 0, f"Test failed. stdout={result.stdout}, stderr={result.stderr}"
    assert "SUCCESS" in result.stdout


def test_rot_env_production_triggers_validation():
    """Test that ROT_ENV=production also triggers validation."""
    code = """
import os
os.environ['ROT_ENV'] = 'production'
os.environ['ROT_WEB_SECRET_KEY'] = 'change-me-in-production'

from rot.core.config import Settings, validate_secret_key

try:
    settings = Settings()
    validate_secret_key(settings)
    print("ERROR: Should have raised RuntimeError")
    exit(1)
except RuntimeError as e:
    if "must be set to a strong secret" in str(e):
        print("SUCCESS")
        exit(0)
    else:
        print(f"ERROR: Wrong error message: {e}")
        exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="."
    )

    assert result.returncode == 0, f"Test failed. stdout={result.stdout}, stderr={result.stderr}"
    assert "SUCCESS" in result.stdout
