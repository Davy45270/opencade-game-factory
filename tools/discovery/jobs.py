"""Identité d'un job initial-discovery calculée sur ses entrées Git."""

import hashlib

from tools.core.catalog import json_text


def job_id(inputs):
    ordered = sorted(inputs, key=lambda item: (item["name"], item["provider"], item["commit"]))
    return hashlib.sha256(json_text(ordered).encode()).hexdigest()[:16]


def job_for(template, inputs):
    ordered = [{"name": name, "provider": provider, "commit": commit}
               for name, provider, commit in sorted(set(inputs))]
    return job_id(ordered), {**template, "inputs": ordered}
