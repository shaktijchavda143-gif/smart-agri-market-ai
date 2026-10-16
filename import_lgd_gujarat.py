#!/usr/bin/env python3
"""Import official LGD Gujarat exports into the app/backend location master.

Supports the official Microsoft SpreadsheetML `.xls` export as well as CSV/XLSX.
English LGD names and numeric codes remain the source-of-truth. Gujarati local names
are preserved when genuinely present, reviewed legacy labels are applied only against
matched official code chains, and remaining names get transparent phonetic Gujarati
transliteration while retaining English names in `aliases`.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
import difflib
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai_backend"))
from location_master import LocationMasterError, validate_master_data  # noqa: E402

STATE_CODE = "24"
LGD_URL = "https://lgdirectory.gov.in/demo/downloadDirectory.do"
SS_NS = "urn:schemas-microsoft-com:office:spreadsheet"
NS = {"ss": SS_NS}

ALIASES = {
    "state_code": ["State Code", "State Code*", "State Code (LGD)"],
    "state_name_en": ["State Name (In English)", "State Name", "State Name (English)"],
    "district_code": ["District Code", "District Code (LGD)"],
    "district_en": ["District Name (In English)", "District Name (English)", "District Name"],
    "district_gu": ["District Name (In Local)", "District Name (In Gujarati)", "District Name (Local)"],
    "taluka_code": ["Sub-District Code", "Sub District Code", "Sub-District Code (LGD)"],
    "taluka_en": ["Sub-District Name (In English)", "Sub-District Name", "Sub District Name", "Sub-District Name (English)"],
    "taluka_gu": ["Sub-District Name(In Local)", "Sub-District Name (In Local)", "Sub District Name (In Local)", "Sub-District Name (Gujarati)"],
    "village_code": ["Village Code", "Village Code (LGD)"],
    "village_en": ["Village Name (In English)", "Village Name (In Englsih)", "Village Name", "Village Name (English)"],
    "village_gu": ["Village Name (In Local)", "Village Name (In Gujarati)", "Village Name (Local)"],
    "village_status": ["Village Status", "Status"],
}

# Gujarati names already established in the app/reviewed district list. A current
# official LGD local-script name takes precedence over this fallback map.
DISTRICT_GU = {
    "Ahmedabad": "અમદાવાદ", "Amreli": "અમરેલી", "Anand": "આણંદ", "Arvalli": "અરવલ્લી",
    "Banas Kantha": "બનાસકાંઠા", "Bharuch": "ભરૂચ", "Bhavnagar": "ભાવનગર", "Botad": "બોટાદ",
    "Chhotaudepur": "છોટા ઉદેપુર", "Dahod": "દાહોદ", "Dangs": "ડાંગ", "Devbhumi Dwarka": "દેવભૂમિ દ્વારકા",
    "Gandhinagar": "ગાંધીનગર", "Gir Somnath": "ગીર સોમનાથ", "Jamnagar": "જામનગર", "Junagadh": "જૂનાગઢ",
    "Kachchh": "કચ્છ", "Kheda": "ખેડા", "Mahesana": "મહેસાણા", "Mahisagar": "મહીસાગર",
    "Morbi": "મોરબી", "Narmada": "નર્મદા", "Navsari": "નવસારી", "Panch Mahals": "પંચમહાલ",
    "Patan": "પાટણ", "Porbandar": "પોરબંદર", "Rajkot": "રાજકોટ", "Sabar Kantha": "સાબરકાંઠા",
    "Surat": "સુરત", "Surendranagar": "સુરેન્દ્રનગર", "Tapi": "તાપી", "Vadodara": "વડોદરા",
    "Valsad": "વલસાડ", "Vav-Tharad": "વાવ-થરાદ",
}

# Official English spellings -> established Gujarati spellings for commonly used
# talukas. Other talukas are transliterated from the official English name.
TALUKA_GU = {
    "Gir Gadhda": "ગીર ગઢડા", "Patan-Veraval": "પાટણ-વેરાવળ", "Veraval City": "વેરાવળ શહેર",
    "Una": "ઉના", "Talala": "તાલાલા", "Kodinar": "કોડીનાર", "Sutrapada": "સુત્રાપાડા",
    "Junagadh": "જૂનાગઢ", "Keshod": "કેશોદ", "Mangrol": "માંગરોળ", "Malia Hatina": "માળિયા હાટીના",
    "Visavadar": "વિસાવદર", "Mendarda": "મેંદરડા", "Vanthali": "વંથલી", "Bhesan": "ભેંસાણ", "Manavadar": "માણાવદર",
    "Amreli": "અમરેલી", "Rajula": "રાજુલા", "Jafrabad": "જાફરાબાદ", "Khambha": "ખાંભા", "Dhari": "ધારી",
    "Savarkundla": "સાવરકુંડલા", "Bagasara": "બગસરા", "Babra": "બાબરા", "Lathi": "લાઠી", "Kukavav Vadia": "કુકાવાવ-વડિયા", "Lilia": "લીલીયા",
    "Rajkot": "રાજકોટ", "Gondal": "ગોંડલ", "Jetpur": "જેતપુર", "Dhoraji": "ધોરાજી", "Upleta": "ઉપલેટા", "Jasdan": "જસદણ",
    "Bhavnagar": "ભાવનગર", "Mahuva": "મહુવા", "Talaja": "તળાજા", "Palitana": "પાલીતાણા", "Sihor": "સિહોર",
    "Porbandar": "પોરબંદર", "Ranavav": "રાણાવાવ", "Kutiyana": "કુતિયાણા", "Jamnagar": "જામનગર", "Kalavad": "કાલાવડ", "Jodiya": "જોડિયા", "Jamjodhpur": "જામજોધપુર",
    "Bhanvad": "ભાણવડ", "Dwarka": "દ્વારકા", "Khambhalia": "ખંભાળિયા", "Morbi": "મોરબી", "Wankaner": "વાંકાનેર", "Tankara": "ટંકારા", "Halvad": "હળવદ",
    "Surendranagar": "સુરેન્દ્રનગર", "Dhrangadhra": "ધ્રાંગધ્રા", "Limbdi": "લીંબડી", "Chotila": "ચોટીલા", "Botad": "બોટાદ", "Gadhada": "ગઢડા", "Barwala": "બરવાળા",
    "Bhuj": "ભુજ", "Anjar": "અંજાર", "Mandvi": "માંડવી", "Nakhatrana": "નખત્રાણા", "Rapar": "રાપર",
    "Dholka": "ધોળકા", "Sanand": "સાણંદ", "Dhandhuka": "ધંધુકા", "Gandhinagar": "ગાંધીનગર", "Kalol": "કલોલ", "Dehgam": "દહેગામ", "Mansa": "માણસા",
    "Mahesana": "મહેસાણા", "Visnagar": "વિસનગર", "Kadi": "કડી", "Unjha": "ઊંઝા", "Patan": "પાટણ", "Chanasma": "ચાણસ્મા", "Sidhpur": "સિદ્ધપુર", "Harij": "હારિજ",
    "Palanpur": "પાલનપુર", "Deesa": "ડીસા", "Tharad": "થરાદ", "Danta": "દાંતા", "Himatnagar": "હિંમતનગર", "Idar": "ઇડર", "Prantij": "પ્રાંતિજ", "Talod": "તલોદ",
    "Modasa": "મોડાસા", "Bayad": "બાયડ", "Malpur": "માલપુર", "Nadiad": "નડિયાદ", "Kapadvanj": "કપડવંજ", "Matar": "માતર", "Anand": "આણંદ", "Borsad": "બોરસદ", "Petlad": "પેટલાદ",
    "Vadodara": "વડોદરા", "Dabhoi": "ડભોઈ", "Padra": "પાદરા", "Bharuch": "ભરૂચ", "Anklesvar": "અંકલેશ્વર", "Jambusar": "જંબુસર", "Surat": "સુરત", "Bardoli": "બારડોલી", "Olpad": "ઓલપાડ",
    "Navsari": "નવસારી", "Chikhli": "ચીખલી", "Gandevi": "ગણદેવી", "Valsad": "વલસાડ", "Dharampur": "ધરમપુર", "Umbergaon": "ઉમરગામ",
}

GU_SCRIPT = re.compile(r"[\u0A80-\u0AFF]")


def _norm_header(value: Any) -> str:
    return " ".join(str(value or "").replace("\ufeff", "").strip().lower().split())


def _cell(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if value.endswith(".0") and value[:-2].isdigit():
        value = value[:-2]
    return value


def _has_gujarati(value: str) -> bool:
    return bool(GU_SCRIPT.search(value or ""))


def _fold_gu(value: str) -> str:
    value = unicodedata.normalize("NFC", value.strip().lower())
    value = value.replace("ી", "િ").replace("ૂ", "ુ").replace("ઊ", "ઉ").replace("ઈ", "ઇ")
    value = value.replace("ં", "").replace("ઁ", "").replace("્", "")
    return "".join(ch for ch in value if ch.isalnum() or "\u0A80" <= ch <= "\u0AFF")


def _latin_words(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", value)


def gujarati_to_latin(value: str) -> str:
    """Simple reverse phonetic helper used only to pair reviewed legacy labels safely."""
    independent = {"અ":"a", "આ":"aa", "ઇ":"i", "ઈ":"i", "ઉ":"u", "ઊ":"u", "ઋ":"ri", "એ":"e", "ઐ":"ai", "ઓ":"o", "ઔ":"au", "ઍ":"e", "ઑ":"o"}
    signs = {"ા":"a", "િ":"i", "ી":"i", "ુ":"u", "ૂ":"u", "ૃ":"ri", "ે":"e", "ૈ":"ai", "ો":"o", "ૌ":"au", "ૅ":"e", "ૉ":"o"}
    consonants = {"ક":"k", "ખ":"kh", "ગ":"g", "ઘ":"gh", "ઙ":"ng", "ચ":"ch", "છ":"chh", "જ":"j", "ઝ":"jh", "ઞ":"ny", "ટ":"t", "ઠ":"th", "ડ":"d", "ઢ":"dh", "ણ":"n", "ત":"t", "થ":"th", "દ":"d", "ધ":"dh", "ન":"n", "પ":"p", "ફ":"ph", "બ":"b", "ભ":"bh", "મ":"m", "ય":"y", "ર":"r", "લ":"l", "વ":"v", "શ":"sh", "ષ":"sh", "સ":"s", "હ":"h", "ળ":"l"}
    def one_word(word: str) -> str:
        out: List[str] = []
        chars = list(unicodedata.normalize("NFC", word.lower()))
        i = 0
        last_inherent = False
        while i < len(chars):
            ch = chars[i]
            if ch == "્":
                i += 1; last_inherent = False; continue
            if i + 2 < len(chars) and chars[i + 1] == "્" and chars[i:i+3] == ["ક", "્", "ષ"]:
                out.append("ksh"); i += 3; last_inherent = True; continue
            if i + 2 < len(chars) and chars[i + 1] == "્" and chars[i:i+3] == ["જ", "્", "ઞ"]:
                out.append("gn"); i += 3; last_inherent = True; continue
            if ch in independent:
                out.append(independent[ch]); i += 1; last_inherent = False; continue
            if ch in consonants:
                token = consonants[ch]
                if i + 1 < len(chars) and chars[i + 1] in signs:
                    out.append(token + signs[chars[i + 1]]); i += 2; last_inherent = False
                elif i + 1 < len(chars) and chars[i + 1] == "્":
                    out.append(token); i += 2; last_inherent = False
                else:
                    out.append(token + "a"); i += 1; last_inherent = True
                continue
            if ch == "ં": out.append("n")
            elif ch == "ઃ": out.append("h")
            else: out.append(ch)
            i += 1; last_inherent = False
        if last_inherent and out and out[-1].endswith("a"):
            out[-1] = out[-1][:-1]
        return "".join(out)
    parts = re.split(r"([^\u0A80-\u0AFF]+)", unicodedata.normalize("NFC", value.lower()))
    return "".join(one_word(p) if p and GU_SCRIPT.search(p) else p for p in parts).strip()


def phonetic_gujarati(value: str) -> str:
    """Conservative English-orthography to Gujarati transliteration (not translation)."""
    words = re.findall(r"[A-Za-z]+|[0-9]+|[^A-Za-z0-9]+", value.strip())
    consonants = {
        "chh":"છ", "sh":"શ", "zh":"ઝ", "jh":"ઝ", "kh":"ખ", "gh":"ઘ", "th":"થ", "dh":"ધ",
        "ph":"ફ", "bh":"ભ", "ch":"ચ", "ng":"ંગ", "ny":"ન્ય", "ck":"ક", "qu":"ક્વ", "ks":"ક્સ",
        "k":"ક", "g":"ગ", "c":"ક", "j":"જ", "t":"ત", "d":"દ", "n":"ન", "p":"પ", "b":"બ", "m":"મ",
        "y":"ય", "r":"ર", "l":"લ", "v":"વ", "w":"વ", "s":"સ", "h":"હ", "f":"ફ", "z":"ઝ", "q":"ક", "x":"ક્સ",
    }
    matras = {"a":"ા", "aa":"ા", "e":"ે", "ee":"ી", "ei":"ે", "i":"િ", "ii":"ી", "o":"ો", "oo":"ૂ", "ou":"ુ", "u":"ુ", "uu":"ૂ", "ai":"ૈ", "au":"ૌ", "oi":"ોઇ"}
    independent = {"a":"અ", "aa":"આ", "e":"એ", "ee":"ઈ", "ei":"એ", "i":"ઇ", "ii":"ઈ", "o":"ઓ", "oo":"ઊ", "ou":"ઉ", "u":"ઉ", "uu":"ઊ", "ai":"ઐ", "au":"ઔ", "oi":"ઓઇ"}
    pairs = sorted(set(consonants) | set(matras), key=len, reverse=True)

    def word_convert(word: str) -> str:
        raw = word.lower()
        out: List[str] = []
        i = 0
        last_was_consonant = False
        syllable_consonant_index: int | None = None
        while i < len(raw):
            matched = next((p for p in pairs if raw.startswith(p, i)), None)
            if matched in matras and (not matched in consonants or (matched in ("ai", "au", "ee", "ei", "ii", "oo", "ou", "uu", "oi"))):
                if last_was_consonant and out:
                    # Final 'a' is an explicit 'આ' sound in many Gujarati place spellings;
                    # internal a remains the consonant's inherent vowel.
                    if matched in ("a", "aa"):
                        if i + len(matched) == len(raw): out.append("ા")
                    else:
                        out.append(matras[matched])
                    last_was_consonant = False
                else:
                    out.append(independent[matched])
                    last_was_consonant = False
                i += len(matched); continue
            if matched in consonants:
                c = consonants[matched]
                # c before e/i/y usually has an s sound in English names.
                if matched == "c" and i + 1 < len(raw) and raw[i+1] in "eiy": c = "સ"
                out.append(c)
                last_was_consonant = True
                i += len(matched); continue
            ch = raw[i]
            if ch in "aeiou":
                v = {"a":"ા", "e":"ે", "i":"િ", "o":"ો", "u":"ુ"}[ch]
                if last_was_consonant and out:
                    if ch == "a" and i + 1 < len(raw):
                        # Unstressed internal a is normally Gujarati's inherent vowel.
                        pass
                    elif ch == "a":
                        out.append("ા")
                    else:
                        out.append(v)
                    last_was_consonant = False
                else:
                    out.append({"a":"અ", "e":"એ", "i":"ઇ", "o":"ઓ", "u":"ઉ"}[ch])
                i += 1; continue
            if ch.isdigit(): out.append(ch)
            elif ch in "-_/": out.append("-")
            elif ch in "()'": out.append(ch)
            elif ch in ".,": out.append(ch)
            else: out.append(ch)
            last_was_consonant = False
            i += 1
        result = "".join(out)
        # Keep punctuation but make it usable as a compact display/search label.
        result = re.sub(r"\s+", " ", result).strip()
        return result or word

    converted = []
    for token in words:
        if re.fullmatch(r"[A-Za-z]+", token): converted.append(word_convert(token))
        elif token and not token.isspace() and token not in ("-", "/"):
            converted.append(token)
        else:
            converted.append(" " if token.isspace() or token in ("-", "/") else token)
    out = "".join(converted)
    out = re.sub(r"\s*[-/]\s*", "-", out)
    out = re.sub(r"\s+", " ", out).strip(" -")
    return out or value.strip()


def _expand_ssml_row(row: ET.Element) -> List[str]:
    values: List[str] = []
    expected_index = 1
    for cell in row.findall("ss:Cell", NS):
        raw_index = cell.attrib.get(f"{{{SS_NS}}}Index")
        cell_index = int(raw_index) if raw_index else expected_index
        while expected_index < cell_index:
            values.append(""); expected_index += 1
        data = cell.find("ss:Data", NS)
        values.append(_cell(data.text if data is not None else ""))
        expected_index = cell_index + 1
        merge_across = int(cell.attrib.get(f"{{{SS_NS}}}MergeAcross", "0") or 0)
        for _ in range(merge_across):
            values.append(""); expected_index += 1
    return values


def _read_spreadsheetml(path: Path) -> Tuple[List[Dict[str, Any]], str]:
    root = ET.parse(path).getroot()
    rows: List[List[str]] = []
    titles = []
    for row in root.findall(".//ss:Worksheet/ss:Table/ss:Row", NS):
        vals = _expand_ssml_row(row)
        rows.append(vals)
        if vals and vals[0]: titles.append(vals[0])
    title_text = " ".join(titles[:3])
    state_match = re.search(r"state\s*code\s*[:=]\s*(\d+)", title_text, re.I)
    if not state_match or state_match.group(1) != STATE_CODE:
        raise RuntimeError("SpreadsheetML export title does not verify Gujarat State Code 24")
    header_i = None
    for i, row in enumerate(rows[:20]):
        joined = " | ".join(row).lower()
        if "district code" in joined and ("village code" in joined or "district name" in joined):
            header_i = i; break
    if header_i is None:
        raise RuntimeError("Could not locate header row in official LGD SpreadsheetML export")
    first = rows[header_i]
    second = rows[header_i + 1] if header_i + 1 < len(rows) else []
    width = max(len(first), len(second))
    headers = []
    for i in range(width):
        base = _cell(first[i] if i < len(first) else "")
        sub = _cell(second[i] if i < len(second) else "")
        if sub.startswith("(") and "local" in sub.lower():
            h = f"{base} (In Local)"
        elif sub.startswith("(") and "english" in sub.lower():
            h = f"{base} (In English)"
        else:
            h = base
        headers.append(h)
    output: List[Dict[str, Any]] = []
    for row in rows[header_i + 2:]:
        if not any(row): continue
        if row and re.match(r"^[A-Za-z]{3}\s+\d{1,2},\s+\d{4}", row[0]): continue
        rec = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers)) if headers[i]}
        if any(_cell(v) for v in rec.values()):
            rec["State Code"] = STATE_CODE
            rec["State Name"] = "Gujarat"
            output.append(rec)
    return output, title_text


def _open_rows(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(8192); f.seek(0)
            try: dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error: dialect = csv.excel
            rows = list(csv.reader(f))
        header_i = None
        for i, row in enumerate(rows[:30]):
            norm = {_norm_header(v) for v in row}
            if any("district code" in v for v in norm) and any("village code" in v for v in norm):
                header_i = i; break
        if header_i is None: raise RuntimeError("Could not find LGD CSV header row")
        headers = [_cell(v) for v in rows[header_i]]
        return [dict(zip(headers, row + [""] * max(0, len(headers)-len(row)))) for row in rows[header_i+1:] if any(_cell(c) for c in row)]
    if suffix == ".xlsx":
        try: from openpyxl import load_workbook
        except ImportError as exc: raise RuntimeError("openpyxl is required to read .xlsx exports") from exc
        book = load_workbook(path, read_only=True, data_only=True)
        sheet = book.active
        raw = [list(row) for row in sheet.iter_rows(values_only=True)]
        book.close()
        rows = [[_cell(c) for c in row] for row in raw]
        header_i = None
        for i, row in enumerate(rows[:30]):
            norm = {_norm_header(v) for v in row}
            if any("district code" in v for v in norm) and any("village code" in v for v in norm):
                header_i = i; break
        if header_i is None: raise RuntimeError("Could not find LGD XLSX header row")
        headers = rows[header_i]
        return [dict(zip(headers, row + [""] * max(0, len(headers)-len(row)))) for row in rows[header_i+1:] if any(_cell(c) for c in row)]
    if suffix == ".xls":
        # The current LGD portal exports SpreadsheetML XML with .xls extension.
        rows, _ = _read_spreadsheetml(path)
        return rows
    raise RuntimeError("Input must be an official LGD .xls (SpreadsheetML), .csv or .xlsx export")


def _get(row: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    by_norm = {_norm_header(k): v for k, v in row.items()}
    for alias in ALIASES[key]:
        normalized = _norm_header(alias)
        if normalized in by_norm:
            value = _cell(by_norm[normalized])
            if value: return value
    if required:
        raise RuntimeError(f"required LGD column/value missing: {key}; acceptable headers={ALIASES[key]}")
    return ""


def _add_alias(aliases: List[str], value: str) -> List[str]:
    val = _cell(value)
    if val and all(_fold_gu(val) != _fold_gu(old) for old in aliases): aliases.append(val)
    return aliases


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _latin_words(a), _latin_words(b)).ratio()


def _load_overrides(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists(): return {"districts": {}, "talukas": {}, "villages": {}}
    try: result = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise RuntimeError(f"invalid reviewed location override file: {exc}") from exc
    if not isinstance(result, dict): raise RuntimeError("location override root must be a JSON object")
    return result


def build_master(
    rows: Sequence[Mapping[str, Any]], export_date: str, *, district_rows: Sequence[Mapping[str, Any]] = (),
    minimum_villages: int = 10_000, minimum_districts: int = 20, minimum_talukas: int = 100,
    input_sha256: str = "", district_sha256: str = "", overrides: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    overrides = overrides or {"districts": {}, "talukas": {}, "villages": {}}
    district_local_by_code: Dict[str, str] = {}
    for row in district_rows:
        dcode = _get(row, "district_code")
        den = _get(row, "district_en")
        dgu = _get(row, "district_gu")
        if dcode and den and _has_gujarati(dgu): district_local_by_code[dcode] = dgu

    parsed: List[Dict[str, str]] = []
    seen_village_code_rows: Dict[str, Dict[str, str]] = {}
    for row in rows:
        state_code = _get(row, "state_code", required=True)
        state_name = _get(row, "state_name_en")
        if state_code and state_code != STATE_CODE: continue
        if state_name and state_name.strip().lower() not in ("gujarat", "gujarāt"): continue
        item = {
            "district_code": _get(row, "district_code", required=True),
            "district_en": _get(row, "district_en", required=True),
            "district_gu": _get(row, "district_gu"),
            "taluka_code": _get(row, "taluka_code", required=True),
            "taluka_en": _get(row, "taluka_en", required=True),
            "taluka_gu": _get(row, "taluka_gu"),
            "village_code": _get(row, "village_code", required=True),
            "village_en": _get(row, "village_en", required=True),
            "village_gu": _get(row, "village_gu"),
            "village_status": _get(row, "village_status"),
        }
        if not all(item[k] for k in ("district_code", "taluka_code", "village_code")):
            raise RuntimeError("blank LGD code found in Gujarat row; refusing to produce master")
        prior = seen_village_code_rows.get(item["village_code"])
        if prior: raise RuntimeError(f"duplicate Village Code {item['village_code']} in input; first={prior}, second={item}")
        seen_village_code_rows[item["village_code"]] = item
        parsed.append(item)

    if len(parsed) < minimum_villages:
        raise RuntimeError(f"Only {len(parsed)} Gujarat village rows found; export appears partial/sample export (minimum {minimum_villages}). No JSON written.")

    districts: Dict[str, Dict[str, Any]] = {}
    taluka_owners: Dict[str, str] = {}
    for item in parsed:
        dc, tc = item["district_code"], item["taluka_code"]
        district_override = overrides.get("districts", {}).get(dc, {}) if isinstance(overrides.get("districts", {}), Mapping) else {}
        taluka_override = overrides.get("talukas", {}).get(f"{dc}:{tc}", {}) if isinstance(overrides.get("talukas", {}), Mapping) else {}
        village_override = overrides.get("villages", {}).get(f"{dc}:{tc}:{item['village_code']}", {}) if isinstance(overrides.get("villages", {}), Mapping) else {}
        local_district = district_local_by_code.get(dc) or item["district_gu"]
        official_district_gu = local_district if _has_gujarati(local_district) else ""
        district_gu = official_district_gu or str(district_override.get("name_gu", "")).strip() or DISTRICT_GU.get(item["district_en"], "") or phonetic_gujarati(item["district_en"])
        district_source = "official_local" if official_district_gu else ("reviewed_legacy_alias" if district_override.get("name_gu") else ("known_translation" if item["district_en"] in DISTRICT_GU else "phonetic_transliteration"))
        district_aliases = _add_alias([], item["district_en"])
        district_aliases = _add_alias(district_aliases, district_gu)
        district_aliases = _add_alias(district_aliases, local_district)
        for alias in district_override.get("aliases", []): district_aliases = _add_alias(district_aliases, str(alias))
        district = districts.setdefault(dc, {
            "code": dc, "name_en": item["district_en"], "name_gu": district_gu,
            "name_gu_source": district_source, "aliases": district_aliases, "talukas": {},
        })
        if district["name_en"] != item["district_en"]: raise RuntimeError(f"District Code {dc} maps to multiple English names")
        if dc not in districts or districts[dc]["name_gu"] == "": district["name_gu"] = district_gu

        if tc in taluka_owners and taluka_owners[tc] != dc: raise RuntimeError(f"Sub-District Code {tc} attached to multiple District Codes")
        taluka_owners[tc] = dc
        taluka_gu_official = item["taluka_gu"] if _has_gujarati(item["taluka_gu"]) else ""
        taluka_gu = taluka_gu_official or str(taluka_override.get("name_gu", "")).strip() or TALUKA_GU.get(item["taluka_en"], "") or phonetic_gujarati(item["taluka_en"])
        taluka_source = "official_local" if taluka_gu_official else ("reviewed_legacy_alias" if taluka_override.get("name_gu") else ("known_translation" if item["taluka_en"] in TALUKA_GU else "phonetic_transliteration"))
        taluka_aliases = _add_alias([], item["taluka_en"])
        taluka_aliases = _add_alias(taluka_aliases, taluka_gu)
        taluka_aliases = _add_alias(taluka_aliases, item["taluka_gu"])
        for alias in taluka_override.get("aliases", []): taluka_aliases = _add_alias(taluka_aliases, str(alias))
        if tc not in district["talukas"]:
            district["talukas"][tc] = {
                "code": tc, "district_code": dc, "name_en": item["taluka_en"], "name_gu": taluka_gu,
                "name_gu_source": taluka_source, "aliases": taluka_aliases, "villages": [],
            }
        elif district["talukas"][tc]["name_en"] != item["taluka_en"]:
            raise RuntimeError(f"Sub-District Code {tc} maps to multiple names")

        vill_gu_official = item["village_gu"] if _has_gujarati(item["village_gu"]) else ""
        vill_gu = vill_gu_official or str(village_override.get("name_gu", "")).strip() or phonetic_gujarati(item["village_en"])
        vill_source = "official_local" if vill_gu_official else ("reviewed_legacy_alias" if village_override.get("name_gu") else "phonetic_transliteration")
        village_aliases = _add_alias([], item["village_en"])
        village_aliases = _add_alias(village_aliases, vill_gu)
        village_aliases = _add_alias(village_aliases, item["village_gu"])
        for alias in village_override.get("aliases", []): village_aliases = _add_alias(village_aliases, str(alias))
        district["talukas"][tc]["villages"].append({
            "code": item["village_code"], "district_code": dc, "taluka_code": tc,
            "name_en": item["village_en"], "name_gu": vill_gu, "name_gu_source": vill_source,
            "aliases": village_aliases, "status": item["village_status"],
        })

    out_districts = []
    for district in sorted(districts.values(), key=lambda x: (x["name_en"].casefold(), x["code"])):
        district["talukas"] = [
            {**t, "villages": sorted(t["villages"], key=lambda v: (v["name_en"].casefold(), v["code"]))}
            for t in sorted(district["talukas"].values(), key=lambda x: (x["name_en"].casefold(), x["code"]))
        ]
        out_districts.append(district)
    data = {
        "schema_version": 1,
        "source": {
            "publisher": "Ministry of Panchayati Raj, Government of India",
            "directory": "Local Government Directory (LGD)", "source_url": LGD_URL,
            "entity_scope": "All village rows in official Gujarat state export; includes Inhabitant, Un-Inhabitant and Forest status",
            "state_code": STATE_CODE, "state_name_en": "GUJARAT", "export_date": export_date,
            "source_file_sha256": input_sha256, "district_export_sha256": district_sha256,
            "license_note": "Attribution: Local Government Directory / Ministry of Panchayati Raj. Verify future updates against the official LGD portal.",
            "gujarati_name_policy": "Use official local-script names when present; then reviewed existing Gujarati aliases matched only to an official LGD code chain; otherwise phonetic transliteration. English official name is retained in aliases.",
        },
        "districts": out_districts,
    }
    counts = validate_master_data(data, minimum_villages=minimum_villages, minimum_districts=minimum_districts, minimum_talukas=minimum_talukas)
    sources = {}
    for d in out_districts:
        sources[d["name_gu_source"]] = sources.get(d["name_gu_source"], 0) + 1
        for t in d["talukas"]:
            sources[t["name_gu_source"]] = sources.get(t["name_gu_source"], 0) + 1
            for v in t["villages"]: sources[v["name_gu_source"]] = sources.get(v["name_gu_source"], 0) + 1
    data["source"]["counts"] = {**counts, "source_name_counts": sources}
    data["source"]["sha256_canonical_json"] = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Full official Gujarat All Villages export (.xls/.csv/.xlsx)")
    parser.add_argument("--district-export", type=Path, help="Optional official Gujarat All Districts export with local-language district labels")
    parser.add_argument("--export-date", required=True, help="LGD export date, YYYY-MM-DD")
    parser.add_argument("--overrides", type=Path, help="Reviewed LGD-code keyed Gujarati alias overrides JSON")
    parser.add_argument("--minimum-villages", type=int, default=10_000, help="Completeness guard")
    parser.add_argument("--minimum-districts", type=int, default=20)
    parser.add_argument("--minimum-talukas", type=int, default=100)
    parser.add_argument("--check-only", action="store_true", help="Validate and print counts without writing JSON")
    args = parser.parse_args()
    try:
        date.fromisoformat(args.export_date)
        rows = _open_rows(args.input)
        district_rows = _open_rows(args.district_export) if args.district_export else []
        overrides = _load_overrides(args.overrides or (ROOT / "tools/gujarat_location_name_overrides.json"))
        source_sha = hashlib.sha256(args.input.read_bytes()).hexdigest()
        district_sha = hashlib.sha256(args.district_export.read_bytes()).hexdigest() if args.district_export else ""
        data = build_master(rows, args.export_date, district_rows=district_rows,
                            minimum_villages=args.minimum_villages, minimum_districts=args.minimum_districts,
                            minimum_talukas=args.minimum_talukas, input_sha256=source_sha,
                            district_sha256=district_sha, overrides=overrides)
        if args.check_only:
            print(json.dumps(data["source"]["counts"], ensure_ascii=False, indent=2))
            print("VALID: full Gujarat LGD master passed structural checks; no JSON files written")
            return 0
        targets = [ROOT / "app/src/main/assets/gujarat_locations.json", ROOT / "ai_backend/gujarat_locations.json"]
        serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(serialized, encoding="utf-8")
        print(json.dumps({"written": [str(p.relative_to(ROOT)) for p in targets], **data["source"]["counts"]}, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, ValueError, LocationMasterError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
