"""
System Diagnostics Utilities

Provides version info on the Python instances used.
"""

import importlib
import os
import sys

def get_pystack_diagnostics(requirements_file="requirements-dev.txt") -> dict:
    """Collect system diagnostics into a dictionary."""


    # todo loop over all installed packages and versions

    diagnostics = {
        "Python": sys.version,
        "Compiler": sys.version_info,
        "Platform": sys.platform,
        "Executable": sys.executable,
        "DevStack": dict()
    }
    if os.path.exists(requirements_file):
        with open(requirements_file) as f:
            for line in f:
                line = line.strip()

                omit_info = "-omit-info" in line
                pkg_name = line.split()[0]
                if not omit_info:
                    try:
                        import_pkg_name = pkg_name
                        if "import-name" in line: # split on "import-name" and take the remainder
                            try:
                                import_pkg_name = line.split("import-name", 1)[1].strip()
                            except IndexError:
                                pass  # fallback to pkg_name if malformed
                        module = importlib.import_module(import_pkg_name)
                        version = getattr(module, "__version__", "N/A") # Version not available
                        diagnostics["DevStack"][pkg_name] = version
                    except ImportError:
                        diagnostics["DevStack"][pkg_name] = "not_installed" # Not Installed
                        pass

    return diagnostics
 
def pystack_summary():
    """Return a summary of the system's Python environment."""
    stackinfo = get_pystack_diagnostics()
    retstr = f"Python {stackinfo['Python'].split()[0]  } | "

    devStackStr = [f"{key}: {value}" for key, value in stackinfo['DevStack'].items()]
    retstr += ', '.join(devStackStr)

    return retstr

if __name__ == "__main__":
    print(pystack_summary())