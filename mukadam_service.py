import os
import math
import time
import json
import base64
import hashlib
import sqlite3
import threading
import csv
import io
import urllib.request
import re
import unicodedata
from typing import List, Optional, Dict, Any, Tuple

try:
    from location_master import (
        LocationMasterError, get_location_master_and_index, load_location_master,
        location_labels_match_codes, resolve_location_names, resolve_location_selection, validate_location_codes,
        validate_location_filter_codes,
    )
except ImportError:  # package-import compatibility for tests/tools
    from .location_master import (
        LocationMasterError, get_location_master_and_index, load_location_master,
        location_labels_match_codes, resolve_location_names, resolve_location_selection, validate_location_codes,
        validate_location_filter_codes,
    )

# On Render, mount a Persistent Disk at /var/data and set MUKADAM_DB_PATH and
# MUKADAM_JSON_PATH to paths on that disk. Without it, files fall back to this project
# directory; that directory is ephemeral on Render Free unless a remote snapshot is configured.
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
# Prefer Render Persistent Disk; otherwise use the backend project folder instead of /tmp.
# On Render Free, the project folder is still ephemeral across redeploys/spin-downs;
# optional GitHub snapshot backup below provides cross-restart recovery when configured.
_DEFAULT_STORE_DIR = (
    "/var/data"
    if os.path.isdir("/var/data") and os.access("/var/data", os.W_OK)
    else _PROJECT_DIR
)
DB_PATH = os.environ.get("MUKADAM_DB_PATH", os.path.join(_DEFAULT_STORE_DIR, "mukadam_marketplace.db"))
BACKUP_JSON_PATH = os.environ.get(
    "MUKADAM_JSON_PATH",
    os.path.join(os.path.dirname(DB_PATH) or ".", "mukadam_backup_snapshot.json"),
)
_MUKADAM_LOCK = threading.RLock()
_JSON_SNAPSHOT_LOCK = threading.Lock()
_GITHUB_BACKUP_STATE_LOCK = threading.Lock()
_GITHUB_BACKUP_RUNNING = False
_GITHUB_BACKUP_PENDING = False
_MUKADAM_RAM_CACHE: List[Dict[str, Any]] = []
_CACHE_INITIALIZED = False


def _hash_pin(pin: str) -> str:
    clean_pin = str(pin).strip()
    return hashlib.sha256(f"smart_agri_mukadam_{clean_pin}".encode("utf-8")).hexdigest()


def _clean_mobile(mobile: str) -> str:
    # Convert native Gujarati/other Unicode decimal digits to ASCII so OTP hashes,
    # Twilio Verify, database keys, and Android payloads use one canonical number.
    ascii_digits = []
    for ch in str(mobile or ""):
        if not ch.isdigit():
            continue
        try:
            ascii_digits.append(str(unicodedata.digit(ch)))
        except (TypeError, ValueError):
            continue
    digits = "".join(ascii_digits)
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    return digits


def _norm_gu(text: Any) -> str:
    """Return a comparable Gujarati locality key despite common spelling variants.

    NFKC/NFC normalization, short/long vowel folding, optional anusvara removal,
    and removal of spacing/zero-width join controls make names such as ``કોદિયા``
    and ``કોદીયા`` compare equally without deleting meaningful consonants/viramas.
    """
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = unicodedata.normalize("NFC", value)
    # Dependent and independent short/long vowel variants.
    value = value.translate(str.maketrans({"ી": "િ", "ૂ": "ુ", "ઊ": "ઉ", "ઈ": "ઇ"}))
    # Anusvara/candrabindu and join controls may vary between data sources.
    value = value.replace("ં", "").replace("ઁ", "")
    value = re.sub(r"[\s\u200b-\u200f\uFEFF]+", "", value)
    # Ignore punctuation differences, but retain Gujarati consonants and viramas.
    value = "".join(ch for ch in value if not unicodedata.category(ch).startswith("P"))
    return value


