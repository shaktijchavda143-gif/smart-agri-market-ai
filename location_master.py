"""Code-first, validated Gujarat LGD location master helpers.

All identity decisions are based on the official LGD district/sub-district/village code
chain. Gujarati/English aliases are for resolving user-facing labels only; they do not
replace the codes or allow a village to cross its district/taluka parent.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

EXPECTED_STATE_CODE = "24"
EXPECTED_SOURCE_URL = "https://lgdirectory.gov.in/demo/downloadDirectory.do"
_MASTER_CACHE: Optional[Dict[str, Any]] = None
_MASTER_INDEX: Optional[Dict[str, Any]] = None
_MASTER_CACHE_STAMP: Optional[Tuple[str, int, int]] = None


class LocationMasterError(ValueError):
    """Raised when a location master is incomplete or internally inconsistent."""


def _s(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def normalize_location_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", _s(value).lower())
    text = text.replace("ી", "િ").replace("ૂ", "ુ").replace("ઊ", "ઉ").replace("ઈ", "ઇ")
    text = text.replace("ં", "").replace("ઁ", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return "".join(ch for ch in text if ch.isalnum() or "\u0a80" <= ch <= "\u0aff")


def _iter_aliases(entry: Mapping[str, Any]) -> List[str]:
    values = [_s(entry.get("name_en")), _s(entry.get("name_gu"))]
    raw = entry.get("aliases", [])
    if isinstance(raw, list):
        values.extend(_s(value) for value in raw)
    # Future schema may include an on-screen disambiguation label.
    values.extend([_s(entry.get("label"))])
    return [v for v in values if v]


def _is_alias(entry: Mapping[str, Any], candidate: str) -> bool:
    target = normalize_location_text(candidate)
    return bool(target) and any(normalize_location_text(alias) == target for alias in _iter_aliases(entry))


def validate_master_data(
    data: Mapping[str, Any], *, minimum_villages: int = 10_000,
    minimum_districts: int = 20, minimum_talukas: int = 100,
) -> Dict[str, int]:
    if data.get("schema_version") != 1:
        raise LocationMasterError("schema_version must be 1")
    source = data.get("source")
    if not isinstance(source, Mapping):
        raise LocationMasterError("source metadata is missing")
    if _s(source.get("state_code")) != EXPECTED_STATE_CODE:
        raise LocationMasterError("master must contain Gujarat LGD state code 24")
    if "lgdirectory.gov.in" not in _s(source.get("source_url")):
        raise LocationMasterError("source_url must identify the official LGD portal")
    districts = data.get("districts")
    if not isinstance(districts, list) or not districts:
        raise LocationMasterError("districts must be a non-empty list")

    district_codes: Dict[str, str] = {}
    taluka_parent: Dict[str, str] = {}
    taluka_codes: Dict[str, Tuple[str, str]] = {}
    village_codes: Dict[str, Tuple[str, str, str]] = {}
    village_count = 0
    missing_gujarati_aliases = 0
    local_source_counts: Dict[str, int] = {}

    for district in districts:
        if not isinstance(district, Mapping):
            raise LocationMasterError("district entry must be an object")
        dcode, den, dgu = _s(district.get("code")), _s(district.get("name_en")), _s(district.get("name_gu"))
        if not dcode or not den or not dgu:
            raise LocationMasterError("district has blank LGD code or name")
        if dcode in district_codes and district_codes[dcode] != den:
            raise LocationMasterError(f"district code {dcode} maps to multiple names")
        district_codes[dcode] = den
        if not dgu:
            missing_gujarati_aliases += 1
        local_source_counts[_s(district.get("name_gu_source")) or "unspecified"] = local_source_counts.get(_s(district.get("name_gu_source")) or "unspecified", 0) + 1
        if "aliases" in district and (not isinstance(district.get("aliases"), list) or not _is_alias(district, den)):
            raise LocationMasterError(f"district {dcode} aliases must include the official English name")
        talukas = district.get("talukas")
        if not isinstance(talukas, list) or not talukas:
            raise LocationMasterError(f"district {dcode} has no talukas")

        for taluka in talukas:
            if not isinstance(taluka, Mapping):
                raise LocationMasterError(f"district {dcode} has a malformed taluka entry")
            tcode, ten, tgu = _s(taluka.get("code")), _s(taluka.get("name_en")), _s(taluka.get("name_gu"))
            if not tcode or not ten or not tgu:
                raise LocationMasterError(f"district {dcode} has taluka with blank LGD code or name")
            if _s(taluka.get("district_code")) != dcode:
                raise LocationMasterError(f"taluka {tcode} has invalid district parent; expected {dcode}")
            prior_parent = taluka_parent.get(tcode)
            if prior_parent is not None and prior_parent != dcode:
                raise LocationMasterError(f"taluka code {tcode} belongs to multiple districts")
            prior_taluka = taluka_codes.get(tcode)
            if prior_taluka is not None and prior_taluka != (dcode, ten):
                raise LocationMasterError(f"taluka code {tcode} maps to multiple names/parents")
            taluka_parent[tcode] = dcode
            taluka_codes[tcode] = (dcode, ten)
            local_source_counts[_s(taluka.get("name_gu_source")) or "unspecified"] = local_source_counts.get(_s(taluka.get("name_gu_source")) or "unspecified", 0) + 1
            if "aliases" in taluka and (not isinstance(taluka.get("aliases"), list) or not _is_alias(taluka, ten)):
                raise LocationMasterError(f"taluka {tcode} aliases must include the official English name")
            villages = taluka.get("villages")
            if not isinstance(villages, list) or not villages:
                raise LocationMasterError(f"taluka {tcode} has no villages")

            for village in villages:
                if not isinstance(village, Mapping):
                    raise LocationMasterError(f"taluka {tcode} has a malformed village entry")
                vcode, ven, vgu = _s(village.get("code")), _s(village.get("name_en")), _s(village.get("name_gu"))
                if not vcode or not ven or not vgu:
                    raise LocationMasterError(f"taluka {tcode} has village with blank LGD code or name")
                if _s(village.get("district_code")) != dcode:
                    raise LocationMasterError(f"village {vcode} has invalid district parent")
                if _s(village.get("taluka_code")) != tcode:
                    raise LocationMasterError(f"village {vcode} has invalid taluka parent")
                if vcode in village_codes:
                    old = village_codes[vcode]
                    raise LocationMasterError(f"duplicate village LGD code {vcode}; first record={old}")
                village_codes[vcode] = (dcode, tcode, ven)
                village_count += 1
                local_source_counts[_s(village.get("name_gu_source")) or "unspecified"] = local_source_counts.get(_s(village.get("name_gu_source")) or "unspecified", 0) + 1
                if "aliases" in village and (not isinstance(village.get("aliases"), list) or not _is_alias(village, ven)):
                    raise LocationMasterError(f"village {vcode} aliases must include the official English name")
                if not vgu:
                    missing_gujarati_aliases += 1

    if village_count < minimum_villages:
        raise LocationMasterError(f"only {village_count} villages found; refusing to accept a partial Gujarat export (minimum completeness guard: {minimum_villages})")
    if len(district_codes) < minimum_districts or len(taluka_codes) < minimum_talukas:
        raise LocationMasterError("district/taluka counts are too small for a complete Gujarat master "
            f"(districts={len(district_codes)}, talukas={len(taluka_codes)}; minimums={minimum_districts}/{minimum_talukas})")
    return {"districts": len(district_codes), "talukas": len(taluka_codes), "villages": village_count,
            "missing_gujarati_aliases": missing_gujarati_aliases, "name_source_counts": local_source_counts}


def build_location_index(master: Mapping[str, Any]) -> Dict[str, Any]:
    districts_by_code: Dict[str, Mapping[str, Any]] = {}
    talukas_by_code: Dict[str, Mapping[str, Any]] = {}
    villages_by_code: Dict[str, Mapping[str, Any]] = {}
    talukas_by_parent: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    villages_by_parent: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
    for district in master.get("districts", []):
        dc = _s(district.get("code")); districts_by_code[dc] = district
        for taluka in district.get("talukas", []):
            tc = _s(taluka.get("code")); talukas_by_code[tc] = taluka; talukas_by_parent[(dc, tc)] = taluka
            for village in taluka.get("villages", []):
                vc = _s(village.get("code")); villages_by_code[vc] = village; villages_by_parent[(dc, tc, vc)] = village
    return {"districts": districts_by_code, "talukas": talukas_by_code, "villages": villages_by_code,
            "talukas_by_parent": talukas_by_parent, "villages_by_parent": villages_by_parent}


def load_location_master(path: Optional[Path] = None) -> Tuple[Dict[str, Any], Dict[str, int]]:
    global _MASTER_CACHE, _MASTER_INDEX, _MASTER_CACHE_STAMP
    master_path = path or Path(__file__).with_name("gujarat_locations.json")
    if not master_path.exists():
        raise FileNotFoundError(f"Official location master not installed: {master_path}. Import the full LGD Gujarat export before enabling code-based location selection.")
    stat = master_path.stat()
    stamp = (str(master_path.resolve()), stat.st_mtime_ns, stat.st_size)
    if path is None and _MASTER_CACHE is not None and _MASTER_CACHE_STAMP == stamp:
        return _MASTER_CACHE, validate_master_data(_MASTER_CACHE)
    try:
        data = json.loads(master_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LocationMasterError(f"invalid location JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LocationMasterError("location master root must be an object")
    counts = validate_master_data(data)
    if path is None:
        _MASTER_CACHE, _MASTER_INDEX, _MASTER_CACHE_STAMP = data, build_location_index(data), stamp
    return data, counts


def get_location_master_and_index() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    master, _ = load_location_master()
    global _MASTER_INDEX
    if _MASTER_INDEX is None:
        _MASTER_INDEX = build_location_index(master)
    return master, _MASTER_INDEX


def _find_alias(entries: List[Mapping[str, Any]], candidate: str) -> Optional[Mapping[str, Any]]:
    hits = [entry for entry in entries if _is_alias(entry, candidate)]
    # Repeated aliases are fine only when they resolve to the same LGD entity code.
    unique = {_s(entry.get("code")): entry for entry in hits}
    return next(iter(unique.values())) if len(unique) == 1 else None


def validate_location_codes(district_code: Any, taluka_code: Any, village_code: Any, *, master: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    dc, tc, vc = _s(district_code), _s(taluka_code), _s(village_code)
    if not dc or not tc or not vc:
        return None
    index = build_location_index(master)
    district = index["districts"].get(dc)
    taluka = index["talukas_by_parent"].get((dc, tc))
    village = index["villages_by_parent"].get((dc, tc, vc))
    if not district or not taluka or not village:
        return None
    return {"district_code": dc, "district": _s(district.get("name_gu") or district.get("name_en")),
            "taluka_code": tc, "taluka": _s(taluka.get("name_gu") or taluka.get("name_en")),
            "village_code": vc, "village": _s(village.get("name_gu") or village.get("name_en"))}


def validate_location_filter_codes(
    district_code: Any = "", taluka_code: Any = "", village_code: Any = "", *, master: Mapping[str, Any]
) -> Optional[Dict[str, str]]:
    """Validate optional search filters; parent codes are required when child codes are present."""
    dc, tc, vc = _s(district_code), _s(taluka_code), _s(village_code)
    if not any((dc, tc, vc)):
        return {"district_code": "", "district": "", "taluka_code": "", "taluka": "", "village_code": "", "village": ""}
    index = build_location_index(master)
    district = index["districts"].get(dc) if dc else None
    if dc and district is None:
        return None
    taluka = None
    village = None
    if tc:
        if not dc:
            return None
        taluka = index["talukas_by_parent"].get((dc, tc))
        if taluka is None:
            return None
    if vc:
        if not dc or not tc:
            return None
        village = index["villages_by_parent"].get((dc, tc, vc))
        if village is None:
            return None
    return {
        "district_code": dc, "district": _s((district or {}).get("name_gu") or (district or {}).get("name_en")),
        "taluka_code": tc, "taluka": _s((taluka or {}).get("name_gu") or (taluka or {}).get("name_en")),
        "village_code": vc, "village": _s((village or {}).get("name_gu") or (village or {}).get("name_en")),
    }


def location_labels_match_codes(
    selection: Mapping[str, Any], *, district: Any = "", taluka: Any = "", village: Any = "",
    master: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Match supplied display names to the entities identified by their validated LGD codes.

    This is deliberately entity-scoped rather than a global name lookup: LGD can contain
    two villages with identical English/Gujarati names inside one taluka. Their codes
    still distinguish the entities, so a valid code chain must not be rejected just
    because the display name itself is ambiguous.
    """
    use_master = master
    if use_master is None:
        try: use_master, _ = load_location_master()
        except (FileNotFoundError, LocationMasterError): return False
    index = build_location_index(use_master)
    checks = (
        ("district", district, _s(selection.get("district_code")), index["districts"]),
        ("taluka", taluka, _s(selection.get("taluka_code")), index["talukas"]),
        ("village", village, _s(selection.get("village_code")), index["villages"]),
    )
    for _kind, raw_label, code, items in checks:
        label = _s(raw_label)
        if not label:
            continue
        entry = items.get(code) if code else None
        if entry is None or not _is_alias(entry, label):
            return False
    return True


