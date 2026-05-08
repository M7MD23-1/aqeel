"""AI-Based PC Builder backend.

This Flask app loads PC component data from an Excel workbook, applies
compatibility rules, runs a selected search algorithm, and serves the static
frontend. It is ready for Render deployment using gunicorn.
"""

from __future__ import annotations

import heapq
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
DATA_FILE = os.path.join(BASE_DIR, "data", "PC_Components_Dataset_small.xlsx")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

CATEGORIES = ["CPU", "Motherboard", "RAM", "Storage", "GPU", "PSU"]
SHEET_MAP = {
    "CPU": "CPUs",
    "Motherboard": "MBs",
    "RAM": "RAMs",
    "Storage": "Storage",
    "GPU": "GPUs",
    "PSU": "PSUs",
}

CURRENCY_RATES = {
    "USD": {"symbol": "$", "rate": 1.0},
    "SAR": {"symbol": "ر.س", "rate": 3.75},
    "AED": {"symbol": "د.إ", "rate": 3.67},
    "KWD": {"symbol": "د.ك", "rate": 0.31},
    "EUR": {"symbol": "€", "rate": 0.92},
}


def as_number(value: Any, default: float = 0.0) -> float:
    """Convert Excel values to float safely."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_yes_no(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "y"}


@lru_cache(maxsize=1)
def load_components() -> Dict[str, List[Dict[str, Any]]]:
    """Load all component sheets from the Excel file.

    The function is cached so free hosting does not reload Excel on every API
    request. Restarting the server refreshes the cache.
    """
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f"Missing data file: {DATA_FILE}")

    components: Dict[str, List[Dict[str, Any]]] = {}
    for category, sheet_name in SHEET_MAP.items():
        df = pd.read_excel(DATA_FILE, sheet_name=sheet_name)
        df = df.where(pd.notnull(df), None)
        records = df.to_dict(orient="records")
        components[category] = [clean_component(category, row) for row in records]
    return components


def clean_component(category: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize numbers and flags for easier compatibility checks."""
    item = dict(item)
    item["category"] = category
    item["price_usd"] = as_number(item.get("price_usd"))

    numeric_fields = [
        "cores", "threads", "base_clock_ghz", "boost_clock_ghz", "tdp_watts",
        "ram_slots", "max_ram_gb", "pcie_version", "m2_slots", "sata_ports",
        "max_pcie_storage_gen", "capacity_gb", "modules", "speed_mhz",
        "read_mbps", "write_mbps", "vram_gb", "wattage",
    ]
    for field in numeric_fields:
        if field in item:
            item[field] = as_number(item.get(field))

    if "integrated_graphics" in item:
        item["integrated_graphics_bool"] = normalize_yes_no(item.get("integrated_graphics"))
    if "nvme_support" in item:
        item["nvme_support_bool"] = normalize_yes_no(item.get("nvme_support"))
    return item


def price_of(build: Dict[str, Dict[str, Any]]) -> float:
    return sum(part.get("price_usd", 0) for part in build.values() if part)


def required_wattage(build: Dict[str, Dict[str, Any]]) -> float:
    cpu = build.get("CPU", {})
    gpu = build.get("GPU", {})
    # Add a safety margin for motherboard, storage, RAM, fans, and transient spikes.
    return cpu.get("tdp_watts", 0) + gpu.get("tdp_watts", 0) + 120


def is_partial_compatible(build: Dict[str, Dict[str, Any]], budget: float) -> bool:
    """Prune states as early as possible while building search trees."""
    if price_of(build) > budget:
        return False

    cpu = build.get("CPU")
    mb = build.get("Motherboard")
    ram = build.get("RAM")
    storage = build.get("Storage")
    psu = build.get("PSU")

    if cpu and mb and str(cpu.get("socket")) != str(mb.get("socket")):
        return False

    if ram and mb and str(ram.get("type")) != str(mb.get("ram_type")):
        return False

    if storage and mb:
        interface = str(storage.get("interface", "")).lower()
        if "nvme" in interface and not mb.get("nvme_support_bool"):
            return False
        if "sata" in interface and mb.get("sata_ports", 0) <= 0:
            return False

    if psu:
        selected_tdp = required_wattage(build)
        # For partial states without CPU/GPU this is intentionally conservative.
        if (cpu or build.get("GPU")) and psu.get("wattage", 0) < selected_tdp:
            return False

    return True


