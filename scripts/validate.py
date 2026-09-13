#!/usr/bin/env python3
"""Validate the canonical autorules catalog and routing profiles."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ACTIONS = {"direct", "proxy", "reject"}
SELECTORS = {"geosite", "geoip", "domains", "cidrs"}
CATEGORY_RE = re.compile(r"^[a-z0-9][a-z0-9._!-]*$")
DOMAIN_PREFIXES = {"domain", "full", "keyword", "regexp"}


class ValidationError(Exception):
    pass


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValidationError(f"{path}: cannot read TOML: {exc}") from exc


def require_keys(data: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - data.keys())
    if missing:
        raise ValidationError(f"{context}: missing keys: {', '.join(missing)}")


def validate_string_list(values: Any, context: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValidationError(f"{context}: expected a non-empty array")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValidationError(f"{context}: every value must be a non-empty string")
    if len(values) != len(set(values)):
        raise ValidationError(f"{context}: duplicate values are not allowed")
    return values


def validate_catalog(
    path: Path,
) -> tuple[dict[str, Any], dict[str, set[str]], list[str]]:
    data = load_toml(path)
    require_keys(
        data,
        {"schema_version", "upstream", "categories", "profiles"},
        str(path),
    )
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValidationError(f"{path}: unsupported schema_version")

    upstream = data["upstream"]
    if not isinstance(upstream, dict):
        raise ValidationError(f"{path}: upstream must be a table")
    require_keys(
        upstream,
        {"repository", "ref", "geosite_asset", "geoip_asset"},
        f"{path}: upstream",
    )
    for key, value in upstream.items():
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{path}: upstream.{key} must be a non-empty string")

    categories = data["categories"]
    if not isinstance(categories, dict) or set(categories) != {"geosite", "geoip"}:
        raise ValidationError(f"{path}: categories must contain only geosite and geoip")

    result: dict[str, set[str]] = {}
    for kind in ("geosite", "geoip"):
        values = validate_string_list(categories[kind], f"{path}: categories.{kind}")
        invalid = [value for value in values if not CATEGORY_RE.fullmatch(value)]
        if invalid:
            raise ValidationError(f"{path}: invalid {kind} names: {', '.join(invalid)}")
        result[kind] = set(values)
    profiles = data["profiles"]
    if not isinstance(profiles, dict) or set(profiles) != {"ids"}:
        raise ValidationError(f"{path}: profiles must contain only ids")
    profile_ids = validate_string_list(profiles["ids"], f"{path}: profiles.ids")
    invalid_profiles = [
        profile_id for profile_id in profile_ids if not CATEGORY_RE.fullmatch(profile_id)
    ]
    if invalid_profiles:
        raise ValidationError(
            f"{path}: invalid profile ids: {', '.join(invalid_profiles)}"
        )

    return data, result, profile_ids


def validate_domains(values: Any, context: str) -> None:
    for value in validate_string_list(values, context):
        if ":" not in value:
            raise ValidationError(f"{context}: domain rule requires a prefix: {value}")
        prefix, pattern = value.split(":", 1)
        if prefix not in DOMAIN_PREFIXES or not pattern:
            raise ValidationError(f"{context}: invalid domain rule: {value}")


def validate_cidrs(values: Any, context: str) -> None:
    for value in validate_string_list(values, context):
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValidationError(f"{context}: invalid CIDR {value}: {exc}") from exc


def validate_profile(path: Path, categories: dict[str, set[str]]) -> str:
    data = load_toml(path)
    require_keys(data, {"schema_version", "id", "description", "default", "rules"}, str(path))
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValidationError(f"{path}: unsupported schema_version")

    profile_id = data["id"]
    if not isinstance(profile_id, str) or not CATEGORY_RE.fullmatch(profile_id):
        raise ValidationError(f"{path}: invalid profile id")
    if profile_id != path.stem:
        raise ValidationError(f"{path}: profile id must match its filename")
    if not isinstance(data["description"], str) or not data["description"].strip():
        raise ValidationError(f"{path}: description must be a non-empty string")
    if data["default"] not in ACTIONS:
        raise ValidationError(f"{path}: default must be one of {sorted(ACTIONS)}")

    rules = data["rules"]
    if not isinstance(rules, list) or not rules:
        raise ValidationError(f"{path}: rules must be a non-empty array of tables")

    for index, rule in enumerate(rules, start=1):
        context = f"{path}: rules[{index}]"
        if not isinstance(rule, dict):
            raise ValidationError(f"{context}: expected a table")
        unknown = set(rule) - ({"action"} | SELECTORS)
        if unknown:
            raise ValidationError(f"{context}: unknown keys: {', '.join(sorted(unknown))}")
        if rule.get("action") not in ACTIONS:
            raise ValidationError(f"{context}: invalid action")
        selectors = SELECTORS & rule.keys()
        if len(selectors) != 1:
            raise ValidationError(f"{context}: exactly one selector is required")

        selector = selectors.pop()
        values = rule[selector]
        if selector in {"geosite", "geoip"}:
            selected = validate_string_list(values, f"{context}.{selector}")
            missing = sorted(set(selected) - categories[selector])
            if missing:
                raise ValidationError(
                    f"{context}: unknown {selector} categories: {', '.join(missing)}"
                )
        elif selector == "domains":
            validate_domains(values, f"{context}.domains")
        else:
            validate_cidrs(values, f"{context}.cidrs")

    return profile_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        _, categories, catalog_profile_ids = validate_catalog(root / "catalog.toml")
        profile_paths = sorted((root / "profiles").glob("*.toml"))
        if not profile_paths:
            raise ValidationError(f"{root / 'profiles'}: no profiles found")
        profile_ids = [validate_profile(path, categories) for path in profile_paths]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValidationError("duplicate profile ids")
        if set(profile_ids) != set(catalog_profile_ids):
            missing = sorted(set(catalog_profile_ids) - set(profile_ids))
            unlisted = sorted(set(profile_ids) - set(catalog_profile_ids))
            details = []
            if missing:
                details.append(f"missing files: {', '.join(missing)}")
            if unlisted:
                details.append(f"unlisted files: {', '.join(unlisted)}")
            raise ValidationError(f"profile catalog mismatch ({'; '.join(details)})")
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: {len(categories['geosite'])} geosite categories, "
        f"{len(categories['geoip'])} geoip categories, "
        f"{len(profile_ids)} profiles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