# Approximate locality centroids used only when a user did not capture GPS.
# Village coordinates below are approximate; unknown villages inherit their taluka centroid.
LOCATION_COORDINATES: Dict[str, Tuple[float, float]] = {
    # Gir Somnath district and its six talukas
    "ગીર સોમનાથ": (20.9060, 70.3840),
    "ગીર ગઢડા": (20.9850, 70.9250),
    "ઉના": (20.8229, 71.0409),
    "વેરાવળ": (20.9159, 70.3629),
    "તાલાલા": (21.0505, 70.5325),
    "કોડીનાર": (20.7932, 70.7031),
    "સુત્રાપાડા": (20.8427, 70.4804),
    # Representative villages in Gir Gadhada / Una / Veraval / Talala / Kodinar / Sutrapada
    "કોદિયા": (21.0120, 70.8950), "કોદીયા": (21.0120, 70.8950),
    "ઇટવાયા": (21.0280, 70.9410), "ઇટવાયા ગામ": (21.0280, 70.9410),
    "જશાધાર": (20.9640, 70.9120), "ધોકડવા": (21.0550, 70.9820),
    "ફાટસર": (20.9800, 70.9300), "બેડીયા": (20.9900, 70.9100),
    "દ્રોણ": (20.9700, 70.9200), "બાબરિયા": (21.0000, 70.9000),
    "જામવાળા": (21.0200, 70.8800), "થોરડી": (20.9600, 70.9400),
    "ઉમેદપરા": (21.0000, 70.9300), "વડવીયાળા": (21.0100, 70.9200),
    "કરેણી": (20.9900, 70.9400), "સનાળા": (20.9800, 70.9000),
    "નવાગામ": (20.9900, 70.9200), "જુના ઉગલા": (20.9700, 70.9000),
    "નવા ઉગલા": (20.9750, 70.9050), "સોનારીયા": (20.9600, 70.9000),
    "વેળાકોટ": (20.9500, 70.9100), "ખીલાવડ": (20.9600, 70.9300),
    "નાના સમઢીયાળા": (20.9400, 70.9200), "મોટા સમઢીયાળા": (20.9450, 70.9250),
    "સમઢીયાળા": (20.9450, 70.9250), "સમઢિયાળા": (20.9450, 70.9250),
    "બોડીદર": (20.9500, 70.9400), "કાણકીયા": (20.9300, 70.9200),
    "હરમડીયા": (20.9400, 70.9000), "નીતલી": (20.9300, 70.9100),
    "રસુલપરા": (20.9500, 70.9000), "વોરા સિંધાજી": (20.9600, 70.9200),
    "જરગલી": (20.9700, 70.8900), "મહોબતપરા": (20.9850, 70.9150),
    "અંબાડા": (20.9900, 70.9200),
    "દેલવાડા": (20.8500, 71.0500), "નવાબંદર": (20.9000, 71.1800),
    "સનખડા": (20.8300, 71.0200), "ગાંગડા": (20.8400, 71.0300),
    "પાતાપુર": (20.8300, 71.0400), "ખાપટ": (20.8100, 71.0500),
    "સીમર": (20.8000, 71.0600), "સૈયદ રાજપરા": (20.8300, 71.0800),
    "કેસરિયા": (20.8200, 71.0200), "તડ": (20.8100, 71.0300),
    "પાણદર": (20.8200, 71.0600), "અંજાર": (20.8300, 71.0700),
    "કોબ": (20.8400, 71.0400), "ભીંગરાણ": (20.8000, 71.0700),
    "વાંસોજ": (20.8100, 71.0800), "નાથળ": (20.8200, 71.0900),
    "સમતેર": (20.8300, 71.0100), "રામેશ્વર": (20.8400, 71.0200),
    "કાંધી": (20.8500, 71.0300), "ભાચા": (20.8600, 71.0400),
    "વણકબારા": (20.8600, 71.1500), "મોઠા": (20.8200, 71.0500),
    "ગરાળ": (20.8100, 71.0400), "દેદાણ": (20.7900, 71.0400),
    "ખત્રીવાડા": (20.8000, 71.0200), "ચિખલી": (20.8100, 71.0100),
    "પ્રભાસ પાટણ (સોમનાથ)": (20.8900, 70.4000), "ભેરાળા": (20.9200, 70.3500),
    "કાજલી": (20.9300, 70.3400), "બાદલપરા": (20.9400, 70.3500),
    "ઉંબા": (20.9000, 70.3400), "સવની": (20.9200, 70.3300),
    "ઇશ્વરીયા": (20.9300, 70.3600), "મંડોર": (20.9400, 70.3700),
    "છાત્રોડા": (20.9200, 70.3800), "ડારી": (20.9000, 70.3700),
    "નાવદ્રા": (20.9100, 70.3500), "ભાલપરા": (20.9000, 70.3600),
    "સુપાસી": (20.8800, 70.3700), "આજોઠા": (20.9300, 70.3700),
    "મેઘપુર": (20.9400, 70.3900), "કોડીદ્રા": (20.9000, 70.3400),
    "મલોંઢા": (20.9300, 70.3800), "પાલડી": (20.9000, 70.3300),
    "સાસણ ગીર": (21.1700, 70.6000), "આંકોલવાડી": (21.0300, 70.5500),
    "ધાવા": (21.0400, 70.5200), "માધુપુર જાંબુડા": (21.0600, 70.5100),
    "ચિત્રોડ": (21.0500, 70.5000), "બોરવાવ": (21.0400, 70.5300),
    "હડમતીયા": (21.0600, 70.5400), "ગુંદરણ": (21.0500, 70.5200),
    "સુરવા": (21.0300, 70.5300), "પીપળવા": (21.0200, 70.5400),
    "ગાભા": (21.0400, 70.5500), "સેમરવાવ": (21.0600, 70.5200),
    "ઘુસીયા": (21.0300, 70.5100), "ભોજદે": (21.0400, 70.5000),
    "વીરપુર": (21.0300, 70.5200), "હિરાણા": (21.0200, 70.5200),
    "જેપુર": (21.0100, 70.5100), "આંબળાશ": (21.0600, 70.5000),
    "મૂળ દ્વારકા": (20.7500, 70.7000), "ઘાંટવડ": (20.7800, 70.7200),
    "ડોળાસા": (20.7700, 70.7400), "વેળણ": (20.7900, 70.6900),
    "સરખડી": (20.8000, 70.7100), "છારા": (20.7900, 70.6900),
    "અરણેજ": (20.7800, 70.7000), "દેવળી": (20.7900, 70.6800),
    "સિંધાજ": (20.8000, 70.7100), "પીપળી": (20.7900, 70.6900),
    "માઢવાડ": (20.7800, 70.7100), "કડવાસણ": (20.7900, 70.7000),
    "અડવી": (20.8000, 70.6900), "પાંચ પીપળવા": (20.7900, 70.7200),
    "મીતીયાજ": (20.7800, 70.6900), "વેળવા": (20.8000, 70.7000),
    "નાનાવાડા": (20.7800, 70.6800), "મોલી": (20.7900, 70.7100), "પીછવી": (20.7800, 70.7200),
    "પ્રાચી": (20.8500, 70.4700), "લોઢવા": (20.8300, 70.4700),
    "ધામળેજ": (20.8200, 70.4600), "હળદરવા": (20.8500, 70.4900),
    "વાવડી": (20.8400, 70.4900), "પ્રશ્નાવડા": (20.8400, 70.4600),
    "રાખેજ": (20.8300, 70.4800), "થરેલી": (20.8500, 70.4800),
    "લાટી": (20.8300, 70.4900), "બોસણ": (20.8400, 70.4700),
    "સોળાજ": (20.8500, 70.4600), "કદવાર": (20.8300, 70.4600), "ઘંટીયા": (20.8400, 70.4500),
    # Other major Gujarat districts / representative talukas
    "જૂનાગઢ": (21.5222, 70.4579), "કેશોદ": (21.3000, 70.2500), "માંગરોળ": (21.5200, 70.1200),
    "માળિયા હાટીના": (21.4100, 70.1700), "વિસાવદર": (21.3400, 70.7500), "મેંદરડા": (21.3200, 70.5700),
    "વંથલી": (21.4800, 70.3400), "ભેંસાણ": (21.5800, 70.5500), "માણાવદર": (21.5000, 70.0500),
    "અમરેલી": (21.6032, 71.2221), "રાજુલા": (21.0400, 71.4500), "જાફરાબાદ": (20.8600, 71.3600),
    "ખાંભા": (21.4800, 70.0500), "ધારી": (21.3300, 71.0200), "સાવરકુંડલા": (21.3300, 71.3000),
    "બગસરા": (21.4800, 70.9500), "બાબરા": (21.8500, 71.3000), "લાઠી": (21.7200, 71.3800),
    "રાજકોટ": (22.3039, 70.8022), "ગોંડલ": (21.9600, 70.8000), "જેતપુર": (21.7300, 70.6200),
    "ધોરાજી": (21.7400, 70.4500), "ઉપલેટા": (21.7400, 70.2800), "જસદણ": (22.0300, 71.2000),
    "ભાવનગર": (21.7645, 72.1519), "મહુવા": (21.0900, 71.7700), "તળાજા": (21.3500, 72.0300),
    "પાલીતાણા": (21.5300, 71.8300), "સિહોર": (21.7000, 71.9600), "પોરબંદર": (21.6417, 69.6293),
    "રાણાવાવ": (21.6900, 69.7400), "કુતિયાણા": (21.6300, 69.9800), "જામનગર": (22.4707, 70.0577),
    "ધ્રોલ": (22.5670, 70.4150), "લાલપુર": (22.1900, 69.9600), "જોડિયા": (22.7000, 70.2800),
    "કાલાવડ": (22.2100, 70.3800), "જામજોધપુર": (21.9600, 70.4500), "ખંભાળિયા": (22.2000, 69.6500),
    "ભાણવડ": (21.9300, 69.7800), "દ્વારકા": (22.2400, 68.9700), "મોરબી": (22.8173, 70.8370),
    "વાંકાનેર": (22.6100, 70.9500), "ટંકારા": (22.6600, 70.7500), "હળવદ": (23.0200, 71.1800),
    "સુરેન્દ્રનગર": (22.7300, 71.6400), "વઢવાણ": (22.7000, 71.7100), "ધ્રાંગધ્રા": (23.0000, 71.4700),
    "લીંબડી": (22.5600, 71.8000), "ચોટીલા": (22.4300, 71.1900), "બોટાદ": (22.1700, 71.6700),
    "ગઢડા": (21.9700, 71.5800), "બરવાળા": (22.0200, 71.1800), "કચ્છ": (23.7337, 69.8597),
    "ભુજ": (23.2410, 69.6669), "અંજાર": (23.1100, 70.0300), "માંડવી": (22.8300, 69.3500),
    "નખત્રાણા": (23.3700, 69.2700), "રાપર": (23.5700, 70.6400), "અમદાવાદ": (23.0225, 72.5714),
    "ધોળકા": (22.7500, 72.4400), "સાણંદ": (22.9900, 72.3800), "ધંધુકા": (22.3700, 71.9800),
    "ગાંધીનગર": (23.2156, 72.6369), "કલોલ": (23.2500, 72.5000), "દહેગામ": (23.1700, 72.8200),
    "માણસા": (23.4300, 72.3800), "મહેસાણા": (23.5880, 72.3693), "વિસનગર": (23.7000, 72.5500),
    "કડી": (23.3000, 72.3300), "ઊંઝા": (23.8000, 72.3900), "પાટણ": (23.8500, 72.1200),
    "ચાણસ્મા": (23.7200, 72.1200), "સિદ્ધપુર": (23.9200, 72.3700), "હારિજ": (23.6900, 71.9100),
    "બનાસકાંઠા": (24.1700, 72.4300), "પાલનપુર": (24.1700, 72.4300), "ડીસા": (24.2500, 72.1800),
    "થરાદ": (24.4000, 71.6300), "દાંતા": (24.1900, 72.7600), "સાબરકાંઠા": (23.6000, 73.0000),
    "હિંમતનગર": (23.6000, 72.9600), "ઇડર": (23.8400, 73.0000), "પ્રાંતિજ": (23.4300, 72.8600),
    "તલોદ": (23.3500, 72.9500), "અરવલ્લી": (23.3000, 73.2000), "મોડાસા": (23.4700, 73.3000),
    "બાયડ": (23.2500, 73.0500), "ખેડા": (22.7500, 72.6800), "નડિયાદ": (22.6900, 72.8600),
    "કપડવંજ": (23.0200, 73.0700), "આણંદ": (22.5600, 72.9500), "આણંદ જિલ્લો": (22.5600, 72.9500),
    "વડોદરા": (22.3072, 73.1812), "ભરૂચ": (21.7051, 72.9959), "સુરત": (21.1702, 72.8311),
    "નવસારી": (20.9467, 72.9520), "વલસાડ": (20.5992, 72.9342), "તાપી": (21.1200, 73.4000),
    "ડાંગ": (20.7500, 73.6800), "દાહોદ": (22.8300, 74.2500), "પંચમહાલ": (22.7500, 73.6000),
    "નર્મદા": (21.8700, 73.5000), "છોટા ઉદેપુર": (22.3100, 74.0100), "મહીસાગર": (23.1500, 73.5800),
}
# Additional talukas and localities from the Android suggestion list. These remain
# approximate fallbacks; exact GPS always takes precedence.
LOCATION_COORDINATES.update({
    "અમદાવાદ શહેર": (23.0225, 72.5714), "બાવળા": (22.8500, 72.3700),
    "ચાંગોદર": (22.8800, 72.4700), "તેલાવ": (22.8400, 72.4500),
    "બગોદરા": (22.7700, 72.3800), "ફેદરા": (22.4700, 72.0200),
    "છત્રાલ": (23.3000, 72.4700), "મોકાસણ": (23.2800, 72.5300),
    "રખિયાલ": (23.1800, 72.7800), "લવાડ": (23.1500, 72.9000),
    "ઇટાદરા": (23.4200, 72.4200), "લિંચ": (23.6000, 72.4000),
    "ગણેશપુરા": (23.7200, 72.5700), "લાડોલ": (23.7200, 72.5300),
    "ઉમતા": (23.7700, 72.4000), "વડનગર રોડ": (23.7800, 72.6000),
    "ચાણસ્મા રોડ": (23.7300, 72.1500), "સરીયદ": (23.7900, 72.1000),
    "હારિજ રોડ": (23.7000, 71.9500), "ખોરસમ": (23.7600, 72.1000),
    "કાકોશી": (23.9000, 72.3500), "દેથળી": (23.8800, 72.3200),
    "રાધનપુર રોડ": (23.6500, 71.8500), "સંકરી": (23.7000, 71.9000),
    "દાંતા રોડ": (24.1500, 72.4000), "ગઢ": (24.1600, 72.4500),
    "ભીલડી": (24.2000, 72.1900), "વાવ": (24.4500, 71.6000),
    "સુઈગામ": (24.0800, 71.2700), "અંબાજી": (24.3300, 72.8500),
    "કુંભારિયા": (24.2700, 72.7800), "ગાંભોઈ": (23.5500, 73.0000),
    "પોળો વિસ્તાર": (23.8700, 73.0000), "વડાલી": (23.9400, 73.0400),
    "સાબલવાડ": (23.8000, 73.0500), "તાજપુર": (23.4400, 72.8400),
    "સલાલ": (23.4500, 72.8900), "મહિયાલ": (23.3300, 72.9700),
    "લાલોડ": (23.3400, 72.9300), "સાકરિયા": (23.4600, 73.2700),
    "ડેમાઈ": (23.2800, 73.0700), "માલપુર રોડ": (23.2500, 73.2000),
    "સલાટવાડા": (23.2500, 73.2200), "મેઘરજ રોડ": (23.2500, 73.3000),
    "ઉમરેઠ રોડ": (22.6900, 72.7800), "પીજ": (22.7100, 72.8300),
    "સેવાલિયા": (22.9700, 73.3300), "માતર": (22.7000, 72.7500),
    "ત્રાજ": (22.6800, 72.7400), "વાસણા": (22.6500, 72.7800),
    "બોરસદ રોડ": (22.4100, 72.9000), "વિદ્યાનગર": (22.5500, 72.9300),
    "બોરસદ": (22.4100, 72.9000), "આસોદર": (22.3800, 72.9500),
    "વાસદ": (22.4500, 73.0700), "પેટલાદ": (22.4800, 72.8000),
    "ધર્મજ": (22.5500, 72.7200), "સોજીત્રા": (22.5400, 72.7200),
    "ડભોઈ": (22.1300, 73.4100), "વાઘોડિયા રોડ": (22.3100, 73.2200),
    "સાવલી રોડ": (22.5700, 73.2200), "કરજણ રોડ": (22.0500, 73.1200),
    "બોડેલી રોડ": (22.2700, 73.7300), "પાદરા": (22.2400, 73.0800),
    "માસર": (22.1800, 73.0200), "સાંખેડા રોડ": (22.1700, 73.5800),
    "અંકલેશ્વર": (21.6300, 73.0000), "ઝાડેશ્વર": (21.7200, 73.0000),
    "જંબુસર": (22.0500, 72.8000), "આમોદ": (22.0200, 72.8700),
    "દહેજ રોડ": (21.7100, 72.6000), "હાંસોટ રોડ": (21.5900, 72.8000),
    "વાલિયા રોડ": (21.5600, 73.0200), "કામરેજ": (21.2700, 72.9600),
    "પાલસાણા": (21.0900, 72.9800), "બારડોલી": (21.1200, 73.1100),
    "મઢી": (21.1200, 73.2000), "સારભોણ": (21.1000, 73.1500),
    "કીમ": (21.2700, 72.8800), "ઉમરપાડા": (21.4500, 73.4300),
    "ઓલપાડ": (21.3400, 72.7500), "મોર": (21.3300, 72.7600),
    "સુવાલી": (21.1000, 72.6300), "વિજલપોર": (20.9500, 73.0000),
    "જલાલપોર": (20.9200, 72.9300), "ચીખલી": (20.7600, 73.0600),
    "ખેરગામ રોડ": (20.7500, 73.0700), "રૂમલા": (20.7800, 73.0300),
    "ગણદેવી": (20.8100, 72.9900), "બિલીમોરા": (20.7700, 72.9700),
    "અમલસાડ": (20.8000, 72.9500), "પારડી": (20.5100, 72.9500),
    "વાપી": (20.3700, 72.9000), "ધરમપુર": (20.5400, 73.1700),
    "કપરાડા રોડ": (20.4000, 73.2500), "માલનપાડા": (20.5100, 73.1300),
    "ઉમરગામ": (20.1700, 72.7800), "સંજન": (20.1800, 72.7600),
    "ભિલાડ": (20.1200, 72.8700), "ખંભાળિયા રોડ": (22.2000, 69.6500),
    "મોટા પાંચદેવડા": (22.2700, 70.3000), "સમાણા": (21.9600, 70.5000),
    "સિડસર": (21.9800, 70.4900), "રામનગર": (22.2100, 69.6300),
    "ભાણવડ રોડ": (21.9200, 69.7700), "બરડા": (21.9000, 69.8000),
    "મોરાણા": (21.9500, 69.7600), "ઓખા": (22.4700, 69.0700),
    "ભાટિયા": (22.2200, 69.1800), "ટીંબડી": (22.8200, 70.8500),
    "માળિયા": (22.8200, 70.8500), "લુણસર": (22.5900, 71.0000),
    "જાલીડા": (22.6500, 70.9300), "નેસડા": (22.6200, 70.7200),
    "ધ્રાંગધ્રા રોડ": (23.0000, 71.1800), "જોરાવરનગર": (22.7300, 71.6500),
    "હળવદ રોડ": (22.9800, 71.1300), "કુંડા": (22.9300, 71.5200),
    "રાણાગઢ": (22.5000, 71.8200), "જાખણ": (22.5500, 71.7700),
    "થાનગઢ": (22.5700, 71.2000), "પાળીયાદ": (22.0500, 71.6500),
    "નાગલપર": (22.1800, 71.6600), "વીંછીયા": (22.0500, 71.6800),
    "ઢસા": (21.9500, 71.5500), "રાણપુર": (22.0000, 71.7400),
    "ખાંભડા": (22.0200, 71.1900), "માધાપર": (23.2500, 69.7000),
    "મિરજાપર": (23.2600, 69.7200), "ચંદિયા": (23.1000, 70.0800),
    "સિનુગ્રા": (23.0900, 70.0500), "મોટી રાયણ": (22.8500, 69.3800),
    "ગુંદિયાળી": (22.8200, 69.3600), "કોટડા જડોદર": (23.3600, 69.2500),
    "વિથોણ": (23.4000, 69.2000), "ભચાઉ રોડ": (23.5600, 70.6900),
    "આડેસર": (23.5500, 70.8500), "નરોડા": (23.0900, 72.6600), "વટવા": (22.9700, 72.6200),
    "કોઠ": (22.7200, 72.4200), "સુઈગામ": (24.0800, 71.2700),
})
_LOCATION_COORDINATES_NORM = {_norm_gu(name): coords for name, coords in LOCATION_COORDINATES.items()}


