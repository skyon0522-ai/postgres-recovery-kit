"""Check pinned raw component blobs and the reviewed recovery adapter."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT, check_modes=False):
    manifest = json.loads((root / "source-copy-manifest.json").read_text())
    entries = [("components/" + component["name"] + "/" + entry["path"], entry)
               for component in manifest["components"] for entry in component["files"]]
    entries += [(entry["path"], entry) for entry in manifest["adapted_files"]]
    changed, hashes = [], {}
    for name, entry in entries:
        path = root / name
        try:
            raw = path.read_bytes()
        except OSError as error:
            changed.append({"path": name, "reason": str(error)})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        hashes[name] = digest
        if digest != entry["sha256"] or len(raw) != entry["bytes"]:
            changed.append({"path": name, "reason": "bytes or SHA-256 mismatch"})
        if "git_blob" in entry:
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if blob != entry["git_blob"]:
                changed.append({"path": name, "reason": "Git blob mismatch"})
        if check_modes and path.stat().st_mode & 0o777 != int(entry["git_mode"][-3:], 8):
            changed.append({"path": name, "reason": "source mode mismatch"})
    license_bytes = (root / "LICENSE").read_bytes()
    if hashlib.sha256(license_bytes).hexdigest() != manifest["components"][0]["license_sha256"]:
        changed.append({"path": "LICENSE", "reason": "MIT notice mismatch"})
    return {"status": "source_verified" if not changed else "source_mismatch",
            "component_files": manifest["copied_source_files"],
            "adapted_files": len(manifest["adapted_files"]),
            "mode_check_enabled": check_modes, "changed": changed, "hashes": hashes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-modes", action="store_true",
                        help="Also verify POSIX source modes after import to a native filesystem or Git.")
    result = verify(check_modes=parser.parse_args().check_modes)
    print(json.dumps({key: value for key, value in result.items() if key != "hashes"}))
    raise SystemExit(0 if result["status"] == "source_verified" else 1)
