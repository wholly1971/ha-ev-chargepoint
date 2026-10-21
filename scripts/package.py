"""Package tracked source without local tools, customer data, or caches."""

from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
output = root / "dist" / "ev-chargepoint-0.2.1.zip"
output.parent.mkdir(exist_ok=True)
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for filename in files:
        if filename:
            archive.write(root / filename, filename)
with ZipFile(output) as archive:
    assert archive.testzip() is None
    assert "custom_components/ev_chargepoint/manifest.json" in archive.namelist()
    assert not any(
        "__pycache__" in name or name.startswith(".tools/") for name in archive.namelist()
    )
print(output)