def full_compatibility(build: Dict[str, Dict[str, Any]], budget: float) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    cpu, mb, ram, storage, gpu, psu = [build.get(cat) for cat in CATEGORIES]

    if not all([cpu, mb, ram, storage, psu]):
        issues.append("Missing required components")

    if cpu and mb and str(cpu.get("socket")) != str(mb.get("socket")):
        issues.append("CPU socket does not match motherboard socket")

    if ram and mb and str(ram.get("type")) != str(mb.get("ram_type")):
        issues.append("RAM type does not match motherboard RAM type")

    if storage and mb:
        interface = str(storage.get("interface", "")).lower()
        if "nvme" in interface and not mb.get("nvme_support_bool"):
            issues.append("NVMe storage requires M.2/NVMe support")
        if "sata" in interface and mb.get("sata_ports", 0) <= 0:
            issues.append("SATA storage requires SATA ports")

    if psu and psu.get("wattage", 0) < required_wattage(build):
        issues.append("PSU wattage is not enough for CPU and GPU")

    if price_of(build) > budget:
        issues.append("Total price exceeds budget")

    # Office builds may use integrated graphics. Other purposes normally use a GPU.
    if gpu is None and not (cpu and cpu.get("integrated_graphics_bool")):
        issues.append("No GPU and no integrated graphics available")

    return len(issues) == 0, issues


def component_score(category: str, item: Dict[str, Any], purpose: str) -> float:
    """Score a single component based on the selected purpose."""
    price = max(item.get("price_usd", 0), 1)
    purpose = purpose.lower()

    if category == "CPU":
        perf = item.get("cores", 0) * 8 + item.get("threads", 0) * 2 + item.get("boost_clock_ghz", 0) * 10
        if purpose in {"content creation", "ai workstation", "high-end build"}:
            perf += item.get("cores", 0) * 12
        if purpose == "office" and item.get("integrated_graphics_bool"):
            perf += 25
        return perf

    if category == "GPU":
        perf = item.get("vram_gb", 0) * 20 + item.get("tdp_watts", 0) * 0.12
        if purpose in {"gaming", "ai workstation", "high-end build"}:
            perf *= 1.8
        if purpose == "office":
            perf *= 0.4
        return perf

    if category == "RAM":
        perf = item.get("capacity_gb", 0) * 3 + item.get("speed_mhz", 0) / 200
        if purpose in {"content creation", "ai workstation"}:
            perf *= 1.6
        return perf

    if category == "Storage":
        perf = item.get("capacity_gb", 0) / 50 + item.get("read_mbps", 0) / 120
        if purpose in {"content creation", "high-end build", "ai workstation"} and "nvme" in str(item.get("interface", "")).lower():
            perf *= 1.4
        return perf

    if category == "Motherboard":
        return item.get("m2_slots", 0) * 8 + item.get("sata_ports", 0) * 2 + item.get("max_ram_gb", 0) / 16

    if category == "PSU":
        return item.get("wattage", 0) / 10 + (15 if str(item.get("efficiency", "")).lower() in {"gold", "platinum"} else 0)

    return 0


def build_score(build: Dict[str, Dict[str, Any]], purpose: str, budget: float) -> float:
    total = price_of(build)
    score = sum(component_score(cat, part, purpose) for cat, part in build.items() if part)
    remaining_ratio = max(budget - total, 0) / max(budget, 1)
    purpose_l = purpose.lower()

    if purpose_l in {"office", "budget build"}:
        score += remaining_ratio * 200
    elif purpose_l == "gaming":
        score += component_score("GPU", build.get("GPU", {}), purpose) * 0.8
    elif purpose_l == "content creation":
        score += build.get("CPU", {}).get("cores", 0) * 10 + build.get("RAM", {}).get("capacity_gb", 0) * 2
    elif purpose_l == "ai workstation":
        score += build.get("GPU", {}).get("vram_gb", 0) * 35 + build.get("PSU", {}).get("wattage", 0) / 5
    elif purpose_l == "high-end build":
        score += total / max(budget, 1) * 60

    return round(score, 2)


def sort_and_prune_components(components: Dict[str, List[Dict[str, Any]]], purpose: str, budget: float) -> Dict[str, List[Dict[str, Any]]]:
    """Purpose-based pruning to keep search safe for free hosting.

    The dataset can grow later, so each category is sorted by usefulness and
    limited to a reasonable number of candidates.
    """
    limits = {
        "CPU": 14,
        "Motherboard": 14,
        "RAM": 12,
        "Storage": 12,
        "GPU": 14,
        "PSU": 12,
    }
    purpose_l = purpose.lower()
    result: Dict[str, List[Dict[str, Any]]] = {}

    for category, items in components.items():
        filtered = [x for x in items if x.get("price_usd", 0) <= budget]

        # Office can skip discrete GPUs if an integrated CPU is available.
        if category == "GPU" and purpose_l == "office":
            filtered = filtered[:]

        if purpose_l in {"office", "budget build"}:
            filtered.sort(key=lambda x: (x.get("price_usd", 0), -component_score(category, x, purpose)))
        else:
            filtered.sort(key=lambda x: (-component_score(category, x, purpose), x.get("price_usd", 0)))

        result[category] = filtered[: limits[category]]
    return result


