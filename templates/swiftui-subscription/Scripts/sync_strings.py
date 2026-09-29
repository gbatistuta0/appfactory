#!/usr/bin/env python3
"""Merge the strings extracted by the last simulator build into Resources/Localizable.xcstrings.

Usage (from the app dir):
  xcodebuild build -scheme <App> -destination 'generic/platform=iOS Simulator' -derivedDataPath build/DerivedData
  python3 Scripts/sync_strings.py [--derived-data build/DerivedData]

New keys arrive untranslated (state "new"); LocalizationCompletenessTests then fails until every
language in app.spec.json locales.app is filled (localize_apply / the growth role). Keys that no
longer appear in code AND have no translations are removed; everything else is kept.
"""
import argparse
import glob
import json
import os
import subprocess

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(APP, "Resources", "Localizable.xcstrings")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--derived-data", default=os.path.join(APP, "build", "DerivedData"))
    args = ap.parse_args()
    files = [f for f in glob.glob(os.path.join(args.derived_data, "Build/Intermediates.noindex/*.build/"
                                               "Debug-iphonesimulator/*.build/Objects-normal/*/*.stringsdata"))
             if "Tests.build" not in f]
    if not files:
        raise SystemExit("no .stringsdata found — build the app for the simulator first")
    subprocess.run(["xcrun", "xcstringstool", "sync", CATALOG, "--stringsdata", *files], check=True)
    with open(CATALOG, encoding="utf-8") as f:
        data = json.load(f)
    stale = [k for k, v in data["strings"].items()
             if v.get("extractionState") == "stale" and not v.get("localizations")]
    for k in stale:
        del data["strings"][k]
    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, separators=(",", " : "), sort_keys=True)
        f.write("\n")
    print(f"{len(data['strings'])} keys ({len(stale)} stale removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
