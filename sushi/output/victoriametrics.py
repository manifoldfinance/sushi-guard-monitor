import requests
import os
import gzip
import math
import json
from typing import List, Dict

mapping = {
    "token": {
        "metric": "tokenId",
        "labels": ["tokenId", "param", "address", "version"],
    },
    "pool": {"metric": "pool", "labels": ["pair", "param", "address", "version"]},
    "router": {
        "metric": "sushi",
        "labels": ["token0", "token1", "param", "address", "type", "isMev"],
    },
    "bento_strategy": {
        "metric": "bento_strategy",
        "labels": [
            "bento_vault",
            "strategy",
            "param",
            "address",
            "version",
            "experimental",
        ],
    },
    "bento_vault": {
        "metric": "bento_vault",
        "labels": [
            "bento_vault",
            "strategy",
            "param",
            "address",
            "version",
            "experimental",
        ],
    },
}

simple_products = ["swap", "pool", "router", "bento_vault", "bento_strategy"]


def export(timestamp, data):
    metrics_to_export = []

    for product in simple_products:
        metric = mapping[product]["metric"]
        for bento_vault, params in data[product].items():

            for key, value in params.items():
                if key in ["address", "version", "experimental"] or value is None:
                    continue

                has_experiments = product == "special"

                label_values = _get_label_values(
                    params, [bento_vault, key], has_experiments
                )
                label_names = mapping[product]["labels"]

                item = _build_item(metric, label_names, label_values, value, timestamp)
                metrics_to_export.append(item)

    for bento_vault, params in data["router_guard"].items():
        metric = mapping["router_guard"]["metric"]
        for key, value in params.items():
            if (
                key in ["address", "version", "experimental", "strategies"]
                or value is None
            ):
                continue

            label_values = _get_label_values(params, [bento_vault, key], True)
            label_names = mapping["router_guard"]["labels"]

            item = _build_item(metric, label_names, label_values, value, timestamp)
            metrics_to_export.append(item)

        # strategies can have nested structs
        metric = mapping["bento_strategy"]["metric"]
        for strategy, strategy_params in data["bento_strategy"][bento_vault][
            "strategies"
        ].items():
            flat = flatten_dict(strategy_params)
            for key, value in flat.items():
                if key in ["address", "version", "experimental"] or value is None:
                    continue

                label_values = _get_label_values(
                    params, [bento_vault, strategy, key], True
                )
                label_names = mapping["bento_strategy"]["labels"]

                item = _build_item(
                    metric, label_names, label_values, value or 0, timestamp
                )
                metrics_to_export.append(item)

    # post all metrics for this timestamp at once
    _post(metrics_to_export)


def _build_item(metric, label_names, label_values, value, timestamp):
    ts_millis = math.floor(timestamp) * 1000
    meta = dict(zip(map(_sanitize, label_names), label_values))
    meta["__name__"] = metric
    return {"metric": meta, "values": [_sanitize(value)], "timestamps": [ts_millis]}


def _to_jsonl_gz(metrics_to_export: List[Dict]):
    lines = []
    for item in metrics_to_export:
        lines.append(json.dumps(item))

    jsonlines = "\n".join(lines)
    return gzip.compress(bytes(jsonlines, "utf-8"))


def _post(metrics_to_export: List[Dict]):
    data = _to_jsonl_gz(metrics_to_export)
    base_url = os.environ.get("VM_URL", "http://victoria-metrics:8428")
    url = f"{base_url}/api/v1/import"
    headers = {"Connection": "close", "Content-Encoding": "gzip"}
    with requests.Session() as session:
        session.post(url=url, data=data, headers=headers)


def _sanitize(value):
    if isinstance(value, bool):
        return int(value)
    elif isinstance(value, str):
        return value.replace('"', "")  # e.g. '"tokenName" 0.1.0 0x340832'

    return value


def flatten_dict(d):
    def items():
        for key, value in d.items():
            if isinstance(value, dict):
                for subkey, subvalue in flatten_dict(value).items():
                    yield key + "." + subkey, subvalue
            else:
                yield key, value

    return dict(items())


def _get_label_values(params, inital_labels, experimental=False):
    address = _get_string_label(params, "address")
    version = _get_string_label(params, "version")
    label_values = inital_labels + [address, version]
    if experimental:
        experimental_label = _get_bool_label(params, "experimental")
        label_values.append(experimental_label)

    return label_values


def _get_bool_label(a_dict, key):
    return "true" if key in a_dict and a_dict[key] == True else "false"


def _get_string_label(a_dict, key):
    return str(a_dict[key]) if key in a_dict else "n/a"
