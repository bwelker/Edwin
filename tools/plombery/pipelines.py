"""Edwin Plombery Pipelines -- job definitions for the scheduler."""

import os
import subprocess
import sys
from pathlib import Path

from plombery import task, get_logger

# Auto-detect EDWIN_HOME: env var > ~/Edwin
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", Path.home() / "Edwin"))
PYTHON = os.environ.get("PYTHON", sys.executable)
PYTHON_312 = os.environ.get("PYTHON_312", PYTHON)

logger = get_logger()


def _run_command(cmd: str, python: str = PYTHON, timeout: int = 7200) -> dict:
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=str(EDWIN_HOME),
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "status": "ok" if result.returncode == 0 else "error",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "exit_code": -1}
    except Exception as e:
        return {"status": "error", "error": str(e), "exit_code": -1}


# -- Pipeline: O365 Sync ------------------------------------------------------

@task()
def sync_o365():
    """Sync O365 mail, calendar, teams, sharepoint."""
    logger.info("Starting O365 sync")
    result = _run_command(f"{PYTHON} connectors/o365/o365 sync all")
    logger.info(f"O365 sync: {result['status']}")
    return result


# -- Pipeline: Google Sync ----------------------------------------------------

@task()
def sync_google():
    """Sync Gmail and Google Calendar."""
    logger.info("Starting Google sync")
    result = _run_command(f"{PYTHON} connectors/google/google sync all")
    logger.info(f"Google sync: {result['status']}")
    return result


# -- Pipeline: iMessage Sync --------------------------------------------------

@task()
def sync_imessage():
    """Sync iMessage conversations."""
    logger.info("Starting iMessage sync")
    result = _run_command(f"{PYTHON} connectors/imessage/imessage sync all")
    logger.info(f"iMessage sync: {result['status']}")
    return result


# -- Pipeline: Indexer --------------------------------------------------------

@task()
def run_indexer():
    """Run the memory indexer (Qdrant embeddings)."""
    logger.info("Starting indexer")
    result = _run_command(f"{PYTHON_312} tools/indexer/indexer sync", python=PYTHON_312)
    logger.info(f"Indexer: {result['status']}")
    return result


# -- Pipeline: Session Watcher ------------------------------------------------

@task()
def run_session_watcher():
    """Check session state and capture if needed."""
    logger.info("Running session watcher")
    result = _run_command(f"{PYTHON} tools/session-watcher/capture")
    logger.info(f"Session watcher: {result['status']}")
    return result


# -- Pipeline: Systems Report -------------------------------------------------

@task()
def run_systems_report():
    """Generate nightly systems health report."""
    logger.info("Generating systems report")
    result = _run_command(f"{PYTHON} tools/systems-report/report")
    logger.info(f"Systems report: {result['status']}")
    return result


# -- Pipeline: PM Export ------------------------------------------------------

@task()
def run_pm_export():
    """Export PM items to Obsidian Action Tracker."""
    logger.info("Running PM export")
    result = _run_command(f"{PYTHON} briefing-book/scripts/pm-export")
    logger.info(f"PM export: {result['status']}")
    return result