def _resolve_coordinates(
    latitude: Optional[float], longitude: Optional[float],
    district: str = "", taluka: str = "", village: str = "",
) -> Tuple[Optional[float], Optional[float]]:
    """Use real GPS when available, otherwise resolve village -> taluka -> district centroid."""
    try:
        lat = float(latitude or 0.0)
        lon = float(longitude or 0.0)
        if abs(lat) > 0.001 and abs(lon) > 0.001:
            return lat, lon
    except (TypeError, ValueError):
        pass
    for location in (village, taluka, district):
        coords = _LOCATION_COORDINATES_NORM.get(_norm_gu(location))
        if coords:
            return coords
    return None, None


def _haversine_km(
    lat1: Optional[float], lon1: Optional[float],
    lat2: Optional[float], lon2: Optional[float],
) -> Optional[float]:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    if abs(float(lat1)) < 0.001 or abs(float(lon1)) < 0.001 or abs(float(lat2)) < 0.001 or abs(float(lon2)) < 0.001:
        return None
    try:
        radius_km = 6371.0
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        d_phi = math.radians(float(lat2) - float(lat1))
        d_lambda = math.radians(float(lon2) - float(lon1))
        a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
        a = min(1.0, max(0.0, a))
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(radius_km * c, 1)
    except (TypeError, ValueError, OverflowError):
        return None


