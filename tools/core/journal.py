import json
import sys


def event(name, *, stream=None, **fields):
    if stream is None:
        stream = sys.stderr
    print(json.dumps({"event": name, **fields}, ensure_ascii=False, sort_keys=True,
                     allow_nan=False), file=stream, flush=True)