@dataclass(order=True)
class QueueState:
    priority: float
    counter: int
    index: int
    build: Dict[str, Dict[str, Any]]
    cost: float = 0.0


def candidate_options(category: str, components: Dict[str, List[Dict[str, Any]]], build: Dict[str, Dict[str, Any]], purpose: str) -> Iterable[Optional[Dict[str, Any]]]:
    """Return possible choices for the current category.

    Office builds are allowed to use integrated graphics, so GPU can be skipped.
    """
    if category == "GPU" and purpose.lower() == "office":
        yield None
    for item in components.get(category, []):
        yield item


def search_build(budget: float, purpose: str, algorithm: str) -> Dict[str, Any]:
    components = sort_and_prune_components(load_components(), purpose, budget)
    algorithm = algorithm.upper().strip()
    max_states = 8000
    explored = 0
    best: Optional[Dict[str, Dict[str, Any]]] = None
    best_score = -1e18

    def consider(build: Dict[str, Dict[str, Any]]) -> None:
        nonlocal best, best_score
        ok, _ = full_compatibility(build, budget)
        if not ok:
            return
        score = build_score(build, purpose, budget)
        if score > best_score:
            best = dict(build)
            best_score = score

    if algorithm in {"UCS", "A*", "ASTAR", "A"}:
        heap: List[QueueState] = [QueueState(0, 0, 0, {}, 0)]
        counter = 1
        while heap and explored < max_states:
            state = heapq.heappop(heap)
            explored += 1
            if state.index == len(CATEGORIES):
                consider(state.build)
                continue

            category = CATEGORIES[state.index]
            for item in candidate_options(category, components, state.build, purpose):
                new_build = dict(state.build)
                if item is not None:
                    new_build[category] = item
                new_cost = price_of(new_build)
                if not is_partial_compatible(new_build, budget):
                    continue
                if algorithm in {"A*", "ASTAR", "A"}:
                    # Higher component score should be explored earlier, while cost remains a constraint.
                    heuristic = sum(component_score(cat, part, purpose) for cat, part in new_build.items() if part)
                    priority = new_cost - heuristic
                else:
                    priority = new_cost
                heapq.heappush(heap, QueueState(priority, counter, state.index + 1, new_build, new_cost))
                counter += 1
    else:
        stack_or_queue: List[Tuple[int, Dict[str, Dict[str, Any]]]] = [(0, {})]
        while stack_or_queue and explored < max_states:
            index, build = stack_or_queue.pop(0 if algorithm == "BFS" else -1)
            explored += 1
            if index == len(CATEGORIES):
                consider(build)
                continue

            category = CATEGORIES[index]
            options = list(candidate_options(category, components, build, purpose))
            if algorithm == "DFS":
                options = list(reversed(options))
            for item in options:
                new_build = dict(build)
                if item is not None:
                    new_build[category] = item
                if is_partial_compatible(new_build, budget):
                    stack_or_queue.append((index + 1, new_build))

    if best is None:
        return {
            "success": False,
            "message": "No compatible build found within this budget. Increase the budget or choose Budget Build/Office.",
            "algorithm": algorithm,
            "explored_states": explored,
            "compatibility_status": False,
            "issues": ["No compatible build found"],
            "build": {},
            "total_price_usd": 0,
            "score": None,
        }

    ok, issues = full_compatibility(best, budget)
    return {
        "success": True,
        "message": "Compatible build found",
        "algorithm": "A*" if algorithm in {"ASTAR", "A"} else algorithm,
        "explored_states": explored,
        "compatibility_status": ok,
        "issues": issues,
        "build": best,
        "total_price_usd": round(price_of(best), 2),
        "required_wattage": round(required_wattage(best), 2),
        "score": best_score,
    }


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory(FRONTEND_DIR, path)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "data_file_exists": os.path.exists(DATA_FILE)})


@app.route("/api/components")
def api_components():
    try:
        return jsonify({"success": True, "components": load_components()})
    except Exception as exc:  # Keep deployment errors visible in the UI.
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/build", methods=["POST"])
def api_build():
    payload = request.get_json(silent=True) or {}
    budget = as_number(payload.get("budget"), 0)
    purpose = str(payload.get("purpose", "Gaming"))
    algorithm = str(payload.get("algorithm", "BFS"))
    currency = str(payload.get("currency", "USD")).upper()

    if budget <= 0:
        return jsonify({"success": False, "error": "Budget must be greater than zero"}), 400

    try:
        result = search_build(budget, purpose, algorithm)
        currency_info = CURRENCY_RATES.get(currency, CURRENCY_RATES["USD"])
        result["currency"] = currency
        result["currency_symbol"] = currency_info["symbol"]
        result["total_price"] = round(result["total_price_usd"] * currency_info["rate"], 2)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