def _read_local_json_records() -> List[Dict[str, Any]]:
    """Read a local JSON snapshot; malformed/empty backups are safely ignored."""
    try:
        if not os.path.exists(BACKUP_JSON_PATH):
            return []
        with open(BACKUP_JSON_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data = list(data.values())
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("mobile")]
    except Exception:
        return []


def _restore_from_local_json_if_empty() -> None:
    """Merge any records missing from SQLite from its local JSON mirror."""
    records = _read_local_json_records()
    if not records:
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        # Merge missing entries even if SQLite already has some rows; INSERT OR IGNORE
        # leaves newer SQLite records intact while restoring records missing from a partial DB.
        for rec in records:
            mobile = _clean_mobile(rec.get("mobile", ""))
            if len(mobile) != 10:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO mukadams (
                    name, mobile, pin_hash, district, taluka, village,
                    district_code, taluka_code, village_code,
                    latitude, longitude, available_status, available_from_date,
                    total_labors, male_labors, female_labors,
                    wage_type, daily_wage_rate, contract_rate_details,
                    rickshaw_fare_type, rickshaw_fare_rate,
                    mukadami_type, mukadami_rate,
                    skills, notes, rating_sum, rating_count, contact_clicks, updated_at,
                    phone_verified_at, phone_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(rec.get("name", "")), mobile, str(rec.get("pin_hash", "")),
                    str(rec.get("district", "")), str(rec.get("taluka", "")), str(rec.get("village", "")),
                    str(rec.get("district_code", "")), str(rec.get("taluka_code", "")), str(rec.get("village_code", "")),
                    float(rec.get("latitude", 0.0) or 0.0), float(rec.get("longitude", 0.0) or 0.0),
                    str(rec.get("available_status", "available")), str(rec.get("available_from_date", "")),
                    int(rec.get("total_labors", 0) or 0), int(rec.get("male_labors", 0) or 0),
                    int(rec.get("female_labors", 0) or 0), str(rec.get("wage_type", "daily")),
                    float(rec.get("daily_wage_rate", 0.0) or 0.0), str(rec.get("contract_rate_details", "")),
                    str(rec.get("rickshaw_fare_type", "per_km")), float(rec.get("rickshaw_fare_rate", 0.0) or 0.0),
                    str(rec.get("mukadami_type", "per_labor")), float(rec.get("mukadami_rate", 0.0) or 0.0),
                    str(rec.get("skills", "")), str(rec.get("notes", "")),
                    float(rec.get("rating_sum", 5.0) or 5.0), max(1, int(rec.get("rating_count", 1) or 1)),
                    int(rec.get("contact_clicks", 0) or 0), float(rec.get("updated_at", time.time()) or time.time()),
                    max(0.0, float(rec.get("phone_verified_at", 0.0) or 0.0)) if int(rec.get("phone_verified", 0) or 0) == 1 else 0.0,
                    1 if int(rec.get("phone_verified", 0) or 0) == 1 and float(rec.get("phone_verified_at", 0.0) or 0.0) > 0 else 0,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _write_local_json_snapshot(snapshot: Optional[List[Dict[str, Any]]] = None) -> None:
    """Synchronously mirror the committed DB snapshot to an atomic local JSON file."""
    try:
        if snapshot is None:
            with _MUKADAM_LOCK:
                snapshot = [dict(item) for item in _MUKADAM_RAM_CACHE]
        # Serialize temp-file writes so concurrent API requests cannot race on `.tmp`.
        with _JSON_SNAPSHOT_LOCK:
            directory = os.path.dirname(BACKUP_JSON_PATH)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp_path = BACKUP_JSON_PATH + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, BACKUP_JSON_PATH)
    except Exception as exc:
        # A mirror failure must not roll back a successful SQLite commit.
        # Keep a diagnostic in service logs so a read-only/missing disk isn't silent.
        print(f"[Mukadam] local JSON snapshot write failed: {exc}")


def init_mukadam_db() -> None:
    global _CACHE_INITIALIZED
    with _MUKADAM_LOCK:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mukadams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    mobile TEXT UNIQUE NOT NULL,
                    pin_hash TEXT NOT NULL,
                    district TEXT DEFAULT '',
                    taluka TEXT DEFAULT '',
                    village TEXT DEFAULT '',
                    district_code TEXT DEFAULT '',
                    taluka_code TEXT DEFAULT '',
                    village_code TEXT DEFAULT '',
                    latitude REAL DEFAULT 0.0,
                    longitude REAL DEFAULT 0.0,
                    available_status TEXT DEFAULT 'available',
                    available_from_date TEXT DEFAULT '',
                    total_labors INTEGER DEFAULT 0,
                    male_labors INTEGER DEFAULT 0,
                    female_labors INTEGER DEFAULT 0,
                    wage_type TEXT DEFAULT 'daily',
                    daily_wage_rate REAL DEFAULT 0.0,
                    contract_rate_details TEXT DEFAULT '',
                    rickshaw_fare_type TEXT DEFAULT 'per_km',
                    rickshaw_fare_rate REAL DEFAULT 0.0,
                    mukadami_type TEXT DEFAULT 'per_labor',
                    mukadami_rate REAL DEFAULT 0.0,
                    skills TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    rating_sum REAL DEFAULT 5.0,
                    rating_count INTEGER DEFAULT 1,
                    contact_clicks INTEGER DEFAULT 0,
                    updated_at REAL DEFAULT 0.0,
                    phone_verified_at REAL NOT NULL DEFAULT 0.0,
                    phone_verified INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Add columns to existing databases. A pre-OTP row has no proof, so SQLite's
            # default 0 keeps it unverified until its owner completes a fresh OTP registration.
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(mukadams)").fetchall()}
            if "phone_verified_at" not in columns:
                conn.execute("ALTER TABLE mukadams ADD COLUMN phone_verified_at REAL NOT NULL DEFAULT 0.0")
            if "phone_verified" not in columns:
                conn.execute("ALTER TABLE mukadams ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0")
            for location_column in ("district_code", "taluka_code", "village_code"):
                if location_column not in columns:
                    conn.execute(f"ALTER TABLE mukadams ADD COLUMN {location_column} TEXT NOT NULL DEFAULT ''")
            conn.commit()
        finally:
            conn.close()
        _restore_from_local_json_if_empty()
        _restore_from_github_if_empty()
        _backfill_location_codes()
        _backfill_fallback_coordinates()
        _refresh_ram_cache()
        _CACHE_INITIALIZED = True


def _backfill_location_codes() -> None:
    """Attach LGD codes to legacy rows only when every text label resolves uniquely in its parent chain."""
    try:
        master, _ = load_location_master()
    except (FileNotFoundError, LocationMasterError) as exc:
        print(f"[Mukadam] LGD code backfill skipped: {exc}")
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT mobile, district, taluka, village, district_code, taluka_code, village_code FROM mukadams"
        ).fetchall()
        changed = False
        for mobile, district, taluka, village, dc, tc, vc in rows:
            if str(dc or "").strip() and str(tc or "").strip() and str(vc or "").strip():
                continue
            # Do not infer from an isolated village name; all three levels must uniquely resolve.
            resolved = resolve_location_selection(
                district=district or "", taluka=taluka or "", village=village or "",
                master=master, require_village=True,
            )
            if not resolved:
                continue
            conn.execute(
                "UPDATE mukadams SET district=?, taluka=?, village=?, district_code=?, taluka_code=?, village_code=? WHERE mobile=?",
                (resolved["district"], resolved["taluka"], resolved["village"],
                 resolved["district_code"], resolved["taluka_code"], resolved["village_code"], _clean_mobile(mobile)),
            )
            changed = True
        if changed:
            conn.commit()
    finally:
        conn.close()


def _backfill_fallback_coordinates() -> None:
    """Persist approximate locality coordinates for legacy rows that still contain 0,0."""
    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute(
                "SELECT mobile, latitude, longitude, district, taluka, village FROM mukadams"
            ).fetchall()
            changed = False
            for mobile, latitude, longitude, district, taluka, village in rows:
                try:
                    lat, lon = float(latitude or 0.0), float(longitude or 0.0)
                except (TypeError, ValueError):
                    lat, lon = 0.0, 0.0
                if abs(lat) > 0.001 and abs(lon) > 0.001:
                    continue  # Never overwrite a real GPS fix.
                fallback = _resolve_coordinates(lat, lon, str(district or ""), str(taluka or ""), str(village or ""))
                if fallback[0] is None or fallback[1] is None:
                    continue
                conn.execute(
                    "UPDATE mukadams SET latitude = ?, longitude = ? WHERE mobile = ?",
                    (fallback[0], fallback[1], _clean_mobile(mobile)),
                )
                changed = True
            if changed:
                conn.commit()
        finally:
            conn.close()


