"""Local administrator configuration; never accept solver paths from MCP tools."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULT_ROOT = Path(os.environ.get('AQWA_MCP_RUNS') or ROOT / '.aqwa-runs').resolve()
WORK, OUTPUT = RESULT_ROOT / 'jobs', RESULT_ROOT / 'reports'


def input_root():
    value = os.environ.get('AQWA_MCP_INPUTS')
    if not value or not Path(value).is_absolute() or not Path(value).is_dir():
        raise ValueError('Native mode needs AQWA_MCP_INPUTS pointing to an absolute private H00 bundle directory. Use the offline demo without it.')
    return Path(value).resolve()


def solver_path():
    value = os.environ.get('AQWA_MCP_EXE')
    if os.name != 'nt' or not value:
        raise ValueError('Native mode requires Windows and AQWA_MCP_EXE pointing to the locally licensed Aqwa.exe.')
    path = Path(value)
    if not path.is_absolute() or path.name.casefold() != 'aqwa.exe' or not path.is_file():
        raise ValueError('AQWA_MCP_EXE must be the absolute path of an existing Aqwa.exe.')
    return path.resolve()
