"""
Helpers for downloading publicly available datasets for demo/testing.

These functions are used by the Streamlit app and can also be used from CLI tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ZENODO_API_BASE = "https://zenodo.org/api/records"


@dataclass(frozen=True)
class PublicDatasetOption:
    """Configuration for a known public dataset source."""

    key: str
    title: str
    record_id: int
    preferred_file_patterns: List[str]
    source_url: str
    description: str


PUBLIC_DATASET_OPTIONS: List[PublicDatasetOption] = [
    PublicDatasetOption(
        key="github_oss_2017",
        title="GitHub Open Source Survey 2017",
        record_id=806811,
        preferred_file_patterns=["negative_incidents.csv", "survey_data.csv"],
        source_url="https://zenodo.org/records/806811",
        description=(
            "Large open survey dataset from GitHub. Includes open-response incident text "
            "and survey responses."
        ),
    ),
    PublicDatasetOption(
        key="science4policy_2024",
        title="Science4Policy Kit Survey Responses (Public)",
        record_id=14275894,
        preferred_file_patterns=["dataset 6.csv", "dataset 1.csv", ".csv"],
        source_url="https://zenodo.org/records/14275894",
        description=(
            "Public survey response datasets with question-answer structure and anonymized data."
        ),
    ),
]


def get_public_dataset_option(key: str) -> PublicDatasetOption:
    for option in PUBLIC_DATASET_OPTIONS:
        if option.key == key:
            return option
    raise KeyError(f"Unknown dataset key: {key}")


def fetch_zenodo_record_metadata(record_id: int, timeout_seconds: int = 45) -> Dict[str, Any]:
    """
    Fetch Zenodo record metadata from the public REST API.
    """
    url = f"{ZENODO_API_BASE}/{record_id}"
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def _extract_file_rows(record_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize file metadata rows from different Zenodo response shapes.
    """
    files = record_json.get("files", [])
    rows: List[Dict[str, Any]] = []
    for item in files:
        key = str(item.get("key", "")).strip()
        links = item.get("links", {}) or {}
        # Usually "self" is a direct download URL in Zenodo record APIs.
        download_url = str(links.get("self") or links.get("download") or "").strip()
        size = int(item.get("size", 0) or 0)
        checksum = str(item.get("checksum", "")).strip()
        if key:
            rows.append(
                {
                    "key": key,
                    "download_url": download_url,
                    "size": size,
                    "checksum": checksum,
                }
            )
    return rows


def pick_preferred_file(
    file_rows: List[Dict[str, Any]],
    preferred_patterns: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Pick the best file using case-insensitive pattern priority, then CSV fallback.
    """
    if not file_rows:
        return None

    lowered = [(row, row["key"].lower()) for row in file_rows]
    for pattern in preferred_patterns:
        needle = pattern.lower()
        for row, key_lower in lowered:
            if needle in key_lower:
                return row

    for row, key_lower in lowered:
        if key_lower.endswith(".csv"):
            return row

    return file_rows[0]


def download_file(url: str, destination: Path, timeout_seconds: int = 120) -> Path:
    """
    Download a file by URL to destination path.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, timeout=timeout_seconds, stream=True) as response:
        response.raise_for_status()
        with destination.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return destination


def download_public_dataset(
    option_key: str,
    target_dir: Path,
) -> Dict[str, Any]:
    """
    Download one known dataset file for the selected option and return metadata.
    """
    option = get_public_dataset_option(option_key)
    record_json = fetch_zenodo_record_metadata(option.record_id)
    file_rows = _extract_file_rows(record_json)
    chosen = pick_preferred_file(file_rows, option.preferred_file_patterns)
    if not chosen:
        raise ValueError(f"No files found in record {option.record_id}.")

    file_name = chosen["key"].replace("/", "_")
    download_url = chosen["download_url"]
    if not download_url:
        raise ValueError(f"No download URL available for file: {chosen['key']}")

    destination = target_dir / file_name
    download_file(download_url, destination)

    return {
        "dataset_title": option.title,
        "dataset_key": option.key,
        "record_id": option.record_id,
        "record_url": option.source_url,
        "downloaded_file": str(destination),
        "downloaded_file_name": file_name,
        "download_url": download_url,
        "all_files": file_rows,
        "chosen_file": chosen,
        "description": option.description,
    }