def _refresh_ram_cache() -> None:
    global _MUKADAM_RAM_CACHE
    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM mukadams ORDER BY updated_at DESC").fetchall()
            _MUKADAM_RAM_CACHE = [dict(row) for row in rows]
            snapshot = [dict(item) for item in _MUKADAM_RAM_CACHE]
        finally:
            conn.close()
        _write_local_json_snapshot(snapshot)


def _trigger_github_backup_async() -> None:
    """Queue one sequential GitHub snapshot upload after each successful data mutation.

    A burst of updates is coalesced, and only one worker uploads at a time. This avoids
    older concurrent uploads finishing after newer ones and replacing the latest backup.
    The local JSON mirror is still written synchronously by _refresh_ram_cache().
    """
    global _GITHUB_BACKUP_RUNNING, _GITHUB_BACKUP_PENDING
    github_token = os.environ.get("GITHUB_BACKUP_TOKEN", "").strip()
    github_repo = os.environ.get("GITHUB_BACKUP_REPO", "").strip()
    github_file_path = os.environ.get("GITHUB_BACKUP_PATH", "backups/mukadam_data.json").strip()
    if not github_token or not github_repo:
        return

    with _GITHUB_BACKUP_STATE_LOCK:
        _GITHUB_BACKUP_PENDING = True
        if _GITHUB_BACKUP_RUNNING:
            return
        _GITHUB_BACKUP_RUNNING = True

    def _backup_worker() -> None:
        global _GITHUB_BACKUP_RUNNING, _GITHUB_BACKUP_PENDING
        while True:
            with _GITHUB_BACKUP_STATE_LOCK:
                if not _GITHUB_BACKUP_PENDING:
                    _GITHUB_BACKUP_RUNNING = False
                    return
                _GITHUB_BACKUP_PENDING = False
            try:
                with _MUKADAM_LOCK:
                    snapshot = [dict(item) for item in _MUKADAM_RAM_CACHE]
                content_bytes = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
                b64_content = base64.b64encode(content_bytes).decode("utf-8")
                api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_file_path}"
                headers = {
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "SmartAgriMarket-MukadamBackup",
                }
                sha = None
                try:
                    req_get = urllib.request.Request(api_url, headers=headers, method="GET")
                    with urllib.request.urlopen(req_get, timeout=10) as resp:
                        existing = json.loads(resp.read().decode("utf-8"))
                    sha = existing.get("sha")
                except Exception:
                    sha = None
                payload = {
                    "message": f"Auto-backup Mukadam data ({len(snapshot)} records)",
                    "content": b64_content,
                }
                if sha:
                    payload["sha"] = sha
                req_put = urllib.request.Request(
                    api_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={**headers, "Content-Type": "application/json"},
                    method="PUT",
                )
                with urllib.request.urlopen(req_put, timeout=15):
                    pass
            except Exception as exc:
                print(f"[Mukadam] GitHub snapshot upload failed: {exc}")
                # If a newer mutation arrived during this attempt, retry once with that
                # latest snapshot; otherwise stop and wait for the next mutation.
                with _GITHUB_BACKUP_STATE_LOCK:
                    if _GITHUB_BACKUP_PENDING:
                        continue
                    _GITHUB_BACKUP_RUNNING = False
                return

    threading.Thread(target=_backup_worker, daemon=True, name="mukadam-backup").start()