def resolve_location_names(
    district: Any = "", taluka: Any = "", village: Any = "", *, master: Mapping[str, Any]
) -> Optional[Dict[str, str]]:
    """Resolve text-only legacy labels to unique LGD codes, without cross-parent guessing."""
    district_text, taluka_text, village_text = _s(district), _s(taluka), _s(village)
    districts = list(master.get("districts", []))
    selected_district = _find_alias(districts, district_text) if district_text else None
    if district_text and selected_district is None:
        return None
    if not district_text and (taluka_text or village_text):
        # A child label without a parent can be ambiguous; never guess a district.
        return None
    tc = ""; vc = ""; taluka_entry = None; village_entry = None
    if taluka_text:
        taluka_entry = _find_alias(list(selected_district.get("talukas", [])), taluka_text)
        if taluka_entry is None: return None
        tc = _s(taluka_entry.get("code"))
    if village_text:
        if taluka_entry is None: return None
        village_entry = _find_alias(list(taluka_entry.get("villages", [])), village_text)
        if village_entry is None: return None
        vc = _s(village_entry.get("code"))
    return {
        "district_code": _s(selected_district.get("code")) if selected_district else "",
        "district": _s(selected_district.get("name_gu") or selected_district.get("name_en")) if selected_district else "",
        "taluka_code": tc, "taluka": _s(taluka_entry.get("name_gu") or taluka_entry.get("name_en")) if taluka_entry else "",
        "village_code": vc, "village": _s(village_entry.get("name_gu") or village_entry.get("name_en")) if village_entry else "",
    }


