"""One module per surveillance source. Each defines SOURCE (a fludash.common.Source subclass) and
runs standalone: `python pull/pull_<name>.py [--check] [--force] [--list]`.

To add a source: copy the closest pull_*.py, give it a new `key`, and add the module name below.
The order here is the order of the buttons (and colour slots) on the dashboard.
"""
import importlib

MODULES = ["pull_flusight", "pull_nhsn_hrd", "pull_nssp", "pull_ilinet", "pull_flusurv", "pull_kinsa"]


def sources():
    return [importlib.import_module(f"pull.{m}").SOURCE() for m in MODULES]