def _restore_from_github_if_empty() -> None:
    """Merge missing records from the remote JSON snapshot during process startup."""
    github_token = os.environ.get("GITHUB_BACKUP_TOKEN", "").strip()
    github_repo = os.environ.get("GITHUB_BACKUP_REPO", "").strip()
    github_file_path = os.environ.get(
        "GITHUB_BACKUP_PATH", "backups/mukadam_data.json"
    ).strip()
    if not github_token or not github_repo:
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        # Restore missing records from the remote snapshot without overwriting newer
        # SQLite rows. This also recovers a partial local database, not only an empty one.
        api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_file_path}"
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "SmartAgriMarket-MukadamBackup",
        }
        req = urllib.request.Request(api_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_json = base64.b64decode(data["content"]).decode("utf-8")
        records = json.loads(raw_json)
        if isinstance(records, dict):
            records = list(records.values())
        if not isinstance(records, list):
            return
        for rec in records:
            if not isinstance(rec, dict):
                continue
            mobile = _clean_mobile(rec.get("mobile", ""))
            if len(mobile) != 10:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO mukadams (
                    name, mobile, pin_hash, district, taluka, village,
                    district_code, taluka_code, village_code,
                    latitude, longitude, available_status, available_from_date,
                    total_labors, male_labors, female_labors,
                    wage_type, daily_wage_rate, contract_rate_details,
                    rickshaw_fare_type, rickshaw_fare_rate,
                    mukadami_type, mukadami_rate,
                    skills, notes, rating_sum, rating_count, contact_clicks, updated_at,
                    phone_verified_at, phone_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get("name", ""),
                    mobile,
                    rec.get("pin_hash", ""),
                    rec.get("district", ""),
                    rec.get("taluka", ""),
                    rec.get("village", ""),
                    str(rec.get("district_code", "")),
                    str(rec.get("taluka_code", "")),
                    str(rec.get("village_code", "")),
                    float(rec.get("latitude", 0.0)),
                    float(rec.get("longitude", 0.0)),
                    rec.get("available_status", "available"),
                    rec.get("available_from_date", ""),
                    int(rec.get("total_labors", 0)),
                    int(rec.get("male_labors", 0)),
                    int(rec.get("female_labors", 0)),
                    rec.get("wage_type", "daily"),
                    float(rec.get("daily_wage_rate", 0.0)),
                    rec.get("contract_rate_details", ""),
                    rec.get("rickshaw_fare_type", "per_km"),
                    float(rec.get("rickshaw_fare_rate", 0.0)),
                    rec.get("mukadami_type", "per_labor"),
                    float(rec.get("mukadami_rate", 0.0)),
                    rec.get("skills", ""),
                    rec.get("notes", ""),
                    float(rec.get("rating_sum", 5.0)),
                    int(rec.get("rating_count", 1)),
                    int(rec.get("contact_clicks", 0)),
                    float(rec.get("updated_at", time.time())),
                    max(0.0, float(rec.get("phone_verified_at", 0.0) or 0.0)) if int(rec.get("phone_verified", 0) or 0) == 1 else 0.0,
                    1 if int(rec.get("phone_verified", 0) or 0) == 1 and float(rec.get("phone_verified_at", 0.0) or 0.0) > 0 else 0,
                ),
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def register_or_update_mukadam(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    name = str(payload.get("name", "")).strip()
    mobile = _clean_mobile(payload.get("mobile", ""))
    pin = str(payload.get("pin", "")).strip()
    if not name:
        return {"ok": False, "message_gu": "કૃપા કરીને મુકાદમનું નામ લખો."}
    if len(mobile) != 10:
        return {"ok": False, "message_gu": "કૃપા કરીને સાચો ૧૦ આંકડાનો મોબાઇલ નંબર લખો."}
    if len(pin) != 4 or not pin.isdigit():
        return {
            "ok": False,
            "message_gu": "સુરક્ષા માટે ૪ આંકડાનો સિક્રેટ પિન (દા.ત. 1234) રાખવો ફરજિયાત છે.",
        }

    district_input = str(payload.get("district", "")).strip()
    taluka_input = str(payload.get("taluka", "")).strip()
    village_input = str(payload.get("village", "")).strip()
    try:
        location_master, _ = load_location_master()
    except (FileNotFoundError, LocationMasterError) as exc:
        print(f"[Mukadam] Registration blocked because LGD master is unavailable: {exc}")
        return {"ok": False, "message_gu": "અધિકૃત LGD ગામ યાદી ઉપલબ્ધ નથી. હાલ નોંધણી કરી શકાતી નથી."}
    location = resolve_location_selection(
        district_code=payload.get("district_code", ""),
        taluka_code=payload.get("taluka_code", ""),
        village_code=payload.get("village_code", ""),
        district=district_input, taluka=taluka_input, village=village_input,
        master=location_master, require_village=True,
    )
    if not location:
        return {"ok": False, "message_gu": "અધિકૃત યાદીમાંથી સાચો જિલ્લો, તાલુકો અને ગામ પસંદ કરો; LGD કોડનો parent chain ખોટો અથવા અધૂરો છે."}
    # Check each provided label against the entity selected by its LGD code.
    # This also permits duplicate locality names to remain addressable by unique codes.
    if not location_labels_match_codes(
        location, district=district_input, taluka=taluka_input, village=village_input, master=location_master
    ):
        return {"ok": False, "message_gu": "નામ અને LGD કોડ વચ્ચે મેળ નથી. જિલ્લા, તાલુકો અને ગામ ફરી પસંદ કરો."}
    district_value = location["district"]
    taluka_value = location["taluka"]
    village_value = location["village"]
    district_code_value = location["district_code"]
    taluka_code_value = location["taluka_code"]
    village_code_value = location["village_code"]

    verification_token = str(payload.get("verification_token", "")).strip()
    try:
        from mukadam_otp_service import consume_registration_token
        phone_verified = consume_registration_token(verification_token, mobile)
    except Exception:
        phone_verified = False
    if not phone_verified:
        return {
            "ok": False,
            "message_gu": "મુકાદમ નોંધણી માટે આ જ મોબાઇલ નંબરનો OTP સફળતાપૂર્વક verify કરવો જરૂરી છે. કૃપા કરીને OTP ફરી ચકાસો.",
        }

    pin_hash = _hash_pin(pin)
    now = time.time()
    try:
        latitude_value = float(payload.get("latitude", 0.0) or 0.0)
        longitude_value = float(payload.get("longitude", 0.0) or 0.0)
    except (TypeError, ValueError):
        latitude_value, longitude_value = 0.0, 0.0
    resolved_lat, resolved_lon = _resolve_coordinates(
        latitude_value, longitude_value, district_value, taluka_value, village_value
    )
    if resolved_lat is not None and resolved_lon is not None:
        latitude_value, longitude_value = resolved_lat, resolved_lon
    male_labors = max(0, int(payload.get("male_labors", 0) or 0))
    female_labors = max(0, int(payload.get("female_labors", 0) or 0))
    total_labors = max(0, int(payload.get("total_labors", 0) or 0))
    if total_labors == 0 and (male_labors + female_labors) > 0:
        total_labors = male_labors + female_labors
    skills_raw = payload.get("skills", "")
    if isinstance(skills_raw, list):
        skills_str = ", ".join(str(skill).strip() for skill in skills_raw if str(skill).strip())
    else:
        skills_str = str(skills_raw).strip()

    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            existing = conn.execute(
                "SELECT * FROM mukadams WHERE mobile = ?", (mobile,)
            ).fetchone()
            if existing:
                if existing["pin_hash"] != pin_hash:
                    return {
                        "ok": False,
                        "message_gu": "આ મોબાઇલ નંબર પહેલેથી રજીસ્ટર છે. વિગત બદલવા માટે તમારો સાચો ૪ આંકડાનો પિન નાખો.",
                    }
                conn.execute(
                    """
                    UPDATE mukadams SET
                        name = ?, district = ?, taluka = ?, village = ?,
                        district_code = ?, taluka_code = ?, village_code = ?,
                        latitude = ?, longitude = ?,
                        available_status = ?, available_from_date = ?,
                        total_labors = ?, male_labors = ?, female_labors = ?,
                        wage_type = ?, daily_wage_rate = ?, contract_rate_details = ?,
                        rickshaw_fare_type = ?, rickshaw_fare_rate = ?,
                        mukadami_type = ?, mukadami_rate = ?,
                        skills = ?, notes = ?, updated_at = ?, phone_verified_at = ?, phone_verified = 1
                    WHERE mobile = ?
                    """,
                    (
                        name,
                        district_value,
                        taluka_value,
                        village_value,
                        district_code_value,
                        taluka_code_value,
                        village_code_value,
                        latitude_value,
                        longitude_value,
                        str(payload.get("available_status", "available")).strip(),
                        str(payload.get("available_from_date", "")).strip(),
                        total_labors,
                        male_labors,
                        female_labors,
                        str(payload.get("wage_type", "daily")).strip(),
                        float(payload.get("daily_wage_rate", 0.0) or 0.0),
                        str(payload.get("contract_rate_details", "")).strip(),
                        str(payload.get("rickshaw_fare_type", "per_km")).strip(),
                        float(payload.get("rickshaw_fare_rate", 0.0) or 0.0),
                        str(payload.get("mukadami_type", "per_labor")).strip(),
                        float(payload.get("mukadami_rate", 0.0) or 0.0),
                        skills_str,
                        str(payload.get("notes", "")).strip(),
                        now,
                        now,
                        mobile,
                    ),
                )
                action_msg = "તમારી મુકાદમ પ્રોફાઇલ અને મજૂરની વિગતો સફળતાપૂર્વક અપડેટ થઈ ગઈ છે!"
            else:
                conn.execute(
                    """
                    INSERT INTO mukadams (
                        name, mobile, pin_hash, district, taluka, village,
                        district_code, taluka_code, village_code,
                        latitude, longitude, available_status, available_from_date,
                        total_labors, male_labors, female_labors,
                        wage_type, daily_wage_rate, contract_rate_details,
                        rickshaw_fare_type, rickshaw_fare_rate,
                        mukadami_type, mukadami_rate,
                        skills, notes, rating_sum, rating_count, contact_clicks, updated_at,
                        phone_verified_at, phone_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 5.0, 1, 0, ?, ?, 1)
                    """,
                    (
                        name,
                        mobile,
                        pin_hash,
                        district_value,
                        taluka_value,
                        village_value,
                        district_code_value,
                        taluka_code_value,
                        village_code_value,
                        latitude_value,
                        longitude_value,
                        str(payload.get("available_status", "available")).strip(),
                        str(payload.get("available_from_date", "")).strip(),
                        total_labors,
                        male_labors,
                        female_labors,
                        str(payload.get("wage_type", "daily")).strip(),
                        float(payload.get("daily_wage_rate", 0.0) or 0.0),
                        str(payload.get("contract_rate_details", "")).strip(),
                        str(payload.get("rickshaw_fare_type", "per_km")).strip(),
                        float(payload.get("rickshaw_fare_rate", 0.0) or 0.0),
                        str(payload.get("mukadami_type", "per_labor")).strip(),
                        float(payload.get("mukadami_rate", 0.0) or 0.0),
                        skills_str,
                        str(payload.get("notes", "")).strip(),
                        now,
                        now,
                    ),
                )
                action_msg = "મુકાદમ તરીકે તમારી નોંધણી સફળતાપૂર્વક થઈ ગઈ છે! હવે નજીકના ખેડૂતો તમારો સંપર્ક કરી શકશે."
            conn.commit()
        finally:
            conn.close()

    _refresh_ram_cache()
    _trigger_github_backup_async()
    return {"ok": True, "message_gu": action_msg, "mobile": mobile}


def update_mukadam_quick_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    mobile = _clean_mobile(payload.get("mobile", ""))
    pin = str(payload.get("pin", "")).strip()
    new_status = str(payload.get("available_status", "unavailable")).strip()
    available_from_date = str(payload.get("available_from_date", "")).strip()
    total_labors = payload.get("total_labors", None)
    if len(mobile) != 10 or len(pin) != 4:
        return {
            "ok": False,
            "message_gu": "સાચો ૧૦ આંકડાનો મોબાઇલ નંબર અને ૪ આંકડાનો પિન નાખો.",
        }

    pin_hash = _hash_pin(pin)
    now = time.time()
    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            existing = conn.execute(
                "SELECT * FROM mukadams WHERE mobile = ?", (mobile,)
            ).fetchone()
            if not existing:
                return {
                    "ok": False,
                    "message_gu": "આ મોબાઇલ નંબરથી કોઈ મુકાદમ રજીસ્ટર નથી. પહેલા નોંધણી કરો.",
                }
            if existing["pin_hash"] != pin_hash:
                return {"ok": False, "message_gu": "તમારો ૪ આંકડાનો સિક્રેટ પિન ખોટો છે."}
            if int(existing["phone_verified"] or 0) != 1:
                return {"ok": False, "message_gu": "તમારી જૂની પ્રોફાઇલમાં મોબાઇલ OTP ચકાસણી બાકી છે. પહેલાં સંપૂર્ણ નોંધણીમાં OTP verify કરો."}
            if total_labors is not None:
                conn.execute(
                    """
                    UPDATE mukadams
                    SET available_status = ?, available_from_date = ?, total_labors = ?, updated_at = ?
                    WHERE mobile = ?
                    """,
                    (new_status, available_from_date, max(0, int(total_labors)), now, mobile),
                )
            else:
                conn.execute(
                    """
                    UPDATE mukadams
                    SET available_status = ?, available_from_date = ?, updated_at = ?
                    WHERE mobile = ?
                    """,
                    (new_status, available_from_date, now, mobile),
                )
            conn.commit()
        finally:
            conn.close()

    _refresh_ram_cache()
    _trigger_github_backup_async()
    status_gu = {
        "available": "🟢 હાલ મજૂર ઉપલબ્ધ છે",
        "future": f"🟡 {available_from_date} પછી મજૂર ઉપલબ્ધ થશે",
        "unavailable": "🔴 હાલ મજૂર ઉપલબ્ધ નથી",
    }.get(new_status, "અપડેટ થયું")
    with _MUKADAM_LOCK:
        public_profile = next(
            (dict(item) for item in _MUKADAM_RAM_CACHE if _clean_mobile(item.get("mobile", "")) == mobile),
            None,
        )
    if public_profile is not None:
        public_profile.pop("pin_hash", None)
        public_profile.pop("phone_verified", None)
        public_profile.pop("phone_verified_at", None)
    return {
        "ok": True,
        "message_gu": f"તમારું સ્ટેટસ બદલાઈ ગયું છે: {status_gu}",
        "available_status": new_status,
        "profile": public_profile,
    }


def _calculate_estimated_cost(
    item: Dict[str, Any], required_labors: int, distance_km: Optional[float]
) -> Dict[str, Any]:
    labors = max(
        1,
        required_labors if required_labors > 0 else int(item.get("total_labors", 1) or 1),
    )
    distance = distance_km if (distance_km is not None and distance_km > 0) else 10.0
    daily_rate = float(item.get("daily_wage_rate", 0.0) or 0.0)
    labor_cost = round(daily_rate * labors, 0)
    rickshaw_type = item.get("rickshaw_fare_type", "per_km")
    rickshaw_rate = float(item.get("rickshaw_fare_rate", 0.0) or 0.0)
    rickshaw_cost = (
        round(rickshaw_rate * distance, 0)
        if rickshaw_type == "per_km"
        else round(rickshaw_rate, 0)
    )
    mukadami_type = item.get("mukadami_type", "per_labor")
    mukadami_rate = float(item.get("mukadami_rate", 0.0) or 0.0)
    mukadami_cost = (
        round(mukadami_rate * labors, 0)
        if mukadami_type == "per_labor"
        else round(mukadami_rate, 0)
    )
    total_cost = labor_cost + rickshaw_cost + mukadami_cost
    return {
        "calculated_for_labors": labors,
        "assumed_distance_km": round(distance, 1),
        "labor_cost": int(labor_cost),
        "rickshaw_cost": int(rickshaw_cost),
        "mukadami_cost": int(mukadami_cost),
        "total_estimated_cost": int(total_cost),
    }


def search_nearby_mukadams(
    district: str = "",
    taluka: str = "",
    skill: str = "",
    village: str = "",
    farmer_lat: Optional[float] = None,
    farmer_lon: Optional[float] = None,
    max_km: float = 60.0,
    required_labors: int = 0,
    include_unavailable: bool = False,
    district_code: str = "",
    taluka_code: str = "",
    village_code: str = "",
) -> Dict[str, Any]:
    """Search using validated LGD codes; names are only display/legacy resolution inputs."""
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    try:
        location_master, location_index = get_location_master_and_index()
    except (FileNotFoundError, LocationMasterError) as exc:
        print(f"[MUKADAM_SEARCH_DIAG] location_master_unavailable=true error={type(exc).__name__}")
        return {"ok": False, "count": 0, "message_gu": "અધિકૃત LGD ગામ યાદી ઉપલબ્ધ નથી; સુરક્ષિત લોકેશન સર્ચ હાલ થઈ શકતું નથી.", "mukadams": []}

    selection = resolve_location_selection(
        district_code=district_code, taluka_code=taluka_code, village_code=village_code,
        district=district, taluka=taluka, village=village, master=location_master, require_village=False,
    )
    if selection is None:
        return {"ok": False, "count": 0, "message_gu": "પસંદ કરેલો જિલ્લો, તાલુકો અથવા ગામ સત્તાવાર LGD કોડ સાથે મેળ ખાતો નથી.", "mukadams": []}
    # Verify labels against the entity selected by each code. Some talukas contain
    # duplicate English/Gujarati village names; the LGD code remains the identity.
    if not location_labels_match_codes(
        selection, district=district, taluka=taluka, village=village, master=location_master
    ):
        return {"ok": False, "count": 0, "message_gu": "લોકેશનનું નામ અને LGD કોડ અલગ છે; ફરી પસંદ કરો.", "mukadams": []}

    district_code_filter = selection["district_code"]
    taluka_code_filter = selection["taluka_code"]
    village_code_filter = selection["village_code"]
    district = selection["district"]
    taluka = selection["taluka"]
    village = selection["village"]
    district_filter = district_code_filter
    taluka_filter = taluka_code_filter
    village_filter = village_code_filter
    skill_filter = _norm_gu(skill)
    ref_lat, ref_lon = _resolve_coordinates(farmer_lat, farmer_lon, district, taluka, village)
    now = time.time()

    with _MUKADAM_LOCK:
        cached_list = [dict(item) for item in _MUKADAM_RAM_CACHE]

    # Aggregate-only diagnostics help diagnose empty production searches without logging
    # names, phone numbers, PIN hashes, or precise coordinates.
    search_diag = {
        "cached": len(cached_list),
        "excluded_unverified": 0,
        "excluded_invalid_location": 0,
        "excluded_unavailable": 0,
        "excluded_district": 0,
        "excluded_skill": 0,
        "excluded_radius": 0,
        "unknown_distance": 0,
        "included_exact_locality": 0,
        "included_radius": 0,
        "included_fallback": 0,
    }
    nearest_distance_km: Optional[float] = None
    has_real_farmer_gps = (
        farmer_lat is not None and farmer_lon is not None
        and abs(float(farmer_lat or 0.0)) > 0.001 and abs(float(farmer_lon or 0.0)) > 0.001
    )
    # A selected village/taluka is a valid approximate search origin when the
    # phone cannot provide GPS. Previously radius matching required real GPS only,
    # so nearby profiles were discarded even when both village centroids were known.
    has_reference_coordinates = (
        ref_lat is not None and ref_lon is not None
        and abs(float(ref_lat or 0.0)) > 0.001 and abs(float(ref_lon or 0.0)) > 0.001
    )
    eligible: List[Dict[str, Any]] = []
    for raw in cached_list:
        item = dict(raw)
        item.pop("pin_hash", None)
        # Legacy/backup rows without historical OTP proof must not be presented as verified.
        if int(item.get("phone_verified", 0) or 0) != 1:
            search_diag["excluded_unverified"] += 1
            continue
        status = str(item.get("available_status", "available")).strip().lower()
        if not include_unavailable and status == "unavailable":
            search_diag["excluded_unavailable"] += 1
            continue
        if status not in ("available", "future", "unavailable"):
            status = "available"
            item["available_status"] = status

        item_dc = str(item.get("district_code", "") or "").strip()
        item_tc = str(item.get("taluka_code", "") or "").strip()
        item_vc = str(item.get("village_code", "") or "").strip()
        if any((item_dc, item_tc, item_vc)):
            indexed_district = location_index["districts"].get(item_dc)
            indexed_taluka = location_index["talukas_by_parent"].get((item_dc, item_tc))
            indexed_village = location_index["villages_by_parent"].get((item_dc, item_tc, item_vc))
            if indexed_district and indexed_taluka and indexed_village:
                item_location = {
                    "district_code": item_dc, "district": str(indexed_district.get("name_gu") or indexed_district.get("name_en") or ""),
                    "taluka_code": item_tc, "taluka": str(indexed_taluka.get("name_gu") or indexed_taluka.get("name_en") or ""),
                    "village_code": item_vc, "village": str(indexed_village.get("name_gu") or indexed_village.get("name_en") or ""),
                }
            else:
                item_location = None
        else:
            # Legacy verified rows can participate only if their entire name chain resolves uniquely.
            item_location = resolve_location_selection(
                district=item.get("district", ""), taluka=item.get("taluka", ""), village=item.get("village", ""),
                master=location_master, require_village=True,
            )
        if not item_location:
            search_diag["excluded_invalid_location"] += 1
            continue
        item["district_code"] = item_location["district_code"]
        item["taluka_code"] = item_location["taluka_code"]
        item["village_code"] = item_location["village_code"]
        item["district"] = item_location["district"]
        item["taluka"] = item_location["taluka"]
        item["village"] = item_location["village"]
        item_district = item_location["district_code"]
        item_taluka = item_location["taluka_code"]
        item_village = item_location["village_code"]
        same_district = bool(district_code_filter and item_district == district_code_filter)
        same_taluka = bool(taluka_code_filter and item_taluka == taluka_code_filter)
        same_village = bool(village_code_filter and item_village == village_code_filter)

        # District remains a hard boundary when the farmer selected it. Village and
        # taluka are ranking preferences, not hard exclusions, when real farmer GPS is
        # available: nearby villages must still be discoverable within max_km.
        if district_code_filter and item_district != district_code_filter:
            search_diag["excluded_district"] += 1
            continue
        if skill_filter and skill_filter not in (_norm_gu("બધા કામ"), _norm_gu("તમામ"), _norm_gu("બધા"), _norm_gu("all")):
            if skill_filter not in _norm_gu(item.get("skills", "")):
                search_diag["excluded_skill"] += 1
                continue

        item_lat, item_lon = _resolve_coordinates(
            item.get("latitude", 0.0), item.get("longitude", 0.0),
            str(item.get("district", "")), str(item.get("taluka", "")), str(item.get("village", "")),
        )
        # Return effective fallback coordinates for legacy 0,0 profiles as well.
        if item_lat is not None and item_lon is not None:
            item["latitude"], item["longitude"] = item_lat, item_lon
        distance_km = _haversine_km(ref_lat, ref_lon, item_lat, item_lon)
        item["distance_km"] = distance_km
        item["_same_district"] = same_district
        item["_same_taluka"] = same_taluka
        item["_same_village"] = same_village
        item["_distance_km_for_sort"] = distance_km
        item["_locality_rank"] = 0 if village_code_filter and same_village else (1 if taluka_code_filter and same_taluka else (2 if district_code_filter and same_district else 3))
        if distance_km is not None:
            nearest_distance_km = distance_km if nearest_distance_km is None else min(nearest_distance_km, distance_km)

        # An exact village match in the selected district must not disappear just
        # because a saved GPS point is stale or the phone has no GPS. If no village
        # is selected, an exact selected taluka is also a locality match.
        exact_locality = (
            (bool(village_code_filter) and same_village and (not district_code_filter or same_district))
            or (not village_code_filter and bool(taluka_code_filter) and same_taluka and (not district_code_filter or same_district))
            or (not village_code_filter and not taluka_code_filter and (not district_code_filter or same_district))
        )
        is_nearby = (
            has_reference_coordinates and max_km > 0 and distance_km is not None
            and distance_km <= max_km
        )
        # Radius matching works from real GPS or a known village/taluka/district
        # centroid. If no reference point can be resolved, do not fabricate distance.
        if exact_locality:
            search_diag["included_exact_locality"] += 1
            eligible.append(item)
        elif is_nearby:
            search_diag["included_radius"] += 1
            eligible.append(item)
        elif not village_code_filter and not taluka_code_filter and not has_real_farmer_gps:
            # Keep the legacy no-location browsing behavior when the user selected
            # neither a locality nor GPS search.
            search_diag["included_fallback"] += 1
            eligible.append(item)
        else:
            search_diag["excluded_radius"] += 1
            if distance_km is None:
                search_diag["unknown_distance"] += 1

    selected: List[Dict[str, Any]] = eligible
    if village_code_filter:
        fallback_level = "village"
    elif taluka_code_filter:
        fallback_level = "taluka"
    elif district_code_filter:
        fallback_level = "district"
    else:
        fallback_level = "nearby"

    final_rows = []
    for item in selected:
        # Avoid leaking internal sort flags into API JSON.
        distance_km = item.get("_distance_km_for_sort")
        rating_count = max(1, int(item.get("rating_count", 1) or 1))
        rating_sum = float(item.get("rating_sum", 5.0) or 5.0)
        item["avg_rating"] = round(rating_sum / rating_count, 1)
        item["is_stale"] = False  # legacy DTO field, retained for compatibility
        age_seconds = max(0.0, now - float(item.get("updated_at", now) or now))
        hours_ago = int(age_seconds // 3600)
        if hours_ago < 1:
            item["updated_text_gu"] = "હમણાં જ અપડેટ કર્યું"
        elif hours_ago < 24:
            item["updated_text_gu"] = f"{hours_ago} કલાક પહેલાં અપડેટ કર્યું"
        else:
            item["updated_text_gu"] = f"{hours_ago // 24} દિવસ પહેલાં અપડેટ કર્યું"
        item["cost_breakdown"] = _calculate_estimated_cost(item, required_labors, distance_km)
        status_rank = 0 if item.get("available_status") == "available" else (1 if item.get("available_status") == "future" else 2)
        locality_rank = int(item.get("_locality_rank", 3))
        if distance_km is None:
            distance_sort = 0.0 if fallback_level in ("village", "taluka", "district") else 9999.0
        else:
            distance_sort = float(distance_km)
        item.pop("phone_verified", None)
        item.pop("phone_verified_at", None)
        item.pop("_same_district", None)
        item.pop("_same_taluka", None)
        item.pop("_same_village", None)
        item.pop("_locality_rank", None)
        item.pop("_distance_km_for_sort", None)
        final_rows.append((status_rank, locality_rank, distance_sort, -float(item.get("updated_at", 0) or 0), item))

    final_rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    final_items = [row[4] for row in final_rows]
    # Emit one aggregate-only line for every search, not just empty lists. This also
    # helps diagnose a missing expected profile when other workers were returned.
    print("[MUKADAM_SEARCH_DIAG] " + json.dumps({
        "district_code": district_code_filter,
        "taluka_code": taluka_code_filter,
        "village_code": village_code_filter,
        "district": district or "",
        "taluka": taluka or "",
        "village": village or "",
        "max_km": max_km,
        "gps_supplied": has_real_farmer_gps,
        "reference_coordinates_available": has_reference_coordinates,
        "reference_source": "gps" if has_real_farmer_gps else ("selected_locality_centroid" if has_reference_coordinates and (village_filter or taluka_filter or district_filter) else ("fallback_centroid" if has_reference_coordinates else "none")),
        "nearest_distance_km": round(nearest_distance_km, 1) if nearest_distance_km is not None else None,
        "returned": len(final_items),
        **search_diag,
    }, ensure_ascii=False))
    return {
        "ok": True,
        "count": len(final_items),
        "message_gu": "" if final_items else "હાલમાં તમારા પસંદ કરેલા વિસ્તારમાં કોઈ મજૂર ઉપલબ્ધ નથી.",
        "mukadams": final_items,
    }


def record_rating_or_contact(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    mobile = _clean_mobile(payload.get("mobile", ""))
    action = str(payload.get("action", "contact")).strip()
    stars = payload.get("stars", None)
    if len(mobile) != 10:
        return {"ok": False, "message_gu": "અમાન્ય મોબાઇલ નંબર."}

    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        try:
            if action == "rate" and stars is not None:
                rating = max(1.0, min(5.0, float(stars)))
                conn.execute(
                    """
                    UPDATE mukadams
                    SET rating_sum = rating_sum + ?, rating_count = rating_count + 1
                    WHERE mobile = ? AND phone_verified = 1
                    """,
                    (rating, mobile),
                )
                message = "તમારું રેટિંગ નોંધાઈ ગયું છે. આભાર!"
            else:
                conn.execute(
                    "UPDATE mukadams SET contact_clicks = contact_clicks + 1 WHERE mobile = ? AND phone_verified = 1",
                    (mobile,),
                )
                message = "સંપર્ક નોંધાયો."
            conn.commit()
        finally:
            conn.close()

    _refresh_ram_cache()
    _trigger_github_backup_async()
    return {"ok": True, "message_gu": message}


def export_mukadams_csv() -> str:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "મુકાદમનું નામ",
            "મોબાઇલ નંબર",
            "જિલ્લો",
            "તાલુકો",
            "ગામ",
            "સ્ટેટસ",
            "ઉપલબ્ધ તારીખ",
            "કુલ મજૂર",
            "પુરુષ",
            "સ્ત્રી",
            "મજૂરી પ્રકાર",
            "રોજિંદો ભાવ (₹)",
            "ઉચ્ચક ભાવ વિગત",
            "રીક્ષા ભાડું પ્રકાર",
            "રીક્ષા ભાડું (₹)",
            "મુકાદમી પ્રકાર",
            "મુકાદમી (₹)",
            "કામની કુશળતા",
            "રેટિંગ",
            "ખેડૂત સંપર્ક સંખ્યા",
        ]
    )
    with _MUKADAM_LOCK:
        for item in _MUKADAM_RAM_CACHE:
            rating_count = max(1, int(item.get("rating_count", 1) or 1))
            average_rating = round(
                float(item.get("rating_sum", 5.0) or 5.0) / rating_count, 1
            )
            writer.writerow(
                [
                    item.get("id", ""),
                    item.get("name", ""),
                    item.get("mobile", ""),
                    item.get("district", ""),
                    item.get("taluka", ""),
                    item.get("village", ""),
                    item.get("available_status", ""),
                    item.get("available_from_date", ""),
                    item.get("total_labors", 0),
                    item.get("male_labors", 0),
                    item.get("female_labors", 0),
                    item.get("wage_type", ""),
                    item.get("daily_wage_rate", 0),
                    item.get("contract_rate_details", ""),
                    item.get("rickshaw_fare_type", ""),
                    item.get("rickshaw_fare_rate", 0),
                    item.get("mukadami_type", ""),
                    item.get("mukadami_rate", 0),
                    item.get("skills", ""),
                    average_rating,
                    item.get("contact_clicks", 0),
                ]
            )
    return output.getvalue()