def resolve_location_selection(
    *, district_code: Any = "", taluka_code: Any = "", village_code: Any = "",
    district: Any = "", taluka: Any = "", village: Any = "", master: Optional[Mapping[str, Any]] = None,
    require_village: bool = True,
) -> Optional[Dict[str, str]]:
    """Validate supplied codes, or safely resolve legacy labels to codes.

    Explicit codes take precedence and must form one valid parent chain. If code fields
    were omitted by an older client, all three exact labels must uniquely resolve inside
    their parent chain before they can be accepted.
    """
    use_master = master
    if use_master is None:
        try: use_master, _ = load_location_master()
        except (FileNotFoundError, LocationMasterError): return None
    codes = (_s(district_code), _s(taluka_code), _s(village_code))
    if any(codes):
        if require_village:
            result = validate_location_codes(*codes, master=use_master)
        else:
            result = validate_location_filter_codes(*codes, master=use_master)
        if result is None: return None
        return result
    result = resolve_location_names(district, taluka, village, master=use_master)
    if not result: return None
    if require_village and not result.get("village_code"): return None
    if not require_village and any((_s(district), _s(taluka), _s(village))) and not result.get("district_code"):
        return None
    return result


def find_district(master: Mapping[str, Any], candidate: str) -> Optional[Mapping[str, Any]]:
    return _find_alias(list(master.get("districts", [])), candidate)


def find_taluka(master: Mapping[str, Any], district_code: str, candidate: str) -> Optional[Mapping[str, Any]]:
    district = next((d for d in master.get("districts", []) if _s(d.get("code")) == _s(district_code)), None)
    return _find_alias(list(district.get("talukas", [])), candidate) if district else None


def find_village(master: Mapping[str, Any], district_code: str, taluka_code: str, candidate: str) -> Optional[Mapping[str, Any]]:
    taluka = None
    for district in master.get("districts", []):
        if _s(district.get("code")) == _s(district_code):
            taluka = next((t for t in district.get("talukas", []) if _s(t.get("code")) == _s(taluka_code)), None)
            break
    return _find_alias(list(taluka.get("villages", [])), candidate) if taluka else None
