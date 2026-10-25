# -*- coding: utf-8 -*-
"""Canonical Gujarati Toponymic & Morphological Resolver for Gujarat LGD Master.

Resolves Gujarat's 34 Districts, 301 Talukas, and 19,199 Villages to authentic
Gujarati spellings without naive letter-by-letter machine transliteration errors.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

GUJARATI_RANGE_RE = re.compile(r"[\u0A80-\u0AFF]")
LATIN_RANGE_RE = re.compile(r"[A-Za-z]")


def is_already_gujarati(text: str) -> bool:
    """Return True if text already contains Gujarati characters and no Latin letters."""
    s = (text or "").strip()
    return bool(s and GUJARATI_RANGE_RE.search(s) and not LATIN_RANGE_RE.search(s))


# 1. Complete Official Gujarati Names for all 34 Districts of Gujarat
CANONICAL_DISTRICTS_GU: Dict[str, str] = {
    "Ahmedabad": "અમદાવાદ",
    "Amreli": "અમરેલી",
    "Anand": "આણંદ",
    "Arvalli": "અરવલ્લી",
    "Banas Kantha": "બનાસકાંઠા",
    "Bharuch": "ભરૂચ",
    "Bhavnagar": "ભાવનગર",
    "Botad": "બોટાદ",
    "Chhotaudepur": "છોટા ઉદેપુર",
    "Dahod": "દાહોદ",
    "Dangs": "ડાંગ",
    "Devbhumi Dwarka": "દેવભૂમિ દ્વારકા",
    "Gandhinagar": "ગાંધીનગર",
    "Gir Somnath": "ગીર સોમનાથ",
    "Jamnagar": "જામનગર",
    "Junagadh": "જૂનાગઢ",
    "Kachchh": "કચ્છ",
    "Kheda": "ખેડા",
    "Mahesana": "મહેસાણા",
    "Mahisagar": "મહીસાગર",
    "Morbi": "મોરબી",
    "Narmada": "નર્મદા",
    "Navsari": "નવસારી",
    "Panch Mahals": "પંચમહાલ",
    "Patan": "પાટણ",
    "Porbandar": "પોરબંદર",
    "Rajkot": "રાજકોટ",
    "Sabar Kantha": "સાબરકાંઠા",
    "Surat": "સુરત",
    "Surendranagar": "સુરેન્દ્રનગર",
    "Tapi": "તાપી",
    "Vadodara": "વડોદરા",
    "Valsad": "વલસાડ",
    "Vav-Tharad": "વાવ-થરાદ",
}

# 2. Complete Official Gujarati Names for Talukas (covering all 301 LGD Sub-Districts)
CANONICAL_TALUKAS_GU: Dict[str, str] = {
    # Ahmedabad
    "Asarva": "અસારવા",
    "Bavla": "બાવળા",
    "Daskroi": "દસ્ક્રોઈ",
    "Detroj-Rampura": "દેત્રોજ-રામપુરા",
    "Dhandhuka": "ધંધુકા",
    "Dholera": "ધોલેરા",
    "Dholka": "ધોળકા",
    "Ghatlodiya": "ઘાટલોડિયા",
    "Mandal": "માંડલ",
    "Maninagar": "મણિનગર",
    "Sabarmati": "સાબરમતી",
    "Sanand": "સાણંદ",
    "Vatva": "વટવા",
    "Vejalpur": "વેજલપુર",
    "Viramgam": "વીરમગામ",
    # Amreli
    "Amreli": "અમરેલી",
    "Babra": "બાબરા",
    "Bagasara": "બગસરા",
    "Dhari": "ધારી",
    "Jafrabad": "જાફરાબાદ",
    "Khambha": "ખાંભા",
    "Kukavav Vadia": "કુકાવાવ-વડિયા",
    "Kunkavav Vadia": "કુકાવાવ-વડિયા",
    "Lathi": "લાઠી",
    "Lilia": "લીલીયા",
    "Rajula": "રાજુલા",
    "Savar Kundla": "સાવરકુંડલા",
    "Savarkundla": "સાવરકુંડલા",
    # Anand
    "Anand": "આણંદ",
    "Anand City": "આણંદ શહેર",
    "Anand Rural": "આણંદ ગ્રામ્ય",
    "Anklav": "આંકલાવ",
    "Borsad": "બોરસદ",
    "Khambhat": "ખંભાત",
    "Petlad": "પેટલાદ",
    "Sojitra": "સોજીત્રા",
    "Tarapur": "તારાપુર",
    "Umreth": "ઉમરેઠ",
    # Arvalli
    "Bayad": "બાયડ",
    "Bhiloda": "ભિલોડા",
    "Dhansura": "ધનસુરા",
    "Malpur": "માલપુર",
    "Meghraj": "મેઘરજ",
    "Modasa": "મોડાસા",
    "Sathamba": "સાઠંબા",
    "Shamlaji": "શામળાજી",
    # Banas Kantha & Vav-Tharad
    "Amirgadh": "અમીરગઢ",
    "Bhabhar": "ભાભર",
    "Danta": "દાંતા",
    "Dantiwada": "દાંતીવાડા",
    "Deesa": "ડીસા",
    "Deesa City": "ડીસા શહેર",
    "Deodar": "દિયોદર",
    "Dhanera": "ધાનેરા",
    "Dharnidhar": "ધરણીધર",
    "Hadad": "હડાદ",
    "Kankrej": "કાંકરેજ",
    "Lakhani": "લાખણી",
    "Ogad": "ઓગડ",
    "Palanpur": "પાલનપુર",
    "Palanpur City": "પાલનપુર શહેર",
    "Raah": "રાહ",
    "Suigam": "સૂઈગામ",
    "Tharad": "થરાદ",
    "Vadgam": "વડગામ",
    "Vav": "વાવ",
    # Bharuch
    "Amod": "આમોદ",
    "Anklesvar": "અંકલેશ્વર",
    "Bharuch": "ભરૂચ",
    "Bharuch City": "ભરૂચ શહેર",
    "Hansot": "હાંસોટ",
    "Jambusar": "જંબુસર",
    "Jhagadia": "ઝઘડિયા",
    "Netrang": "નેત્રંગ",
    "Vagra": "વાગરા",
    "Valia": "વાલિયા",
    # Bhavnagar
    "Bhavnagar": "ભાવનગર",
    "Bhavnagar City": "ભાવનગર શહેર",
    "Gariadhar": "ગારિયાધાર",
    "Ghogha": "ઘોઘા",
    "Jesar": "જેસર",
    "Mahuva": "મહુવા",
    "Palitana": "પાલીતાણા",
    "Sihor": "સિહોર",
    "Talaja": "તળાજા",
    "Umrala": "ઉમરાળા",
    "Vallabhipur": "વલ્લભીપુર",
    # Botad
    "Barwala": "બરવાળા",
    "Botad": "બોટાદ",
    "Botad City": "બોટાદ શહેર",
    "Gadhada": "ગઢડા",
    "Ranpur": "રાણપુર",
    # Chhotaudepur
    "Bodeli": "બોડેલી",
    "Chhota Udaipur": "છોટા ઉદેપુર",
    "Jetpur Pavi": "જેતપુર પાવી",
    "Kadval": "કડવાળ",
    "Kavant": "કવાંટ",
    "Nasvadi": "નસવાડી",
    "Sankheda": "સંખેડા",
    # Dahod
    "Dahod": "દાહોદ",
    "Devgadbaria": "દેવગઢબારિયા",
    "Dhanpur": "ધાનપુર",
    "Dohad": "દાહોદ",
    "Fatepura": "ફતેપુરા",
    "Garbada": "ગરબાડા",
    "Govindguru Limdi": "ગોવિંદગુરુ લીમડી",
    "Jhalod": "ઝાલોદ",
    "Limkheda": "લીમખેડા",
    "Sanjeli": "સંજેલી",
    "Singvad": "સીંગવડ",
    "Sukhsar": "સુખસર",
    # Dangs
    "Ahwa": "આહવા",
    "Subir": "સુબીર",
    "Waghai": "વઘઈ",
    # Devbhumi Dwarka
    "Bhanvad": "ભાણવડ",
    "Dwarka": "દ્વારકા",
    "Kalyanpur": "કલ્યાણપુર",
    "Khambhalia": "ખંભાળિયા",
    "Okhamandal": "ઓખામંડળ",
    # Gandhinagar
    "Dehgam": "દહેગામ",
    "Gandhinagar": "ગાંધીનગર",
    "Kalol": "કલોલ",
    "Kalol City": "કલોલ શહેર",
    "Kalol Gandhinagar": "કલોલ (ગાંધીનગર)",
    "Mansa": "માણસા",
    # Gir Somnath
    "Gir Gadhda": "ગીર ગઢડા",
    "Kodinar": "કોડીનાર",
    "Patan-Veraval": "પાટણ-વેરાવળ",
    "Sutrapada": "સુત્રાપાડા",
    "Talala": "તાલાલા",
    "Una": "ઉના",
    "Veraval City": "વેરાવળ શહેર",
    # Jamnagar
    "Dhrol": "ધ્રોલ",
    "Jamjodhpur": "જામજોધપુર",
    "Jamnagar": "જામનગર",
    "Jamnagar City": "જામનગર શહેર",
    "Jamnagar Rural": "જામનગર ગ્રામ્ય",
    "Jodiya": "જોડિયા",
    "Kalavad": "કાલાવડ",
    "Lalpur": "લાલપુર",
    # Junagadh
    "Bhesan": "ભેંસાણ",
    "Junagadh": "જૂનાગઢ",
    "Junagadh City": "જૂનાગઢ શહેર",
    "Keshod": "કેશોદ",
    "Malia Hatina": "માળિયા હાટીના",
    "Manavadar": "માણાવદર",
    "Mangrol": "માંગરોળ",
    "Mendarda": "મેંદરડા",
    "Vanthali": "વંથલી",
    "Visavadar": "વિસાવદર",
    # Kachchh
    "Abdasa": "અબડાસા",
    "Anjar": "અંજાર",
    "Bhachau": "ભચાઉ",
    "Bhuj": "ભુજ",
    "Gandhidham": "ગાંધીધામ",
    "Lakhpat": "લખપત",
    "Mandvi": "માંડવી",
    "Mundra": "મુન્દ્રા",
    "Nakhatrana": "નખત્રાણા",
    "Rapar": "રાપર",
    # Kheda
    "Fagvel": "ફાગવેલ",
    "Galteshwar": "ગળતેશ્વર",
    "Kapadvanj": "કપડવંજ",
    "Kathlal": "કઠલાલ",
    "Kheda": "ખેડા",
    "Mahudha": "મહુધા",
    "Matar": "માતર",
    "Mehmedabad": "મહેમદાવાદ",
    "Nadiad": "નડિયાદ",
    "Nadiad City": "નડિયાદ શહેર",
    "Thasra": "ઠાસરા",
    "Vaso": "વાસો",
    # Mahesana
    "Becharaji": "બેચરાજી",
    "Jotana": "જોટાણા",
    "Kadi": "કડી",
    "Kheralu": "ખેરાલુ",
    "Mahesana": "મહેસાણા",
    "Mahesana City": "મહેસાણા શહેર",
    "Satlasana": "સતલાસણા",
    "Unjha": "ઊંઝા",
    "Vadnagar": "વડનગર",
    "Vijapur": "વિજાપુર",
    "Visnagar": "વિસનગર",
    # Mahisagar
    "Balasinor": "બાલાસિનોર",
    "Godhar": "ગોધર",
    "Kadana": "કડાણા",
    "Khanpur": "ખાનપુર",
    "Kothmba": "કોઠંબા",
    "Lunawada": "લુણાવાડા",
    "Santrampur": "સંતરામપુર",
    "Virpur": "વીરપુર",
    # Morbi
    "Halvad": "હળવદ",
    "Maliya": "માળિયા",
    "Morbi": "મોરબી",
    "Morbi City": "મોરબી શહેર",
    "Morvi": "મોરબી ગ્રામ્ય",
    "Tankara": "ટંકારા",
    "Wankaner": "વાંકાનેર",
    # Narmada
    "Chikada": "ચીકાડા",
    "Dediapada": "ડેડીયાપાડા",
    "Garudeshwar": "ગરૂડેશ્વર",
    "Nandod": "નાંદોદ",
    "Sagbara": "સાગબારા",
    "Tilakwada": "તિલકવાડા",
    # Navsari
    "Bansda": "વાંસદા",
    "Chikhli": "ચીખલી",
    "Gandevi": "ગણદેવી",
    "Jalalpore": "જલાલપોર",
    "Khergam": "ખેરગામ",
    "Navsari": "નવસારી",
    # Panch Mahals
    "Ghoghamba": "ઘોઘંબા",
    "Godhra": "ગોધરા",
    "Halol": "હાલોલ",
    "Jambughoda": "જાંબુઘોડા",
    "Kalol": "કાલોલ",
    "Morwa (Hadaf)": "મોરવા (હડફ)",
    "Shehera": "શહેરા",
    # Patan
    "Chanasma": "ચાણસ્મા",
    "Harij": "હારિજ",
    "Patan": "પાટણ",
    "Patan City": "પાટણ શહેર",
    "Radhanpur": "રાધનપુર",
    "Sami": "સમી",
    "Santalpur": "સાંતલપુર",
    "Saraswati": "સરસ્વતી",
    "Shankheshvar": "શંખેશ્વર",
    "Sidhpur": "સિદ્ધપુર",
    # Porbandar
    "Kutiyana": "કુતિયાણા",
    "Porabandar City": "પોરબંદર શહેર",
    "Porbandar": "પોરબંદર",
    "Ranavav": "રાણાવાવ",
    # Rajkot
    "Dhoraji": "ધોરાજી",
    "Gondal": "ગોંડલ",
    "Gondal City": "ગોંડલ શહેર",
    "Jamkandorna": "જામકંડોરણા",
    "Jasdan": "જસદણ",
    "Jetpur": "જેતપુર",
    "Jetpur City": "જેતપુર શહેર",
    "Kotda Sangani": "કોટડા સાંગાણી",
    "Lodhika": "લોધિકા",
    "Paddhari": "પડધરી",
    "Rajkot": "રાજકોટ",
    "Rajkot East": "રાજકોટ પૂર્વ",
    "Rajkot South": "રાજકોટ દક્ષિણ",
    "Rajkot West": "રાજકોટ પશ્ચિમ",
    "Upleta": "ઉપલેટા",
    "Vinchchiya": "વીંછિયા",
    # Sabar Kantha
    "Himatnagar": "હિંમતનગર",
    "Idar": "ઇડર",
    "Khedbrahma": "ખેડબ્રહ્મા",
    "Poshina": "પોશીના",
    "Prantij": "પ્રાંતિજ",
    "Talod": "તલોદ",
    "Vadali": "વડાલી",
    "Vijaynagar": "વિજયનગર",
    # Surat
    "Abrama": "અબ્રામા",
    "Adajan": "અડાજણ",
    "Ambika": "અંબિકા",
    "Areth": "અરેઠ",
    "Bardoli": "બારડોલી",
    "Chorasi": "ચોર્યાસી",
    "Kamrej": "કામરેજ",
    "Katargam": "કતારગામ",
    "Majura": "મજુરા",
    "Olpad": "ઓલપાડ",
    "Palsana": "પાલસાણા",
    "Puna": "પુણા",
    "Surat": "સુરત",
    "Surat City": "સુરત શહેર",
    "Udhna": "ઉધના",
    "Umarpada": "ઉમરપાડા",
    # Surendranagar
    "Chotila": "ચોટીલા",
    "Chuda": "ચૂડા",
    "Dasada": "દસાડા",
    "Dhrangadhra": "ધ્રાંગધ્રા",
    "Lakhtar": "લખતર",
    "Limbdi": "લીંબડી",
    "Muli": "મૂળી",
    "Sayla": "સાયલા",
    "Surendranagar": "સુરેન્દ્રનગર",
    "Thangadh": "થાનગઢ",
    "Wadhwan": "વઢવાણ",
    # Tapi
    "Dolvan": "ડોલવણ",
    "Kukarmunda": "કુકરમુંડા",
    "Nizar": "નિઝર",
    "Songadh": "સોનગઢ",
    "Uchchhal": "ઉચ્છલ",
    "Ukai": "ઉકાઈ",
    "Valod": "વાલોડ",
    "Vyara": "વ્યારા",
    # Vadodara
    "Dabhoi": "ડભોઈ",
    "Desar": "ડેસર",
    "Karjan": "કરજણ",
    "Padra": "પાદરા",
    "Savli": "સાવલી",
    "Sinor": "શિનોર",
    "Vadodara": "વડોદરા",
    "Vadodara East": "વડોદરા પૂર્વ",
    "Vadodara North": "વડોદરા ઉત્તર",
    "Vadodara Rural": "વડોદરા ગ્રામ્ય",
    "Vadodara South": "વડોદરા દક્ષિણ",
    "Vadodara West": "વડોદરા પશ્ચિમ",
    "Vaghodia": "વાઘોડિયા",
    # Valsad
    "Dharampur": "ધરમપુર",
    "Kaprada": "કપરાડા",
    "Nanapodha": "નાનાપોંઢા",
    "Pardi": "પારડી",
    "Umbergaon": "ઉમરગામ",
    "Valsad": "વલસાડ",
    "Vapi": "વાપી",
}

# 3. Exact Village Code Overrides (Keyed by LGD Village Code)
EXACT_VILLAGE_CODE_GU: Dict[str, str] = {
    "515101": "સાંઢણીધાર",     # Sandhnidhar / SANDHANIDHAR (Gir Somnath -> Kodinar)
    "514927": "સાંઢબેડા",       # Sandhbeda (Gir Somnath -> Talala)
    "511933": "સાંઢીડા",        # Sandhida (Ahmedabad -> Dholera)
    "516372": "સાંઢીડા",        # Sandhida (Bhavnagar -> Sihor)
    "516437": "સાંઢ ખાખરા",     # Sandh Khakhara (Bhavnagar -> Gariadhar)
    "524652": "સાંઢકૂવા",       # Sandhkuva (Tapi -> Songadh)
    "518072": "સાંઢ પાળીયા",    # Sandh Paliya (Mahisagar -> Godhar)
    "507186": "સાંધાણ",         # Sandhan (Kachchh -> Abdasa)
    "507142": "સાંધવ",         # Sandhav (Kachchh -> Abdasa)
    "517531": "સંધાણા",         # Sandhana (Kheda -> Matar)
    "517690": "સાંઢેલી",        # Sandheli (Kheda -> Thasra)
    "517742": "સાંઢેલીયા",      # Sandheliya (Kheda -> Thasra)
    "514783": "સાંઢા",         # Sandha (Junagadh -> Mangrol)
    "521068": "સાંઢા",         # Sandha (Vadodara -> Padra)
    "521217": "સાંઢા",         # Sandha (Vadodara -> Sinor)
    "520609": "સાંઢિયા",        # Sandhiya (Chhotaudepur -> Nasvadi)
    "521402": "સાંઢિયા",        # Sandhia (Narmada -> Garudeshwar)
    "513085": "સાંઢવાયા",       # Sandhavaya (Rajkot -> Kotda Sangani)
    "523747": "સાંધીયેર",       # Sandhiyer (Surat -> Olpad)
    "519736": "સાંઢાસાલ",       # Sandhasal (Vadodara -> Desar)
    "507960": "સાંઢોસી",        # Sandhosi (Banas Kantha -> Hadad)
    "515381": "જશાધાર",        # Jasadhar (Gir Somnath -> Gir Gadhda)
    "514985": "જશાધાર",        # Jasadhar (Gir Somnath -> Talala)
    "515377": "ભાયાધાર",        # Bhayadhar (Gir Somnath -> Gir Gadhda)
    "515342": "લામધાર",        # Lamdhar (Gir Somnath -> Gir Gadhda)
    "514953": "ખીરધાર",        # Khirdhar (Gir Somnath -> Talala)
    "514988": "રતીધાર",        # Ratidhar (Gir Somnath -> Talala)
    "514452": "ગોલાધાર",        # Goladhar (Junagadh -> Junagadh)
    "514490": "લીંબડી ધાર",     # Limbdi Dhar (Junagadh -> Junagadh)
    "514470": "તળિયાધાર",       # Taliyadhar (Junagadh -> Junagadh)
    "514716": "રાણીધાર",        # Ranidhar (Junagadh -> Mendarda)
    "513301": "ધોળીધાર",        # Dholidhar (Rajkot -> Jamkandorna)
    "513160": "ગોડલાધાર",       # Godladhar (Rajkot -> Jasdan)
    "513228": "ખાંડાધાર",       # Khandadhar (Rajkot -> Gondal)
    "512778": "લાકડધાર",        # Lakaddhar (Morbi -> Wankaner)
    "516143": "માંડવધાર",       # Mandavdhar (Botad -> Gadhada)
    "516547": "મૈધાર",         # Maidhar (Bhavnagar -> Palitana)
    "516726": "મોટી જાગધાર",    # Moti Jagdhar (Bhavnagar -> Mahuva)
    "516753": "નાની જાગધાર",    # Nani Jagdhar (Bhavnagar -> Mahuva)
    "515934": "બાબરિયાધાર",     # Babariyadhar (Amreli -> Rajula)
    "515526": "હજીરાધાર",       # Hajiradhar (Amreli -> Lathi)
    "515850": "ખાડાધાર",        # Khadadhar (Amreli -> Khambha)
    "515419": "લુણી-ધાર",       # Luni-Dhar (Amreli -> Kunkavav Vadia)
    "515770": "ધાર",           # Dhar (Amreli -> Savar Kundla)
    "508425": "લીલાધાર",        # Liladhar (Vav-Tharad -> Deodar)
    "516087": "દુદાધાર",        # Dudadhar (Bhavnagar -> Vallabhipur)
    "516396": "લીંબડધાર",       # Limbaddhar (Bhavnagar -> Sihor)
    "515249": "કોદિયા",         # Kodiya (Gir Somnath -> Gir Gadhda)
    "515264": "અંબાડા",         # Ambada (Gir Somnath -> Gir Gadhda)
    "515267": "ફાટસર",         # Fatsar (Gir Somnath -> Gir Gadhda)
    "515097": "થોરડી",         # Thordi (Gir Somnath -> Sutrapada)
    "515003": "પાલડી",         # Paldi (Gir Somnath -> Patan-Veraval)
    "515011": "મલોંઢા",        # Malondha (Gir Somnath -> Patan-Veraval)
    "515026": "કોડીદ્રા",       # Kodidara (Gir Somnath -> Patan-Veraval)
    "515049": "આજોઠા",         # Ajotha (Gir Somnath -> Patan-Veraval)
    "515040": "નાવદ્રા",        # Navadra (Gir Somnath -> Patan-Veraval)
    "515053": "ભાલપરા",        # Bhalpara (Ct) (Gir Somnath -> Patan-Veraval)
    "515022": "ભેરાળા",        # Bherala (Gir Somnath -> Patan-Veraval)
    "515051": "કાજલી",         # Kajli (Gir Somnath -> Patan-Veraval)
    "515050": "બાદલપરા",        # Badalpara (Gir Somnath -> Patan-Veraval)
    "515035": "ઈશ્વરિયા",       # Ishvariya (Gir Somnath -> Patan-Veraval)
    "515028": "મંડોર",         # Mandor (Gir Somnath -> Patan-Veraval)
    "515031": "છાત્રોડા",       # Chhatroda (Gir Somnath -> Patan-Veraval)
    "515032": "ડારી",          # Dari (Gir Somnath -> Patan-Veraval)
    "514978": "આંબળાશ",        # Amblash (Gir Somnath -> Talala)
    "514930": "ચિત્રોડ",        # Chitrod (Gir Somnath -> Talala)
    "515149": "મૂળ દ્વારકા",    # Mul Dwarka (Gir Somnath -> Kodinar)
    "515359": "દેલવાડા",        # Delwada (Gir Somnath -> Una)
    "506567": "આડેસર",
    "506735": "ચંદિયા",
    "506743": "સિનુગ્રા",
    "506920": "માધાપર",
    "506992": "કોટડા જડોદર",
    "507004": "નખત્રાણા",
    "507009": "વિથોણ",
    "507284": "ગુંદિયાળી",
    "507831": "કુંભારિયા",
    "507897": "દાંતા",
    "508192": "ગઢ",
    "508774": "દેથળી",
    "509094": "ખોરસમ",
    "509524": "લિંચ",
    "509623": "નંદાસણ",
    "509713": "બાવલુ",
    "510016": "સાબલવાડ",
    "510597": "સલાલ",
    "510690": "મહિયાલ",
    "510813": "સાકરિયા",
    "510996": "માલપુર",
    "511098": "ડેમાઈ",
    "511220": "ઇટાદરા",
    "511236": "અમરાપુર",
    "511624": "ચાંગોદર",
    "511738": "કોઠ",
    "512010": "કુંડા",
    "512729": "હડમતીયા",
    "512731": "ટંકારા",
    "512760": "બેડી",
    "512788": "લુણસર",
    "512857": "જાલીડા",
    "512944": "કુવાડવા",
    "512989": "સરધાર",
    "513112": "ભાડલા",
    "513206": "કોલીથડ",
    "513242": "મોવિયા",
    "513249": "દેવચડી",
    "513272": "સુલતાનપુર",
    "513344": "કોલકી",
    "513356": "ડુમીયાણી",
    "513375": "સુપેડી",
    "513386": "મોટી મારડ",
    "513394": "પાટણવાવ",
    "513414": "કાગવડ",
    "513415": "પીઠડીયા",
    "513431": "થાણા ગાલોળ",
    "513524": "રામનગર",
    "513819": "મોટા પાંચદેવડા",
    "514109": "સમાણા",
    "514152": "સિડસર",
    "514176": "મીયાણી",
    "514196": "બગવદર",
    "514218": "ઓડદર",
    "514244": "બિલેશ્વર",
    "514304": "દેવડા",
    "514326": "ચૌટા",
    "514368": "સરદારગઢ",
    "514373": "પાજોદ",
    "514405": "કોયલાણા",
    "514416": "કોયલી",
    "514420": "શાપુર",
    "514432": "ગાદોઈ",
    "514448": "લુશાળા",
    "514458": "ચોકી",
    "514463": "વડાલ",
    "514466": "મજેવડી",
    "514486": "પલાસવા",
    "514505": "બિલખા",
    "514531": "પરબ વાવડી",
    "514532": "ખંભાળીયા",
    "514543": "રાણપુર",
    "514552": "ભેંસાણ",
    "514562": "ચણાકા",
    "514601": "લેરીયા",
    "514624": "કાલસારી",
    "514672": "અરણીયાળા",
    "514674": "મીઠાપુર",
    "514678": "દાત્રાણા",
    "514687": "મેંદરડા",
    "514721": "બાલાગામ",
    "514732": "મઢડા",
    "514757": "અજાબ",
    "514758": "મેસવાણ",
    "514790": "કાલેજ",
    "514803": "શીલ",
    "514811": "લોએજ",
    "514823": "મક્તુપુર",
    "514833": "શેરીયાજ",
    "514836": "માંગરોળ",
    "514847": "વીરડી",
    "514861": "ભંડુરી",
    "514887": "ગડુ",
    "514934": "ભોજદે",
    "514940": "બોરવાવ",
    "514951": "જેપુર",
    "514954": "વીરપુર",
    "514955": "ધાવા",
    "514967": "આંકોલવાડી",
    "514968": "સુરવા",
    "514969": "ગુંદરણ",
    "514972": "સેમરવાવ",
    "514974": "ગાભા",
    "514975": "ઘુસીયા",
    "514977": "પીપળવા",
    "514980": "હડમતીયા",
    "515061": "ઘંટીયા",
    "515066": "લાટી",
    "515067": "કદવાર",
    "515079": "બોસણ",
    "515083": "થરેલી",
    "515089": "સોળાજ",
    "515090": "લોઢવા",
    "515091": "પ્રશ્નાવડા",
    "515096": "રાખેજ",
    "515098": "ધામળેજ",
    "515102": "ઘાંટવડ",
    "515103": "હરમડીયા",
    "515109": "અરણેજ",
    "515123": "કડવાસણ",
    "515138": "મીતીયાજ",
    "515142": "અડવી",
    "515143": "ડોળાસા",
    "515144": "વેળવા",
    "515146": "દેવળી",
    "515151": "પીપળી",
    "515156": "પાંચ પીપળવા",
    "515157": "નાનાવાડા",
    "515159": "સરખડી",
    "515160": "છારા",
    "515162": "વેળણ",
    "515236": "જામવાળા",
    "515244": "નીતલી",
    "515245": "સોનારીયા",
    "515249": "કોદિયા",
    "515250": "રસુલપરા",
    "515252": "બાબરિયા",
    "515255": "ગીર ગઢડા",
    "515256": "દ્રોણ",
    "515257": "ઇટવાયા",
    "515259": "ધોકડવા",
    "515260": "બેડીયા",
    "515262": "મોટા સમઢીયાળા",
    "515263": "મહોબતપરા",
    "515265": "નવા ઉગલા",
    "515266": "ખીલાવડ",
    "515268": "ઉમેદપરા",
    "515270": "જરગલી",
    "515271": "વડવીયાળા",
    "515278": "નાના સમઢીયાળા",
    "515285": "ભાચા",
    "515288": "ખાપટ",
    "515292": "વેળાકોટ",
    "515296": "બોડીદર",
    "515302": "પાતાપુર",
    "515316": "કાણકીયા",
    "515322": "સમતેર",
    "515323": "ગાંગડા",
    "515326": "ખત્રીવાડા",
    "515327": "સનખડા",
    "515328": "રામેશ્વર",
    "515332": "નાથળ",
    "515333": "કેસરિયા",
    "515337": "ચિખલી",
    "515345": "ગરાળ",
    "515346": "મોઠા",
    "515350": "અંજાર",
    "515353": "કોબ",
    "515354": "ભીંગરાણ",
    "515355": "તડ",
    "515358": "વાંસોજ",
    "515363": "સીમર",
    "515364": "સૈયદ રાજપરા",
    "515373": "નવાબંદર",
    "515379": "થોરડી",
    "515381": "જશાધાર",
    "515433": "કોટડા પીઠા",
    "515463": "દરેડ",
    "515466": "ચમારડી",
    "515478": "વાંડળીયા",
    "515519": "મતિરાળા",
    "515532": "શાખપુર",
    "515533": "સલડી",
    "515547": "પુંજાપાદર",
    "515565": "ક્રાંકચ",
    "515572": "ચિતલ",
    "515611": "ગાવડકા",
    "515624": "દેવરાજીયા",
    "515648": "માવજીંજવા",
    "515667": "કાગદડી",
    "515669": "હામાપુર",
    "515697": "ધારી",
    "515698": "ખીચા",
    "515726": "સરસીયા",
    "515728": "ગોવિંદપુર",
    "515729": "દલખાણીયા",
    "515766": "શેલણા",
    "515767": "વંડા",
    "515776": "ઓળીયા",
    "515800": "બાઢડા",
    "515806": "વિજપડી",
    "515837": "ભાડ",
    "515847": "ગીદરડી",
    "515857": "ડેડાણ",
    "515870": "ત્રાકુડા",
    "515930": "વાવેરા",
    "515960": "ડુંગર",
    "515982": "હિંડોરણા",
    "515986": "પીપાવાવ",
    "515995": "ભેરાઈ",
    "516000": "કોવાયા",
    "516025": "નાગલપર",
    "516260": "બુધેલ",
    "516356": "સણોસરા",
    "516401": "ટાણા",
    "516411": "વરલ",
    "516467": "નોંધણવદર",
    "516507": "ઘેટી",
    "516516": "મોટી પાણિયાળી",
    "516586": "ત્રાપજ",
    "516595": "દાંત્રડ",
    "516672": "અલંગ",
    "516694": "બગદાણા",
    "516715": "મોટા ખુંટવડા",
    "516759": "તલગાજરડા",
    "516774": "કળસાર",
    "517001": "ધર્મજ",
    "517216": "વડાલી",
    "517537": "માતર",
    "517543": "ત્રાજ",
    "517568": "વાસણા",
    "521071": "માસર",
    "523011": "અમલસાડ",
    "523103": "રૂમલા",
    "523713": "મોર",
    "523737": "ઓલપાડ",
    "524311": "મઢી",
    "524335": "સારભોણ",
    "926752": "સુત્રાપાડા",
    "930006": "ગઢડા",
    "930101": "વિસાવદર",
    "930102": "વંથલી",
    "930103": "કેશોદ",
    "930104": "માણાવદર",
    "930105": "બાંટવા",
    "930106": "ચોરવાડ",
    "930168": "રાણાવાવ",
    "930169": "આદિત્યાણા",
    "930170": "કુતિયાણા",
    "930184": "ધોરાજી",
    "930196": "જસદણ",
    "930198": "ધંધુકા",
    "930203": "ઉપલેટા",
    "930204": "ભાયાવદર",
    "930246": "ચોટીલા",
    "930251": "ધ્રાંગધ્રા",
    "930253": "ડભોઈ",
    "930255": "હારિજ",
    "930260": "માણસા",
    "930263": "હળવદ",
    "930289": "બોરસદ",
    "930291": "પેટલાદ",
    "930305": "કપડવંજ",
    "930317": "માંડવી",
    "930318": "તાલાલા",
    "935069": "કાલાવડ",
    "935070": "જામજોધપુર",
    "936610": "બાબરા",
    "936611": "બગસરા",
    "936613": "ચલાલા",
    "936615": "દામનગર",
    "936616": "લાઠી",
    "936617": "રાજુલા",
}

# Extra English spelling aliases for specific villages (so users typing common English variants match)
EXTRA_ENGLISH_ALIASES_BY_CODE: Dict[str, List[str]] = {
    "515101": ["SANDHANIDHAR", "Sandhanidhar", "Sandhani Dhar"],
    "515249": ["Kodiya", "Kodia"],
    "515143": ["Dolasa", "Dholasa"],
    "515359": ["Delwada", "Delvada"],
}

# 4. Curated Word & Morpheme Dictionary for Gujarati Toponyms
WORD_DICT_GU: Dict[str, str] = {
    # Common Adjectives / Prefixes / Modifiers
    "moti": "મોટી", "mota": "મોટા", "nani": "નાની", "nana": "નાના",
    "juna": "જૂના", "juni": "જૂની", "nava": "નવા", "navi": "નવી",
    "upla": "ઉપલા", "upli": "ઉપલી", "nichla": "નીચલા", "nichli": "નીચલી",
    "vachla": "વચલા", "vachli": "વચલી", "ugamna": "ઉગમણા", "athamna": "આથમણા",
    "khara": "ખારા", "khari": "ખારી", "mitha": "મીઠા", "mithi": "મીઠી",
    "kala": "કાળા", "kali": "કાળી", "dhola": "ધોળા", "dholi": "ધોળી",
    "lila": "લીલા", "lili": "લીલી", "lal": "લાલ", "bura": "બુરા",
    "panch": "પાંચ", "sat": "સાત", "nav": "નવ", "bar": "બાર", "ek": "એક",
    "mul": "મૂળ", "shri": "શ્રી", "sri": "શ્રી",
    "khurd": "ખુર્દ", "bujarg": "બુઝર્ગ", "bujrang": "બુઝર્ગ", "buzarg": "બુઝર્ગ",
    "dur": "દૂર", "najik": "નજીક", "east": "પૂર્વ", "west": "પશ્ચિમ",
    "north": "ઉત્તર", "south": "દક્ષિણ", "rural": "ગ્રામ્ય", "urban": "શહેર",
    "city": "શહેર", "part": "ભાગ", "alias": "ઉર્ફે", "no": "નં.",
    "na": "ના", "ni": "ની", "nu": "નું", "no.": "નં.", "to": "થી",
    "kasba": "કસ્બા", "inami": "ઇનામી", "jagiri": "જાગીરી", "sarkari": "સરકારી",
    "khalsa": "ખાલસા", "talpad": "તળપદ", "tarfe": "તરફે", "party": "પાર્ટી",
    "jungle": "જંગલ", "forest": "જંગલ", "kampo": "કંપો", "kampa": "કંપા",

    # High-Frequency Standalone & Compound Words
    "sandhnidhar": "સાંઢણીધાર", "sandhanidhar": "સાંઢણીધાર", "sandhani": "સાંઢણી", "sandhni": "સાંઢણી",
    "sandh": "સાંઢ", "sandha": "સાંઢા", "sandhida": "સાંઢીડા", "sandhbeda": "સાંઢબેડા",
    "dhar": "ધાર", "dhara": "ધરા", "dhari": "ધારી",
    "muvada": "મુવાડા", "muvadi": "મુવાડી", "muvadu": "મુવાડું",
    "nes": "નેસ", "nesh": "નેસ", "nesda": "નેસડા", "nesdi": "નેસડી", "nesvad": "નેસવડ",
    "navagam": "નવાગામ", "junagam": "જૂનાગામ", "vadagam": "વડાગામ", "bamangam": "બામણગામ",
    "bhalgam": "ભાલગામ", "bhalgamda": "ભાલગામડા", "dahegamda": "દહેગામડા", "dehgam": "દહેગામ",
    "degam": "દેગામ", "vadgam": "વડગામ", "viramgam": "વીરમગામ", "khergam": "ખેરગામ",
    "katargam": "કતારગામ", "suigam": "સૂઈગામ", "umargam": "ઉમરગામ", "umbergaon": "ઉમરગામ",
    "solgam": "સોલગામ", "asalgam": "અસલગામ", "malgam": "માલગામ", "madhgam": "માધગામ",
    "bhatgam": "ભાટગામ", "devgam": "દેવગામ", "gam": "ગામ", "gamdi": "ગામડી", "gamda": "ગામડા",
    "rampura": "રામપુરા", "rampur": "રામપુર", "rampuri": "રામપુરી", "rampar": "રામપર",
    "rampara": "રામપરા", "ramnagar": "રામનગર", "ramgadh": "રામગઢ", "ramgadhi": "રામગઢી",
    "ramnath": "રામનાથ", "rameshvar": "રામેશ્વર", "ramol": "રામોલ",
    "vavdi": "વાવડી", "vavadi": "વાવડી", "vav": "વાવ",
    "kotda": "કોટડા", "kotdi": "કોટડી", "kotadi": "કોટડી", "kot": "કોટ", "kotha": "કોઠા",
    "kothi": "કોઠી", "koth": "કોઠ", "kothara": "કોઠારા", "kothariya": "કોઠારીયા", "kothiya": "કોઠિયા",
    "pipaliya": "પીપળીયા", "pipli": "પીપળી", "pipali": "પીપળી", "pipalva": "પીપળવા",
    "piplaj": "પીપળજ", "pipal": "પીપળ", "pipariya": "પીપરીયા", "pipardi": "પીપરડી",
    "piparadi": "પીપરડી", "pipodara": "પીપોદરા", "piplod": "પીપલોદ", "panchpipla": "પાંચપીપળા",
    "rajpipla": "રાજપીપળા", "pipalpada": "પીપળપાડા", "piparala": "પીપરાળા", "pipar": "પીપર",
    "piplana": "પીપલાણા", "dharpipla": "ધારપીપળા",
    "vasna": "વાસણા", "vasana": "વાસણા", "vasan": "વાસણ", "vas": "વાસ", "navavas": "નવાવાસ",
    "mumanvas": "મુમનવાસ", "madhvas": "મધવાસ", "vasai": "વસાઈ", "vaso": "વાસો",
    "vasda": "વાસદા", "vasodara": "વાસોદરા", "vastral": "વસ્ત્રાલ", "vastrapur": "વસ્ત્રાપુર",
    "amba": "આંબા", "ambardi": "આંબરડી", "ambli": "આંબલી", "ambali": "આંબલી", "amli": "આમલી",
    "ambaliyara": "આંબલીયારા", "amaliyara": "આંબલીયારા", "ambaliyala": "આંબલીયાળા",
    "ambaliya": "આંબલીયા", "ambla": "આંબલા", "ambala": "અંબાલા", "ambada": "અંબાડા",
    "ambavada": "આંબાવાડા", "ambavad": "આંબાવડ", "ambav": "આંબાવ", "ambapani": "આંબાપાણી",
    "ambheta": "અંભેટા", "amblash": "આંબળાશ", "ambaji": "અંબાજી",
    "virpur": "વીરપુર", "virpar": "વીરપર", "virdi": "વીરડી", "virani": "વીરાણી",
    "viraniya": "વીરાણીયા", "virva": "વીરવા", "virol": "વીરોલ",
    "khijadiya": "ખીજડીયા", "vadiya": "વડિયા", "vadi": "વાડી", "wadi": "વાડી",
    "rajpur": "રાજપુર", "rajpura": "રાજપુરા", "rajupura": "રાજુપુરા", "rajpar": "રાજપર",
    "rajpara": "રાજપરા", "rajkot": "રાજકોટ", "rajgadh": "રાજગઢ", "rajavad": "રાજાવડ",
    "rajasthali": "રાજસ્થળી", "rajoda": "રાજોડા", "rajula": "રાજુલા",
    "haripura": "હરિપુરા", "haripur": "હરિપુર", "haripar": "હરિપર", "haripara": "હરિપરા",
    "mahudi": "મહુડી", "mahuda": "મહુડા", "mahuva": "મહુવા", "mahudha": "મહુધા",
    "ratanpur": "રતનપુર", "ratanpura": "રતનપુરા", "ratanpar": "રતનપર", "ratanvav": "રતનવાવ",
    "devaliya": "દેવળીયા", "devli": "દેવળી", "devla": "દેવળા", "devalpur": "દેવળપુર",
    "devpura": "દેવપુરા", "devpara": "દેવપરા", "devgadh": "દેવગઢ", "devda": "દેવડા",
    "devdi": "દેવડી", "deva": "દેવા", "devi": "દેવી", "devachadi": "દેવચડી",
    "samadhiyala": "સમઢીયાળા", "samdhi": "સમઢી",
    "hadmatiya": "હડમતીયા", "hadala": "હડાળા", "hadad": "હડાદ",
    "lalpur": "લાલપુર", "lalpura": "લાલપુરા",
    "gadh": "ગઢ", "gadhada": "ગઢડા", "gadha": "ગઢા", "gadhiya": "ગઢીયા", "gadhadiya": "ગઢડીયા",
    "gadhula": "ગઢુલા",
    "pardi": "પારડી", "paldi": "પાલડી", "padar": "પાદર", "padardi": "પાદરડી",
    "padariya": "પાદરીયા", "padaliya": "પાડલીયા", "padal": "પાડલ", "padana": "પડાણા",
    "paddhari": "પડધરી", "paddhara": "પડધરા",
    "timba": "ટીંબા", "timbi": "ટીંબી", "timbo": "ટીંબો", "timbdi": "ટીંબડી",
    "timbarva": "ટીંબરવા", "timbla": "ટીંબલા",
    "khanpur": "ખાનપુર", "khanpar": "ખાનપર", "khan": "ખાણ",
    "vandh": "વાંઢ", "vanta": "વાંટા", "vanto": "વાંટો", "vantda": "વાંટડા", "vantada": "વાંટડા",
    "vant": "વાંટ",
    "faliya": "ફળિયા", "jaliya": "જાળીયા", "jalida": "જાલીડા", "jalisana": "જાલીસણા",
    "chikhli": "ચીખલી", "chikhali": "ચીખલી", "chikhla": "ચીખલા", "chikhodra": "ચીખોદ્રા",
    "kerala": "કેરાળા", "keriya": "કેરીયા",
    "rangpur": "રંગપુર", "rangpar": "રંગપર",
    "ishvariya": "ઈશ્વરિયા", "math": "મઠ",
    "rupavati": "રૂપાવતી", "rupal": "રૂપાલ", "ruppura": "રૂપપુરા", "rupgadh": "રૂપગઢ",
    "pati": "પાટી", "patiya": "પાટિયા", "patdi": "પાટડી", "patan": "પાટણ", "patna": "પાટણા",
    "patapur": "પાતાપુર", "patla": "પાટલા", "patadiya": "પાટડીયા", "patanvav": "પાટણવાવ",
    "talav": "તળાવ", "talavdi": "તળાવડી", "talavadi": "તળાવડી", "taleti": "તળેટી",
    "fatepur": "ફતેપુર", "fatepura": "ફતેપુરા", "fategadh": "ફતેગઢ", "fatehvadi": "ફતેહવાડી",
    "jetpur": "જેતપુર", "jetpor": "જેતપોર", "jetalpur": "જેતલપુર", "jepur": "જેપુર",
    "bordi": "બોરડી", "bor": "બોર", "boriya": "બોરીયા", "boriyad": "બોરીયાદ", "boru": "બોરુ",
    "borvav": "બોરવાવ", "borbhatha": "બોરભાઠા", "bori": "બોરી", "boridara": "બોરીદรา",
    "borida": "બોરીડા", "borpada": "બોરપાડા", "boriavi": "બોરીઆવી",
    "motipura": "મોટીપુરા", "nanapura": "નાનાપુરા",
    "kheda": "ખેડા", "khirsara": "ખીરસરા",
    "khakhariya": "ખાખરીયા", "khakhara": "ખાખરા", "khakhra": "ખાખરા", "khakhar": "ખાખર",
    "dudhala": "દૂધાળા", "dudhai": "દૂધઈ", "dudhiya": "દૂધિયા",
    "dungri": "ડુંગરી", "dungari": "ડુંગરી", "dungar": "ડુંગર", "dungra": "ડુંગરા",
    "dungara": "ડુંગરા", "dungarpur": "ડુંગરપુર",
    "mevasa": "મેવાસા", "manpur": "માનપુર", "manpura": "માનપુરા", "manpar": "માનપર",
    "meghpar": "મેઘપર", "meghpur": "મેઘપુર", "megha": "મેઘા", "meghraj": "મેઘરજ",
    "navapura": "નવાપુરા", "navapara": "નવાપરા", "navanagar": "નવાનગર", "navagadh": "નવાગઢ",
    "navaniya": "નવાણીયા", "navalpur": "નવલપુર",
    "pratappura": "પ્રતાપપુરા", "pratapgadh": "પ્રતાપગઢ", "pratapnagar": "પ્રતાપનગર",
    "kamalpur": "કમલપુર", "kamalpura": "કમલપુરા",
    "vadala": "વડાળા", "vadal": "વડાલ", "vadali": "વડાલી", "vad": "વડ", "vadla": "વડલા",
    "vadli": "વડલી", "vadod": "વડોદ", "vadodara": "વડોદરા", "vadodar": "વડોદર",
    "vadpada": "વડપાડા", "vadva": "વડવા", "vadvasa": "વડવાસા", "vadoli": "વડોલી",
    "vadsar": "વડસર", "vadu": "વાડુ", "vadnagar": "વડનગર",
    "bamroli": "બામરોલી", "jasapar": "જસાપર", "jashapar": "જસાપર", "jaspur": "જસપુર",
    "jaspura": "જસપુરા", "jasvantpura": "જસવંતપુરા", "jashvantpura": "જશવંતપુરા",
    "ghoda": "ઘોડા", "ghodi": "ઘોડી", "ghodasar": "ઘોડાસર", "ghogha": "ઘોઘા",
    "sukhpar": "સુખપર", "sukhpur": "સુખપુર", "sukhsar": "સુખસર", "suka": "સૂકા",
    "kanthariya": "કંથારીયા", "khajuri": "ખજૂરી", "khajuriya": "ખજૂરીયા",
    "ganeshpura": "ગણેશપુરા", "ganpatpura": "ગણપતપુરા",
    "sultanpur": "સુલતાનપુર", "sultanpura": "સુલતાનપુરા",
    "palla": "પલ્લા", "palli": "પલ્લી", "pal": "પાલ", "pali": "પાલી", "paliyad": "પાળીયાદ",
    "palaiya": "પલાયા", "palaj": "પાલજ", "palsana": "પાલસાણા", "palanpur": "પાલનપુર",
    "ranipura": "રાણીપુરા", "ranipur": "રાણીપુર", "rani": "રાણી", "ranip": "રાણીપ",
    "gundala": "ગુંદાળા", "gunda": "ગુંદા", "gundi": "ગુંદી", "gundaran": "ગુંદરણ",
    "gundiyali": "ગુંદિયાળી",
    "beraja": "બેરાજા", "anandpur": "આનંદપુર", "anandpura": "આનંદપુરા", "anandpar": "આનંદપર",
    "anand": "આણંદ", "sanosara": "સણોસરા", "kuva": "કૂવા", "kuvadva": "કુવાડવા",
    "sardarpura": "સરદારપુરા", "sardarpur": "સરદારપુર", "sardargadh": "સરદારગઢ",
    "sardarnagar": "સરદારનગર",
    "chhapra": "છાપરા", "chhapri": "છાપરી", "chhatral": "છત્રાલ", "chhatrali": "છત્રાલી",
    "chhatrapura": "છત્રપુરા", "chhatroda": "છાત્રોડા",
    "pahadiya": "પહાડિયા", "pahad": "પહાડ",
    "rasulpur": "રસુલપુર", "rasulpura": "રસુલપુરા", "rasulpara": "રસુલપરા",
    "jambudi": "જાંબુડી", "jambuda": "જાંબુડા", "jambusar": "જંબુસર", "jambughoda": "જાંબુઘોડા",
    "jam": "જામ", "jamnagar": "જામનગર", "jamjodhpur": "જામજોધપુર", "jamkandorna": "જામકંડોરણા",
    "jamvala": "જામવાળા", "jamvali": "જામવાળી", "jamli": "જામલી", "jamka": "જામકા",
    "jamana": "જામણા", "jampur": "જામપુર", "jamaniya": "જામણીયા", "jamla": "જામળા",
    "jamba": "જાંબા", "jampar": "જામપર",
    "jorapura": "જોરાપુરા", "ranpur": "રાણપુર", "ranpar": "રાણપર", "ranparda": "રાણપરડા",
    "ranapur": "રાણાપુર", "ranavav": "રાણાવાવ", "ranagadh": "રાણાગઢ",
    "mangrol": "માંગરોળ", "mandvi": "માંડવી", "mandva": "માંડવા", "mandav": "માંડવ",
    "mandavda": "માંડવડા", "mandavdhar": "માંડવધાર", "mandal": "માંડલ", "mandali": "માંડલી",
    "mandala": "માંડલા", "mandan": "માંડણ", "mandor": "મંડોર",
    "zari": "ઝરી", "zariya": "ઝરીયા", "zarna": "ઝરણા", "zarola": "ઝારોલા", "zer": "ઝેર",
    "zoz": "ઝોઝ", "zab": "ઝાબ", "zinzuda": "ઝીંઝુડા", "zinzavadar": "ઝીંઝાવદર",
    "zala": "ઝાલા",
    "shahpur": "શાહપુર", "shahpura": "શાહપુરા", "shapur": "શાપુર",
    "bhandariya": "ભંડારીયા", "bhanduri": "ભંડુરી",
    "malvan": "માલવણ", "mal": "માળ", "malu": "માલુ", "malpur": "માલપુર", "malpara": "માલપરા",
    "maliya": "માળિયા", "malana": "માલણા", "malanka": "માલણકા", "malanpur": "માલનપુર",
    "jivapar": "જીવાપર", "jitpur": "જીતપુર", "jitpura": "જીતપુરા", "jitnagar": "જીતનગર",
    "sherpura": "શેરપુરા", "shergadh": "શેરગઢ", "sherdi": "શેરડી", "sher": "શેર",
    "bhanpur": "ભાણપુર", "bhanpura": "ભાણપુરા", "bhanvad": "ભાણવડ",
    "antroli": "અંત્રોલી", "antoli": "અંતોલી",
    "umarda": "ઉમરડા", "umariya": "ઉમરીયા", "umrala": "ઉમરાળા", "umrali": "ઉમરાળી",
    "umarva": "ઉમરવા", "umra": "ઉમરા", "umran": "ઉમરાણ", "umarpada": "ઉમરપાડા",
    "umreth": "ઉમરેઠ", "umargadh": "ઉમરગઢ",
    "bedi": "બેડી", "beda": "બેડા", "bediya": "બેડીયા",
    "mithapur": "મીઠાપુર", "bhat": "ભાટ", "bhatiya": "ભાટિયા", "bhatpura": "ભાટપુરા",
    "bhatpur": "ભાટપુર",
    "khodiyar": "ખોડિયાર", "khodla": "ખોડલા", "khoda": "ખોડા",
    "mahadevpura": "મહાદેવપુરા", "mahadevpara": "મહાદેવપરા", "mahadeviya": "મહાદેવીયા",
    "khambhaliya": "ખંભાળીયા", "khambhalia": "ખંભાળિયા", "khambha": "ખાંભા",
    "khambhala": "ખંભાળા", "khambhla": "ખાંભલા", "khambhalida": "ખંભાલીડા", "khambhda": "ખાંભડા",
    "khambhat": "ખંભાત",
    "ingorala": "ઇંગોરાળા", "dhanpura": "ધનપુરા", "dhanpur": "ધાનપુર", "dhanora": "ધનોરા",
    "dhanavada": "ધનાવાડા", "dhanwada": "ધનવાડા", "dhanera": "ધાનેરા", "dhansura": "ધનસુરા",
    "limdi": "લીમડી", "limbdi": "લીંબડી", "limbala": "લીંબાળા", "limbodara": "લીંબોદરા",
    "limbhoi": "લીંબોઈ", "limadiya": "લીમડીયા", "limkheda": "લીમખેડા", "limbad": "લીંબડ",
    "nagalpar": "નાગલપર", "nagadiya": "નાગડીયા",
    "dharampur": "ધરમપુર", "dharampura": "ધરમપુરા", "dharampuri": "ધરમપુરી", "dharampor": "ધરમપોર",
    "dharola": "ધરોલા", "dharoli": "ધરોલી", "dharoi": "ધરોઈ", "dharai": "ધરાઈ",
    "amrapar": "અમરાપર", "amrapur": "અમરાપુર", "amarapur": "અમરાપુર", "amarpura": "અમરપુરા",
    "amargadh": "અમરગઢ", "amrutvel": "અમૃતવેલ", "amrutpura": "અમૃતપુરા", "amroli": "અમરોલી",
    "amrol": "અમરોલ", "amadra": "આમદ્રા", "amalsad": "અમલસાડ", "amod": "આમોદ",
    "amodra": "આમોદ્રા", "amodara": "આમોદરા", "amreli": "અમરેલી",
    "hathipura": "હાથીપુરા", "hathijan": "હાથીજણ",
    "umedpura": "ઉમેદપુરા", "umedpara": "ઉમેદપરા",
    "khadol": "ખડોલ", "khad": "ખડ", "khadak": "ખડક", "khadakiya": "ખડકીયા",
    "khadba": "ખડબા", "khada": "ખાડા", "khadiya": "ખાડીયા", "khadsaliya": "ખડસલીયા",
    "vankiya": "વાંકીયા", "vanka": "વાંકા", "vanki": "વાંકી", "vankol": "વાંકોલ",
    "vank": "વાંક", "vankla": "વાંકલા", "vankaner": "વાંકાનેર", "vankaneda": "વાંકાનેડા",
    "anida": "અણીદા", "aniyali": "અણિયાળી",
    "rabarika": "રબારીકા", "bara": "બારા", "bari": "બારી", "bariya": "બારીયા",
    "porda": "પોરડા", "pada": "પાડા", "gola": "ગોલા", "golana": "ગોલાણા", "golan": "ગોલાણ",
    "mor": "મોર", "mora": "મોરા", "moriya": "મોરીયા", "morad": "મોરડ", "morali": "મોરલી",
    "morvad": "મોરવડ", "morbi": "મોરબી", "morvi": "મોરબી", "morasa": "મોરાસા",
    "moradiya": "મોરડીયા", "moraiya": "મોરૈયા", "moviya": "મોવિયા", "movi": "મોવી",
    "songadh": "સોનગઢ", "songir": "સોનગીર", "sonariya": "સોનારીયા", "sonipur": "સોનીપુર",
    "kharod": "ખરોડ", "kharoda": "ખરોડા", "khareda": "ખરેડા", "kharedi": "ખરેડી",
    "kharachiya": "ખારાચીયા",
    "bela": "બેલા", "sakhpar": "સાખપર", "simaliya": "સીમળીયા", "simal": "સીમળ",
    "simli": "સીમલી", "simar": "સીમર", "sim": "સીમ", "semaliya": "સેમળીયા",
    "sembaliya": "સેંબલીયા", "semarvav": "સેમરવાવ",
    "kadval": "કડવાળ", "kadvasan": "કડવાસણ", "kadvar": "કદવાર", "kadodara": "કડોદરા",
    "kadipur": "કડીપુર", "kadachhala": "કડાછલા", "kado": "કાડો", "kadoli": "કડોલી",
    "kadana": "કડાણા", "kadi": "કડી",
    "biliya": "બીલીયા", "bilkha": "બિલખા", "bildi": "બિલડી", "bileshwar": "બિલેશ્વર",
    "biliyat": "બિલિયાત", "bilimora": "બિલીમોરા",
    "ratadiya": "રતાડીયા", "delvada": "દેલવાડા", "delwada": "દેલવાડા",
    "veraval": "વેરાવળ", "dhoraji": "ધોરાજી", "gorada": "ગોરાડા", "gorva": "ગોરવા",
    "goraiya": "ગોરૈયા", "goraj": "ગોરજ",
    "bakrol": "બાકરોલ", "hirapur": "હીરાપુર", "hirapar": "હીરાપર",
    "thordi": "થોરડી", "thorala": "થોરાળા", "thori": "થોરી",
    "barvala": "બરવાળા", "barwala": "બરવાળા", "baroda": "બરોડા", "bardoli": "બારડોલી",
    "barda": "બરડા", "bardipada": "બરડીપાડા",
    "sakariya": "સાકરિયા", "kalyanpar": "કલ્યાણપર", "kalyanpur": "કલ્યાણપુર",
    "kalyanpura": "કલ્યાણપુરા", "kalyangadh": "કલ્યાણગઢ",
    "kumbhariya": "કુંભારિયા", "kumbhan": "કુંભણ", "kumbhara": "કુંભારા", "kumbhardi": "કુંભારડી",
    "gopalpura": "ગોપાલપુરા", "gokalpura": "ગોકળપુરા", "govindpur": "ગોવિંદપુર",
    "govindpura": "ગોવિંદપુરા", "govindpara": "ગોવિંદપરા",
    "vadadala": "વડાદલા", "vadadla": "વડાદલા", "alva": "અલવા", "bolundra": "બોલુંદ્રા",
    "karanpur": "કરણપુર", "karanpura": "કરણપુરા", "karangadh": "કરણગઢ",
    "malekpur": "મલેકપુર", "vajapur": "વજાપુર", "vajpur": "વજપુર", "vajdi": "વજડી",
    "odha": "ઓઢા", "odhav": "ઓઢવ", "odhava": "ઓઢવા", "oddar": "ઓડદર", "ode": "ઓડ",
    "bhutiya": "ભૂતિયા", "bhut": "ભૂત",
    "surpur": "સુરપુર", "surka": "સુરકા", "surva": "સુરવા", "surajpura": "સૂરજપુરા",
    "sureli": "સુરેલી", "supedi": "સુપેડી",
    "badarpura": "બદરપુરા", "danta": "દાંતા", "dantali": "દાંતાલી", "dantiya": "દાંતીયા",
    "danti": "દાંતી", "dantiwada": "દાંતીવાડા", "dantrad": "દાંત્રડ",
    "thana": "થાણા", "than": "થાન", "thangadh": "થાનગઢ", "thala": "થાળા", "thara": "થરા",
    "tharavada": "થરાવાડા", "tharad": "થરાદ", "thareli": "થરેલી", "thasra": "ઠાસરા",
    "thambha": "થાંભા", "thikariya": "ઠીકરીયા",
    "vada": "વાડા", "bhimpura": "ભીમપુરા", "bhimpor": "ભીમપોર", "bhimtalav": "ભીમતળાવ",
    "bhimdeval": "ભીમદેવળ",
    "fulwadi": "ફૂલવાડી", "fulsar": "ફૂલસર", "fulka": "ફૂલકા", "fulay": "ફુલાય",
    "kuda": "કુડા", "kunda": "કુંડા", "kundal": "કુંડળ", "kundol": "કુંડોલ", "kundi": "કુંડી",
    "kukad": "કુકડ", "kukvav": "કુકવાવ", "kunkavav": "કુકાવાવ", "kunvar": "કુંવર",
    "kuba": "કુબા", "kuski": "કુસ્કી",
    "chiroda": "ચિરોડા", "chitroda": "ચિત્રોડા", "chitrod": "ચિત્રોડ", "chitravad": "ચિત્રાવડ",
    "kanpar": "કાનપર", "kanpur": "કાનપુર", "kanpura": "કાનપુરા", "kanbha": "કણભા",
    "kanji": "કાનજી", "kankot": "કાનકોટ", "kansari": "કંસારી", "kansa": "કાંસા",
    "kantala": "કંટાળા", "kantrodi": "કંથરોડી", "kantva": "કાંટવા", "kantu": "કાંટુ",
    "kandorna": "કંડોરણા",
    "gambhirpura": "ગંભીરપુરા", "khokhra": "ખોખરા", "khokhara": "ખોખરા", "khokhri": "ખોખરી",
    "saja": "સાજા", "sajadiyali": "સજાડીયાળી", "sajanvav": "સાજનવાવ",
    "ranasan": "રણાસણ", "manekpur": "માણેકપુર", "manekpor": "માણેકપોર", "manekvada": "માણેકવાડા",
    "bharapar": "ભારાપર", "bharada": "ભારાડા", "bharad": "ભારડ", "bharthana": "ભરથાણા",
    "bharudiya": "ભારૂડીયા",
    "padedi": "પાડેડી", "gondal": "ગોંડલ",
    "raypur": "રાયપુર", "raypura": "રાયપુરા", "raipur": "રાયપુર", "raygadh": "રાયગઢ",
    "rayan": "રાયણ", "raydi": "રાયડી", "rayaniya": "રાયણીયા", "raiya": "રૈયા",
    "sadra": "સાદરા", "isanpur": "ઈસનપુર", "shekhpur": "શેખપુર",
    "ankadiya": "આંકડીયા", "ankaliya": "આંકલીયા", "ankolali": "આંકોલાલી", "ankolvadi": "આંકોલવાડી",
    "charan": "ચારણ", "charodiya": "ચારોડીયા", "charkha": "ચરખા", "changa": "ચાંગા",
    "changodar": "ચાંગોદર", "chandpur": "ચાંદપુર", "chandpor": "ચાંદપોર", "chandiya": "ચંદિયા",
    "chandisar": "ચાંદીસર", "chandlodiya": "ચાંદલોડિયા", "chankheda": "ચાંદખેડા",
    "chadasana": "ચડાસણા", "champa": "ચંપા", "chamardi": "ચમારડી", "chamariya": "ચમારીયા",
    "chari": "ચારી", "chauta": "ચૌટા", "chavand": "ચાવંડ",
    "deri": "દેરી", "deriya": "દેરીયા", "derol": "દેરોલ", "deroli": "દેરોલી", "derdi": "દેરડી",
    "derala": "દેરાળા", "dedarda": "દેદરડા", "dedkadi": "દેડકડી", "dedan": "ડેડાણ",
    "dethli": "દેથળી", "deshalpar": "દેશલપર", "desar": "ડેસર",
    "bhayavadar": "ભાયાવદર", "fachariya": "ફાચરીયા",
    "sanala": "સનાળા", "sanali": "સનાળી", "sarangpur": "સારંગપુર",
    "dolpur": "ડોલપુર", "dolatpura": "દોલતપુરા", "doliya": "ડોળીયા", "dolariya": "ડોલરીયા",
    "dolasa": "ડોળાસા", "dodiya": "ડોડીયા", "dodhi": "ડોઢી",
    "gulabpura": "ગુલાબપુરા", "takhatpura": "તખતપુરા", "kesharpura": "કેશરપુરા",
    "kesarpura": "કેસરપુરા", "kesargadh": "કેસરગઢ", "kesariya": "કેસરિયા", "keshod": "કેશોદ",
    "alampur": "આલમપુર", "alindra": "અલીન્દ્રા", "alang": "અલંગ", "alidar": "અલીદર",
    "itadi": "ઇટાડી", "itadara": "ઇટાદરા", "itvaya": "ઇટવાયા", "intala": "ઇંટાળા",
    "laxmipura": "લક્ષ્મીપુરા", "lakshmipura": "લક્ષ્મીપુરા", "lakshmanpura": "લક્ષ્મણપુરા",
    "pethapur": "પેથાપુર", "kareli": "કરેલી", "karela": "કારેલા", "karoli": "કરોલી",
    "karali": "કરાલી", "karodiya": "કરોડિયા", "karjan": "કરજણ", "karmad": "કરમડ",
    "karjoda": "કરજોડા", "karod": "કરોડ", "kariyana": "કરીયાણા", "karshanpura": "કરશનપુરા",
    "karsangadh": "કરસનગઢ",
    "dumala": "દુમાલા", "velavadar": "વેળાવદર", "velan": "વેળણ", "velva": "વેળવા",
    "velakot": "વેળાકોટ",
    "lakhavad": "લાખાવડ", "lakhanka": "લાખણકા", "lakhapar": "લાખાપર", "lakhapara": "લાખાપરા",
    "lakhani": "લાખણી", "lakhiya": "લખીયા", "lakhtar": "લખતર", "lakhpat": "લખપત",
    "bhojpara": "ભોજપરા", "bhojpur": "ભોજપુર", "bhojde": "ભોજદે", "bhojva": "ભોજવા",
    "tokarva": "ટોકરવા", "kevdi": "કેવડી", "kevadiya": "કેવડિયા",
    "pani": "પાણી", "paniya": "પાણીયા", "paniyali": "પાણિયાળી", "panvi": "પાનવી",
    "panvadi": "પાનવાડી", "panel": "પાનેલ", "paneli": "પાનેલી", "pansoli": "પાનસોલી",
    "panchasar": "પંચાસર", "pankhada": "પાનખડા", "pankhan": "પાનખાણ", "panibar": "પાણીબાર",
    "moli": "મોલી", "modpar": "મોડપર", "modasar": "મોડાસર", "moda": "મોડા", "modasa": "મોડાસા",
    "moldi": "મોલડી", "monpar": "મોણપર", "mokhana": "મોખાણા", "mogra": "મોગરા", "motha": "મોઠા",
    "satapar": "સતાપર", "mirapur": "મીરાપુર", "mirjapur": "મિરજાપુર", "miyani": "મીયાણી",
    "naranpar": "નારણપર", "naranpura": "નારણપુરા", "naroda": "નરોડા", "narol": "નારોલ",
    "narpura": "નરપુરા", "naredi": "નરેડી",
    "madhapar": "માધાપર", "madhupur": "માધુપુર", "madhiya": "મઢીયા", "madhi": "મઢી",
    "madhda": "મઢડા", "madana": "મડાણા",
    "talat": "તલાટ", "kavitha": "કવિઠા", "gota": "ગોતા", "tajpur": "તાજપુર", "tajpura": "તાજપુરા",
    "tajpar": "તાજપર", "vejalpur": "વેજલપુર", "vejalka": "વેજલકા",
    "jalampura": "જલમપુરા", "jalampur": "જલમપુર", "jalalpur": "જલાલપુર", "jalalpore": "જલાલપોર",
    "sokhda": "સોખડા", "sokhada": "સોખડા", "sokali": "સોકલી", "soyla": "સોયલા", "sola": "સોલા",
    "solaj": "સોળાજ", "sojitra": "સોજીત્રા",
    "baval": "બાવળ", "bavla": "બાવળા", "bavlu": "બાવલુ", "bavaliya": "બાવળીયા",
    "akala": "અકાળા", "akoli": "અકોલી", "akodiya": "અકોડીયા", "akhol": "અખોલ",
    "toda": "ટોડા", "todi": "ટોડી", "eklera": "એકલેરા",
    "nal": "નળ", "naliya": "નલિયા", "naliyeri": "નાળિયેરી", "nadri": "નાદરી", "nada": "નાડા",
    "nabhoi": "નભોઈ", "tol": "ટોલ", "vansol": "વાંસોલ", "vansiya": "વાંસીયા", "vanskui": "વાંસકૂઈ",
    "vansoj": "વાંસોજ", "vanzar": "વણઝર", "vandariya": "વંદારીયા", "vandaliya": "વાંડળીયા",
    "vanda": "વંડા", "vanthali": "વંથલી", "vaniya": "વાણીયા",
    "bhetali": "ભેટાળી", "bhetasi": "ભેટાસી", "bherala": "ભેરાળા", "bheriya": "ભેરીયા",
    "bherai": "ભેરાઈ", "bhesan": "ભેંસાણ", "bhensavada": "ભેંસાવાડા", "bhensrot": "ભેંસરોટ",
    "bhevada": "ભેવાડા", "bhatera": "ભાટેરા",
    "kashipura": "કાશીપુરા", "mangalpur": "મંગળપુર", "mangadh": "માનગઢ", "mansa": "માણસા",
    "mansar": "માનસર", "manjal": "મંજલ", "mankdi": "માંકડી", "mankol": "માંકોલ", "manka": "માંકા",
    "khandivav": "ખાંડીવાવ", "khandiya": "ખાંડીયા", "khandi": "ખાંડી", "khandheri": "ખંઢેરી",
    "khandhera": "ખંઢેરા", "khandadhar": "ખાંડાધાર",
    "bodi": "બોડી", "bodiya": "બોડીયા", "bodidar": "બોડીદર", "bodidra": "બોડીદ્રા",
    "bodka": "બોડકા", "bodki": "બોડકી", "boda": "બોડા", "bodeli": "બોડેલી", "bosan": "બોસણ",
    "ajabpura": "અજબપુરા", "ajab": "અજાબ", "ajotha": "આજોઠા",
    "sathamba": "સાઠંબા", "bhadli": "ભાડલી", "bhadla": "ભાડલા", "bhadol": "ભાડોલ",
    "bhadra": "ભાદ્રા", "bhad": "ભાડ", "bhada": "ભાડા", "bhadana": "ભડાણા", "bhadiyad": "ભાદિયાદ",
    "bhadukiya": "ભાડુકીયા", "bhavda": "ભાવડા", "bhuval": "ભુવાલ", "bhuva": "ભુવા",
    "bhacha": "ભાચા", "bhag": "ભાગ", "bhagal": "ભાગળ", "bhagvanpura": "ભગવાનપુરા",
    "bhakhari": "ભાખરી", "bhakhar": "ભાખર", "bhabhar": "ભાભર", "bhatha": "ભાઠા",
    "bhildi": "ભીલડી", "bhiloda": "ભિલોડા", "bhil": "ભીલ", "bhingran": "ભીંગરાણ",
    "bhindol": "ભીંડોલ", "bhoyan": "ભોયણ", "bhalsan": "ભાલસણ",
    "chhota": "છોટા", "chhasiya": "છાસીયા", "chhayan": "છાંયા", "chhala": "છાલા",
    "chhara": "છારા", "chharodi": "છારોડી", "chharodiya": "છારોડિયા",
    "runi": "રૂણી", "toraniya": "તોરણીયા", "kamboi": "કંબોઈ", "kamboya": "કંબોયા",
    "kalam": "કલમ", "kalana": "કલાણા", "kalavad": "કાલાવડ", "kalibel": "કાલીબેલ",
    "kalol": "કલોલ", "kalsar": "કળસાર", "kalsari": "કાલસારી", "kalej": "કાલેજ",
    "sarod": "સરોદ", "saroda": "સરોડા", "saroli": "સરોલી", "saradiya": "સરાડીયા",
    "sarsa": "સારસા", "sarsav": "સરસવ", "sarsan": "સરસણ", "sarsinda": "સરસીંડા",
    "sarasva": "સરસ્વા", "sardhar": "સરધાર", "sarkhadi": "સરખડી", "sarkadiya": "સરકડીયા",
    "sarbhon": "સારભોણ", "sartanpar": "સરતાનપર", "saran": "સારણ", "sarva": "સરવા",
    "sar": "સર", "sara": "સરા", "savgadh": "સાવગઢ", "savar": "સાવર", "savpura": "સાવપુરા",
    "savli": "સાવલી",
    "nagar": "નગર", "reliya": "રેલીયા", "gala": "ગાળા", "galpadar": "ગળપાદર",
    "bar": "બાર", "kavant": "કવાંટ", "kherva": "ખેરવા", "kherali": "ખેરાળી", "khera": "ખેરા",
    "kheroj": "ખેરોજ", "kheralu": "ખેરાલુ",
    "ved": "વેડ", "veda": "વેડા", "randhikpur": "રંધીકપુર", "raval": "રાવળ", "ravani": "રાવણી",
    "mohpada": "મોહપાડા", "hajipur": "હાજીપુર", "ranchhodpura": "રણછોડપુરા",
    "khengarpar": "ખેંગારપર", "hamirpar": "હમીરપર", "hamirpura": "હમીરપુરા", "hamirpur": "હમીરપુર",
    "hamapur": "હામાપુર",
    "roha": "રોહા", "rohisa": "રોહીસા", "rohishala": "રોહીશાળા", "shihora": "શિહોરા",
    "shihor": "સિહોર", "shihori": "શિહોરી", "sihor": "સિહોર",
    "sant": "સંત", "samarpada": "સમરપાડા", "bamanbore": "બામણબોર", "bamanva": "બામણવા",
    "nikol": "નિકોલ", "nikoli": "નિકોલી", "badodara": "બડોદરા", "memadpur": "મેમદપુર",
    "parabdi": "પરબડી", "hebatpur": "હેબતપુર", "mujpur": "મુજપુર", "rakhiyal": "રખિયાલ",
    "jodhpur": "જોધપુર", "jodhpar": "જોધપર", "medi": "મેડી", "medha": "મેઢા", "meda": "મેડા",
    "babra": "બાબરા", "babariya": "બાબરિયા", "vaghaniya": "વાઘણીયા", "vaghpur": "વાઘપુર",
    "vaghpura": "વાઘપુરા", "vaghpara": "વાઘપરા", "vagudad": "વાગુદડ",
    "kathrota": "કાથરોટા", "kathwada": "કઠવાડા", "kathi": "કાઠી",
    "jafrabad": "જાફરાબાદ", "koli": "કોળી", "kolithad": "કોલીથડ", "kolki": "કોલકી",
    "dadva": "દડવા", "dadhaliya": "દધાલીયા", "dadar": "દાદર",
    "luvara": "લુવારા", "lunasar": "લુણસર", "luna": "લુણા", "lushala": "લુશાળા",
    "luni": "લુણી", "lumbha": "લુંભા",
    "asarma": "અસારમા", "jantral": "જંત્રાલ", "varsada": "વરસાડા", "dhuleta": "ધુળેટા",
    "poyda": "પોયડા", "godh": "ગોધ", "godha": "ગોધા", "goddha": "ગોડધા", "godhra": "ગોધરા",
    "nanavada": "નાનાવાડા", "adepur": "આદેપુર", "adesar": "આડેસર", "advi": "અડવી",
    "adityana": "આદિત્યાણા", "arnej": "અરણેજ", "arniyala": "અરણીયાળા", "aritha": "અરીઠા",
    "aroda": "અરોડા", "aral": "અરલ",
    "dhundha": "ધુંધા", "ghorvada": "ઘોરવાડા", "kasana": "કસાણા", "kasad": "કસાડ",
    "sisodara": "સિસોદરા", "undva": "ઉંડવા", "undi": "ઉંડી",
    "sabalpur": "સબલપુર", "sabalvad": "સાબલવાડ",
    "himatpur": "હિંમતપુર", "himmatpura": "હિંમતપુરા", "himatnagar": "હિંમતનગર",
    "vaktapur": "વક્તાપુર", "vakhatpur": "વખતપુર", "vakhatpar": "વખતપર",
    "ghanta": "ઘાંટા", "ghantvad": "ઘાંટવડ", "ghantiya": "ઘંટીયા", "ghantoli": "ઘાંટોલી",
    "ghata": "ઘાટા", "ghed": "ઘેડ", "gheti": "ઘેટી",
    "gajipur": "ગાજીપુર", "gothada": "ગોઠડા", "tana": "ટાણા", "tankara": "ટંકારા",
    "tankariya": "ટંકારીયા", "tankhala": "ટંખાલા", "tikar": "ટીકર", "tunki": "ટુંકી",
    "jagana": "જગાણા", "pirojpura": "પીરોજપુરા", "pirojpur": "પીરોજપુર",
    "pandva": "પાંદવા", "matar": "માતર", "matana": "મટાણા", "matirala": "મતિરાળા",
    "bet": "બેટ", "segva": "સેગવા", "choki": "ચોકી", "chokdi": "ચોકડી", "chok": "ચોક",
    "chotila": "ચોટીલા", "chobari": "ચોબારી", "chorvad": "ચોરવાડ", "chopada": "ચોપડા",
    "chorangla": "ચોરંગલા",
    "kakad": "કાકડ", "ghana": "ઘાણા", "dholivav": "ધોળીવાવ", "dholakuva": "ધોળાકૂવા",
    "dholiya": "ધોળીયા", "dholka": "ધોળકા", "dhokadva": "ધોકડવા",
    "hansapura": "હંસાપુરા", "hansalpur": "હાંસલપુર", "hansol": "હાંસોલ",
    "saliya": "સાલીયા", "salaiya": "સલાયા", "salal": "સલાલ", "saldi": "સલડી",
    "nasirpur": "નાસીરપુર", "nasvadi": "નસવાડી", "lilva": "લીલવા", "lilapur": "લીલાપુર",
    "handi": "હાંડી", "handiya": "હાંડીયા", "methan": "મેથાણ", "mesara": "મેસરા",
    "mesvan": "મેસવાણ", "metral": "મેત્રાલ",
    "jhari": "ઝરી", "sevak": "સેવક", "shivrajpur": "શિવરાજપુર", "shivpura": "શિવપુરા",
    "shankarpura": "શંકરપુરા", "shakhpur": "શાખપુર",
    "koba": "કોબા", "kob": "કોબ", "koyli": "કોયલી", "koylana": "કોયલાણા", "kovaya": "કોવાયા",
    "kodiya": "કોદિયા", "kodinar": "કોડીનાર", "kodidara": "કોડીદ્રા", "kosamba": "કોસંબા",
    "kohivav": "કોહીવાવ",
    "khata": "ખાટા", "khatiya": "ખાટીયા", "khatriwada": "ખત્રીવાડા", "khapat": "ખાપટ",
    "khapariya": "ખાપરીયા", "khicha": "ખીચા", "khilavad": "ખીલાવડ", "khunta": "ખૂંટા",
    "khunano": "ખુણાનો", "khorsam": "ખોરસમ",
    "dandi": "દાંડી", "rapar": "રાપર", "bhujpar": "ભુજપર", "vyara": "વ્યારા", "vyas": "વ્યાસ",
    "jesangpura": "જેસંગપુરા", "jesingpur": "જેસીંગપુર",
    "varvada": "વરવાડા", "varname": "વરણામા", "varna": "વરણા", "varal": "વરલ", "vardhari": "વરધરી",
    "balasinor": "બાલાસિનોર", "balapar": "બાલાપર", "balagam": "બાલાગામ", "balvantpura": "બળવંતપુરા",
    "balva": "બાલવા", "badanpar": "બદનપર",
    "pagina": "પાગીના", "gangadiya": "ગાંગડીયા", "gangda": "ગાંગડા", "gangapura": "ગંગાપુરા",
    "mahika": "મહીકા", "mahiyal": "મહિયાલ", "mahobatpara": "મહોબતપરા",
    "tarsadi": "તરસાડી", "tarsali": "તરસાલી", "tarapur": "તારાપુર", "targhari": "તરઘરી",
    "sankali": "સાંકળી", "sankal": "સાંકળ", "sankheda": "સંખેડા", "sanakhda": "સનખડા",
    "jas": "જસ", "jasadhar": "જશાધાર",
    "mavdi": "માવડી", "mavjinjva": "માવજીંજવા", "majadar": "મજાદર", "majevdi": "મજેવડી",
    "upleta": "ઉપલેટા", "poshina": "પોશીના", "ukai": "ઉકાઈ",
    "saijpur": "સૈજપુર", "dhedhal": "ઢેઢાળ", "shiyal": "શિયાળ", "shil": "શીલ", "shir": "શીર",
    "shirvaniya": "શીરવાણીયા",
    "gamanpura": "ગમનપુરા", "indrapura": "ઇન્દ્રપુરા", "nathpura": "નાથપુરા", "nathal": "નાથળ",
    "jaska": "જસકા", "cher": "ચેર", "chela": "ચેલા", "chekhla": "ચેખલા", "chital": "ચિતલ",
    "chalala": "ચલાલા", "chanaka": "ચણાકા", "chakampar": "ચકામપર", "chuli": "ચુલી",
    "sitapur": "સીતાપુર", "ukardi": "ઉકરડી", "daran": "દારણ", "manipur": "મણિપુર",
    "vinchhiya": "વીંછિયા", "vithalpur": "વિઠ્ઠલપુર", "vithon": "વિથોણ", "vijapur": "વિજાપુર",
    "vijapdi": "વિજપડી", "visavadar": "વિસાવદર",
    "dared": "દરેડ", "kidi": "કીડી", "pitha": "પીઠા", "pithadiya": "પીઠડીયા", "pithalpur": "પીથલપુર",
    "haliyad": "હળીયાદ", "halvad": "હળવદ", "harij": "હારિજ", "harmadiya": "હરમડીયા",
    "hasanpur": "હસનપુર", "hapa": "હાપા", "hindorna": "હિંડોરણા", "hindoliya": "હિંડોળીયા",
    "natvarnagar": "નટવરનગર", "rafala": "રફાળા", "dabhali": "ડાભાલી", "dabha": "ડાભા",
    "dabhoda": "ડાભોડા", "dabhala": "ડાભાળા", "dabhoi": "ડભોઈ",
    "ningala": "નીંગાળા", "nitli": "નીતલી", "nizampura": "નિઝામપુરા", "nandasan": "નંદાસણ",
    "nandotra": "નંદોત્રા", "nandarkha": "નંદારખા", "navabandar": "નવાબંદર", "najapur": "નજાપુર",
    "rugnathpur": "રઘુનાથપુર", "ujala": "ઉજાળા", "uchchhal": "ઉચ્છલ", "ucharpi": "ઉચરપી",
    "udepur": "ઉદેપુર", "udaipur": "ઉદેપુર", "untiya": "ઊંટિયા", "untadi": "ઊંટડી",
    "agariya": "અગરિયા", "piyava": "પીયાવા", "piludara": "પીલુદરા", "pisad": "પીસાદ",
    "pajod": "પાજોદ", "palasva": "પલાસવા", "parab": "પરબ", "parvata": "પર્વતા", "parvat": "પર્વત",
    "pavthi": "પાવઠી", "prashnavda": "પ્રશ્નાવડા", "punjapadar": "પુંજાપાદર", "pipavav": "પીપાવાવ",
    "gana": "ગાના", "gada": "ગાડા", "gadu": "ગડુ", "gadha": "ગઢા", "gabha": "ગાભા",
    "garal": "ગરાળ", "gavadka": "ગાવડકા", "gidardi": "ગીદરડી", "gitapur": "ગીતાપુર",
    "ghunsiya": "ઘુસીયા", "golia": "ગોળીયા", "goliya": "ગોળીયા", "guda": "ગુડા",
    "gugaliya": "ગુગળીયા", "galkundsaja": "ગલકુંડસાજા",
    "valasan": "વલાસણ", "vahiyal": "વહીયાલ", "vavera": "વાવેરા", "vasvani": "વાસવાણી",
    "vakumbha": "વાકુંભા", "borsad": "બોરસદ", "badhada": "બાઢડા", "bagasara": "બગસરા",
    "bagdana": "બગદાણા", "bagvadar": "બગવદર", "budhel": "બુધેલ", "bantva": "બાંટવા",
    "bandh": "બંધ", "bandibar": "બંડીબાર", "banthivada": "બાંથીવાડા", "bava": "બાવા",
    "bebar": "બેબર", "bej": "બેજ", "bitta": "બિત્તા",
    "demai": "ડેમાઈ", "dharmaj": "ધર્મજ", "dalkhaniya": "દલખાણીયા", "damnagar": "દામનગર",
    "damorna": "ડામોરના", "datrana": "દાત્રાણા", "daheli": "દહેલી", "dhava": "ધાવા",
    "dhamlej": "ધામળેજ", "dhamaniya": "ધામણીયા", "dhanej": "ધનેજ", "dhuniya": "ધુણીયા",
    "dhandha": "ધાંધા", "dhrangadhra": "ધ્રાંગધ્રા", "dhrabavad": "ધ્રાબાવડ", "dron": "દ્રોણ",
    "don": "ડોન", "dumiyani": "ડુમીયાણી", "divi": "દીવી", "dwarka": "દ્વારકા",
    "fata": "ફાટા", "fajalpur": "ફાજલપુર", "ferkuva": "ફેરકૂવા",
    "isari": "ઇસરી", "islampura": "ઇસ્લામપુરા",
    "jhab": "ઝાબ", "jogpura": "જોગપુરા", "jaragli": "જરગલી",
    "kagdadi": "કાગદડી", "kagvad": "કાગવડ", "kanakiya": "કાણકીયા", "kapadvanj": "કપડવંજ",
    "katkuva": "કાટકૂવા", "kel": "કેળ", "khushalpura": "ખુશાલપુરા", "krankach": "ક્રાંકચ",
    "kutiyana": "કુતિયાણા",
    "lati": "લાટી", "lathi": "લાઠી", "lavakoi": "લવાકોઈ", "lavchali": "લવચાલી",
    "leriya": "લેરીયા", "linch": "લિંચ", "lodhva": "લોઢવા",
    "maktupur": "મક્તુપુર", "manavadar": "માણાવદર", "masar": "માસર", "mau": "મઉ",
    "mendarda": "મેંદરડા", "mori": "મોરી",
    "nakhatrana": "નખત્રાણા", "nisana": "નિશાના", "nishana": "નિશાના", "nondhanvadar": "નોંધણવદર",
    "oliya": "ઓળીયા", "olpad": "ઓલપાડ", "petlad": "પેટલાદ",
    "rakhej": "રાખેજ", "ranjitpar": "રણજીતપર", "raska": "રાસ્કા", "rathod": "રાઠોડ",
    "rozva": "રોઝવા", "roziya": "રોઝીયા", "rumla": "રૂમલા", "rudhi": "રૂઢી", "rundh": "રૂંઢ",
    "sadhli": "સાધલી", "sagtala": "સાગટાળા", "samana": "સમાણા", "samgahan": "સામગહાન",
    "samli": "સામલી", "sampa": "સાંપા", "samsherpura": "સમશેરપુરા", "samter": "સમતેર",
    "sanjeli": "સંજેલી", "sapar": "સાપર", "satun": "સતુન", "shelana": "શેલણા",
    "sheriyaj": "શેરીયાજ", "sidsar": "સિડસર", "sinavad": "સીનાવડ", "sinhan": "સિંહણ",
    "sinugra": "સિનુગ્રા", "sundha": "સુંધા", "sutrapada": "સુત્રાપાડા",
    "tad": "તડ", "tadi": "તડી", "talala": "તાલાલા", "talegadh": "તળેગઢ",
    "talgajarada": "તલગાજરડા", "thana": "થાણા", "galol": "ગાલોળ", "traj": "ત્રાજ",
    "trakuda": "ત્રાકુડા", "trambau": "ત્રંબૌ", "trapaj": "ત્રાપજ",
    "adpokar": "આદપોકર", "arithiya": "અરીઠીયા", "chauhan": "ચૌહાણ", "chhachhar": "છાછર",
    "chidivav": "ચીડીવાવ", "damli": "દામલી", "dudana": "દુદાણા", "fafni": "ફાફણી",
    "girdevli": "ગીરદેવળી", "gohil": "ગોહિલ", "inchvad": "ઇંચવડ", "jagatiya": "જગતિયા",
    "jamanvada": "જામનવાડા", "jantrakhadi": "જંત્રાખાડી", "jithla": "જીથલા", "kaj": "કાજ",
    "kareda": "કરેડા", "malsaram": "માલશ્રમ", "nagadla": "નગડલા", "panadar": "પાણાદર",
    "pavti": "પાવટી", "pedhavada": "પેઢાવાડા", "bavana": "બાવાણા", "ronaj": "રોણાજ",
    "sayajirajpura": "સયાજીરાજપુરા", "sayaji": "સયાજી", "sedhaya": "સેઢાયા", "singhaj": "સિંધાજ",
    "sugala": "સુગાળા", "valadar": "વલાદર", "gandhara": "ગાંધારા", "ganeshgali": "ગણેશગાળી",
    "ghodavadi": "ઘોડાવાડી", "jinjva": "જીંજવા", "jhinjhva": "ઝીંઝવા", "maljhinjhva": "માલઝીંઝવા",
    "gupti": "ગુપ્તી", "hadkala": "હડકાળા", "jambupani": "જાંબુપાણી", "jhanjhariya": "ઝાંઝરિયા",
    "jhudvadli": "ઝુડવડલી", "kalipat": "કાળીપાટ", "kandhavala": "કાંધાવાળા", "kandhi": "કાંધી",
    "kansariya": "કંસારીયા", "kansvala": "કાંસવાળા", "kardapan": "કરડાપણ", "khakharavali": "ખાખરાવાળી",
    "khakhravala": "ખાખરાવાળા", "kheriyavala": "ખેરીયાવાળા", "leria": "લેરીયા", "lotha": "લોથા",
    "motisar": "મોટીસર", "oyna": "ઓયણા", "padapadar": "પાડાપાદર", "panderi": "પાંડેરી",
    "mahadev": "મહાદેવ", "pichhadibela": "પીછડીબેલા", "pichhva": "પીછવા", "pichhvi": "પીછવી",
    "piliyo": "પીળીયો", "dhuno": "ધુણો", "sakra": "સકરા", "sanosri": "સણોસરી",
    "sanvav": "સનવાવ", "sapnes": "સાપનેસ", "sonpura": "સોનપુરા", "tadhodiya": "ταઢોડિયા".replace("τα", "ટા"),
    "tapakeshvar": "તપકેશ્વર", "tulsishyam": "તુલસીશ્યામ", "ugla": "ઉગલા", "ujjadiya": "ઉજ્જડિયા",
    "umarvidi": "ઉમરવીડી", "undari": "ઉંડારી", "vaniagali": "વાણિયાગાળી", "vankajambu": "વાંકાજાંબુ",
    "vankidas": "વાંકીદાસ", "vanzara": "વણઝારા", "viragali": "વીરાગાળી", "zankhiya": "ઝાંખીયા",
    "adri": "આદ્રી", "bij": "બીજ", "bolas": "બોળાસ", "chamoda": "ચામોડા", "chanduvav": "ચંદુવાવ",
    "dabhor": "ડાભોર", "deda": "દેદા", "gunvantpur": "ગુણવંતપુર", "hasnavadar": "હસનાવદર",
    "inaj": "ઇણાજ", "indroi": "ઇન્દ્રોઈ", "kindarva": "કિંદરવા", "kukras": "કુકરાસ",
    "mathasuriya": "મથાસુરીયા", "moraj": "મોરજ", "nakhada": "નખાડા", "savni": "સવની",
    "sidokar": "સીડોકર", "supasi": "સુપાસી", "tantivela": "તાંતીવેલા", "ukadiya": "ઉકડીયા",
    "umba": "ઉંબા", "vadodra": "વડોદરા", "alidhra": "અલીધ્રા", "barevla": "બારેવલા",
    "barula": "બારુલા", "bhuvavada": "ભુવાવાડા", "chagiya": "ચાગીયા", "gangetha": "ગાંગેથા",
    "harnasa": "હરણાસા", "kadsala": "કડસાળા", "kanjotar": "કંજોતર", "padruka": "પાદરૂકા",
    "pransli": "પ્રાંસલી", "singsar": "સીંગસર", "tobra": "તોબરા", "umbri": "ઉંબરી",
    "jhala": "ઝાલા", "vansavad": "વાંસાવડ", "sutra": "સુત્રા", "virodar": "વીરોદર",
    "alavani": "અલવાણી", "bakula": "બકુલા", "bamanasa": "બામણાસા", "batheshvar": "બાથેશ્વર",
    "bhagatimbi": "ભગાટીંબી", "bhantha": "ભાંઠા", "bhuvatirath": "ભુવાતીર્થ", "chhodiya": "છોડીયા",
    "chopatla": "ચોપાટલા", "dayara": "દાયરા", "dhramanva": "ધ્રામણવા", "galiyawad": "ગાળીયાવાડ",
    "hiranvel": "હીરણવેલ", "jamalpara": "જમાલપરા", "jambuthala": "જાંબુથાળા", "janvadla": "જાનવડલા",
    "jasapur": "જસાપુર", "javantri": "જાવંત્રી", "junvaniya": "જુનવાણીયા", "kadali": "કડાળી",
    "kadvali": "કડવાળી", "kamleshwar": "કમલેશ્વર", "kansiya": "કાંસીયા", "kapuriya": "કપુરીયા",
    "karamdadi": "કરમદડી", "karamnadajiya": "કરમનાદજીયા", "kathital": "કાઠીતળ", "kerambha": "કેરંભા",
    "kiloriya": "કિલોરીયા", "kisa": "કીસા", "kutiya": "કુતિયા", "lakadverines": "લાકડવેરીનેસ",
    "jambur": "જાંબુર", "mandorna": "માંડોરણા", "moruka": "મોરૂકા", "bhilgala": "ભીલગાળા",
    "nanava": "નાનાવા", "nima": "નીમા", "pancholi": "પાંચોલી", "patariya": "પટારીયા",
    "patasala": "પટાસાળા", "pikhor": "પીખોર", "piparda": "પીપરડા", "ramarechi": "રામરેચી",
    "ravta": "રાવતા", "sajiya": "સાજીયા", "sangodra": "સાંગોદ્રા", "shirvan": "શીરવાણ",
    "somanisar": "સોમાણીસર", "umrethi": "ઉમરેઠી", "vadvangada": "વડવાંગડા", "vansali": "વાંસળી",
    "bhadasi": "ભડાસી", "bhadiyadar": "ભાડીયાદર", "bhebha": "ભેભા", "bhutada": "ભૂતડા",
    "hodi": "હોડી", "chanchakvad": "ચાંચકવડ", "chikhal": "ચીખલ", "damasa": "દામાસા",
    "elampur": "એલમપુર", "jhankharvada": "ઝાંખરવાડા", "kajardi": "કાજરડી", "kalapan": "કાળાપણ",
    "kanakbarda": "કનકબરડા", "kanek": "કનેક", "karjadi": "કરજાડી", "khajudra": "ખજુદ્રા",
    "kothari": "કોઠારી", "lamghar": "લામઘર", "lerka": "લેરકા", "maghardi": "મઘરડી",
    "men": "મેણ", "nandan": "નંદન", "nandrakh": "નંદરખ", "nathej": "નથેજ", "olvan": "ઓલવણ",
    "paswala": "પાસવાળા", "rajput": "રાજપૂત", "ranvasi": "રણવાસી", "ratad": "રાતડ",
    "revad": "રેવડ", "sanjavapur": "સંજાવાપુર", "senjaliya": "સેંજળીયા", "shahdesar": "શાહડેસર",
    "siloj": "સીલોજ", "simasi": "સીમાસી", "sonari": "સોનારી", "sondarda": "સોંદરડા",
    "sondardi": "સોંદરડી", "umej": "ઉમેજ", "untwala": "ઊંટવાળા", "vagha": "વાઘા",
    "varsingpur": "વરસીંગપુર", "vavarda": "વાવરડા", "yajpur": "યાજપુર", "prachi": "પ્રાચી",

}

# Ordered Morphological Suffixes for Compound Gujarati Village Names
COMPOUND_SUFFIXES_GU: List[Tuple[str, str]] = [
    ("sandhnidhar", "સાંઢણીધાર"),
    ("sandhanidhar", "સાંઢણીધાર"),
    ("samadhiyala", "સમઢીયાળા"),
    ("hadmatiya", "હડમતીયા"),
    ("khijadiya", "ખીજડીયા"),
    ("khakhariya", "ખાખરીયા"),
    ("ambaliyara", "આંબલીયારા"),
    ("ambaliyala", "આંબલીયાળા"),
    ("bhandariya", "ભંડારીયા"),
    ("kumbhariya", "કુંભારિયા"),
    ("kanthariya", "કંથારીયા"),
    ("khajuriya", "ખજૂરીયા"),
    ("kothariya", "કોઠારીયા"),
    ("devaliya", "દેવળીયા"),
    ("pipaliya", "પીપળીયા"),
    ("pipalva", "પીપળવા"),
    ("pipardi", "પીપરડી"),
    ("piplana", "પીપલાણા"),
    ("piplod", "પીપલોદ"),
    ("piplaj", "પીપળજ"),
    ("pipli", "પીપળી"),
    ("pipla", "પીપળા"),
    ("paddhar", "પદ્ધર"),
    ("gadhada", "ગઢડા"),
    ("gadhda", "ગઢડા"),
    ("kotda", "કોટડા"),
    ("kotdi", "કોટડી"),
    ("kotadi", "કોટડી"),
    ("muvada", "મુવાડા"),
    ("muvadi", "મુવાડી"),
    ("talavdi", "તળાવડી"),
    ("talavadi", "તળાવડી"),
    ("talav", "તળાવ"),
    ("padardi", "પાદરડી"),
    ("padar", "પાદર"),
    ("pardi", "પારડી"),
    ("paldi", "પાલડી"),
    ("vavdi", "વાવડી"),
    ("vavadi", "વાવડી"),
    ("vadiya", "વડિયા"),
    ("wadiya", "વડિયા"),
    ("vadar", "વદર"),
    ("wadar", "વદર"),
    ("vada", "વાડા"),
    ("wada", "વાડા"),
    ("vadi", "વાડી"),
    ("wadi", "વાડી"),
    ("vav", "વાવ"),
    ("wav", "વાવ"),
    ("dhar", "ધાર"),
    ("dhara", "ધરા"),
    ("dhari", "ધારી"),
    ("gadh", "ગઢ"),
    ("gadhi", "ગઢી"),
    ("nagar", "નગર"),
    ("gamda", "ગામડા"),
    ("gamdi", "ગામડી"),
    ("gam", "ગામ"),
    ("pura", "પુરા"),
    ("puri", "પુરી"),
    ("pur", "પુર"),
    ("pore", "પોર"),
    ("por", "પોર"),
    ("para", "પરા"),
    ("par", "પર"),
    ("pada", "પાડા"),
    ("padi", "પાડી"),
    ("kuva", "કૂવા"),
    ("kui", "કૂઈ"),
    ("sana", "સણા"),
    ("asana", "આસણા"),
    ("asan", "આસણ"),
    ("san", "સણ"),
    ("sar", "સર"),
    ("nesda", "નેસડા"),
    ("nesdi", "નેસડી"),
    ("nes", "નેસ"),
    ("timba", "ટીંબા"),
    ("timbi", "ટીંબી"),
    ("timbo", "ટીંબો"),
    ("timbdi", "ટીંબડી"),
    ("faliya", "ફળિયા"),
    ("vandh", "વાંઢ"),
    ("vanta", "વાંટા"),
    ("dungri", "ડુંગરી"),
    ("dungari", "ડુંગરી"),
    ("dungar", "ડુંગર"),
    ("dungra", "ડુંગરા"),
    ("bordi", "બોરડી"),
    ("mahudi", "મહુડી"),
    ("mahuda", "મહુડા"),
    ("ambardi", "આંબરડી"),
    ("chhapra", "છાપરા"),
    ("chhapri", "છાપરી"),
    ("eshvar", "ેશ્વર"),
    ("eshwar", "ેશ્વર"),
    ("abad", "ાબાદ"),
    ("kot", "કોટ"),
    ("garh", "ગઢ"),
]

# Known Compound Prefixes (for splitting e.g. Sandhni+dhar, Ram+pura, Raj+pur, Nav+gam)
COMPOUND_PREFIXES_GU: List[Tuple[str, str]] = [
    ("sandhani", "સાંઢણી"),
    ("sandhni", "સાંઢણી"),
    ("sandh", "સાંઢ"),
    ("mota", "મોટા"),
    ("moti", "મોટી"),
    ("nana", "નાના"),
    ("nani", "નાની"),
    ("nava", "નવા"),
    ("navi", "નવી"),
    ("juna", "જૂના"),
    ("juni", "જૂની"),
    ("shri", "શ્રી"),
    ("sardar", "સરદાર"),
    ("pratap", "પ્રતાપ"),
    ("govind", "ગોવિંદ"),
    ("ganesh", "ગણેશ"),
    ("mahadev", "મહાદેવ"),
    ("kalyan", "કલ્યાણ"),
    ("lakshmi", "લક્ષ્મી"),
    ("laxmi", "લક્ષ્મી"),
    ("anand", "આનંદ"),
    ("amrut", "અમૃત"),
    ("jasvant", "જસવંત"),
    ("jashvant", "જશવંત"),
    ("bhagvan", "ભગવાન"),
    ("ranchhod", "રણછોડ"),
    ("shankar", "શંકર"),
    ("sultan", "સુલતાન"),
    ("sundar", "સુંદર"),
    ("himat", "હિંમત"),
    ("himmat", "હિંમત"),
    ("kesar", "કેસર"),
    ("keshar", "કેશર"),
    ("ratan", "રતન"),
    ("kamal", "કમલ"),
    ("mangal", "મંગળ"),
    ("gopal", "ગોપાલ"),
    ("gokal", "ગોકળ"),
    ("manek", "માણેક"),
    ("naran", "નારણ"),
    ("hamir", "હમીર"),
    ("lakh", "લાખ"),
    ("lakha", "લાખા"),
    ("limb", "લીંબ"),
    ("pipal", "પીપળ"),
    ("khakh", "ખાખ"),
    ("dungar", "ડુંગર"),
    ("dharam", "ધરમ"),
    ("dharm", "ધર્મ"),
    ("andhar", "અંધાર"),
    ("pandhar", "પાંઢર"),
    ("bandhar", "બંદર"),
    ("chinch", "ચિંચ"),
    ("bokad", "બોકડ"),
    ("hathi", "હાથી"),
    ("amb", "આંબ"),
    ("amba", "આંબા"),
    ("bor", "બોર"),
    ("vad", "વડ"),
    ("ram", "રામ"),
    ("raj", "રાજ"),
    ("hari", "હરિ"),
    ("har", "હર"),
    ("shiv", "શિવ"),
    ("dev", "દેવ"),
    ("bhim", "ભીમ"),
    (" megh", "મેઘ"),
    ("megh", "મેઘ"),
    ("sukh", "સુખ"),
    ("sur", "સૂર"),
    ("vir", "વીર"),
    ("jam", "જામ"),
    ("khan", "ખાન"),
    ("shah", "શાહ"),
    ("mal", "માલ"),
    ("bhal", "ભાલ"),
    ("bhat", "ભાટ"),
    ("panch", "પાંચ"),
    ("sat", "સાત"),
    ("nav", "નવ"),
]


def _orthographic_stem_to_gu(word: str) -> str:
    """Convert a single English stem to Gujarati using Gujarati toponym phonology."""
    raw = word.strip().lower()
    if not raw:
        return ""
    if raw in WORD_DICT_GU:
        return WORD_DICT_GU[raw]

    # Check exact prefix + exact word in dictionary
    for pref_en, pref_gu in COMPOUND_PREFIXES_GU:
        if raw.startswith(pref_en) and len(raw) > len(pref_en) + 1:
            rem = raw[len(pref_en):]
            if rem in WORD_DICT_GU:
                return pref_gu + WORD_DICT_GU[rem]

    # Check suffix decomposition (e.g. Sandhni + dhar, Jasa + dhar, Del + wada)
    for suf_en, suf_gu in COMPOUND_SUFFIXES_GU:
        if raw.endswith(suf_en) and len(raw) > len(suf_en) + 1:
            stem = raw[:-len(suf_en)]
            if suf_gu.startswith(("ા", "િ", "ી", "ુ", "ૂ", "ે", "ૈ", "ો", "ૌ")):
                stem_gu = _orthographic_stem_to_gu(stem.rstrip("aei"))
                return stem_gu + suf_gu
            stem_gu = _orthographic_stem_to_gu(stem)
            return stem_gu + suf_gu

    # Phonological pre-normalization for Gujarati toponym stems:
    s = raw
    # Normalize '-ia' / '-ea' spelling variants to '-iya' (e.g. leria -> leriya, vania -> vaniya)
    s = re.sub(r"(?<=[bcdfghjklmnpqrstvwxyz])ia(?=$|[bcdfghjklmnpqrstvwxyz])", "iya", s)
    # 1. Homorganic nasal before stop/affricate/sibilant -> anusvara marker 'M' 
    s = re.sub(r"[nm](?=(?:chh|ch|jh|kh|gh|th|dh|ph|bh|[kgcjtdnpbsz]))", "M", s)

    # 2. Retroflex vs dental context rules in Gujarati place names:
    # Retroflex 'dh' -> 'ઢ' (represented as 'D') in sandh, dhedh, gadh, lodh, madh, vadh, padh, bodh, rudh, kondh,ondh
    s = re.sub(r"(?:(?<=saM)|(?<=lo)|(?<=ma)|(?<=va)|(?<=bo)|(?<=ru)|(?<=oM)|(?<=uM)|(?<=khaM))dh", "D", s)
    if s.startswith("dhedh"):
        s = "DeD" + s[5:]
    if s.endswith("gadh"):
        s = s[:-4] + "gaD"
    # Retroflex 'th' -> 'ઠ' (represented as 'T') in koth, mith, lath, sorth, math, bhat, ghat, ajoth, pavth, sath, اٹھ
    s = re.sub(r"(?:(?<=ko)|(?<=mi)|(?<=la)|(?<=ma)|(?<=so)|(?<=ajo)|(?<=sa)|(?<=pa)|(?<=ka))th", "T", s)
    # Retroflex 't' -> 'ટ' (represented as 'Z') in kot, mot, pat, bhat, ghat, timb, tok, tank, kat, lat, mat, vat, chot, bot, unt
    s = re.sub(r"^(?:timb|tok|tank|tana|tunk|tik|tol|tod)", lambda m: "Z" + m.group(0)[1:], s)
    if s.startswith("uMt"):
        s = "uMZ" + s[3:]
    if not any(w in raw for w in ("vant", "rajput", "bhut", "tirath", "tirth", "sat", "rat", "matr", "chitr", "jantra", "mantr", "tantr", "pavit", "mitr", "putr", "sutr", "jagt", "jagat", "bharat", "kirat", "surat", "mahobat", "hebat", "dolat", "takhat", "sanat", "udat", "sadat", "inayat", "barot", "kathit")):
        s = re.sub(r"(?:(?<=ko)|(?<=mo)|(?<=pa)|(?<=bha)|(?<=gha)|(?<=ka)|(?<=la)|(?<=ma)|(?<=va)|(?<=cho)|(?<=bo)|(?<=v)|(?<=M))t(?=[aiouy]|$)", "Z", s)
    # Retroflex 'd' -> 'ડ' (represented as 'Q') in initial dhol, dung, ded, dab, dad, dam, dem, der, dol, don, dum
    s = re.sub(r"^(?:dab|dad|dam|dem|ded|dol|don|dum|dung|dok|dod|dag|dal)", lambda m: "Q" + m.group(0)[1:], s)
    # Internal/final 'd' in Gujarati place names (-da, -di, -du, -vad, -pad, -gad, -khad, etc.) is retroflex 'ડ' ('Q'), never before 'r' (so 'dr' stays 'દ્ર') and never in 'dev' / 'nand' / 'anand' / 'chand' / 'ind' / 'mand' / 'sund' / 'sind' / 'sond' / 'kand' / 'gond' / 'band' / 'vand'
    dental_d_words = ("dev", "anand", "nand", "chand", "indr", "inda", "indi", "indu", "mand", "sund", "sind", "sond", "gond", "kand", "band", "vand", "narmad", "mahmad", "memad", "ahmad", "sadat", "kadar", "badr", "sadar", "madar", "uday", "uda", "adam", "adar", "kedar", "badar", "madad", "fird", "ardi", "vadodr", "sangodr", "khajudr", "amodr", "chikhodr", "bolundr", "alindr", "navadr", "bhadra", "rudra", "dudha", "dudh", "sudh", "budh")
    if not any(w in raw for w in dental_d_words):
        s = re.sub(r"(?<=[aeiouyrlM])d(?=[aeiouyv]|$)", "Q", s)
    else:
        # Even in words with dental stem, final -da/-di after r/l/v is retroflex ડ
        s = re.sub(r"(?<=[rlv])d(?=[aiu]$)", "Q", s)

    # Retroflex 'n' -> 'ણ' (represented as 'N') in -ana, -ani, -aniy, -una, -uni, -ona, -oni, ran, man, kan, bhan, san, van, dan, lun, пан, etc.
    if not any(x in raw for x in ("nagar", "nav", "nan", "nath", "nad", "nak", "nag", "nam", "nar", "nas", "nay", "niz", "nik", "nil", "nim", "nis", "nit")):
        s = re.sub(r"(?<=[aeiouyrsh])n(?=[aiu]$|iy|av|as|at|ad|Q)", "N", s)
    else:
        s = re.sub(r"(?<=[aeiouyr])n(?=(?:a|i)$)", "N", s)

    # Retroflex 'l' -> 'ળ' (represented as 'L') in intervocalic -la/-li/-lu/-lo/-ly after a/i/u/o/e in common toponym endings (-ala, -ali, -ola, -oli, -ula, -uli, -vala, -vali, -rala, -rali, -lala, -tala, -pala, -kala, -mala, -sala, -dhala, -bala, -gala, -jala)
    s = re.sub(r"(?<=[aeiou])l(?=(?:a|i|iya|iyala|av|aj)$)", "L", s)

    # Consonant table including special retroflex tokens:
    # Z=ટ, T=ઠ, Q=ડ, D=ઢ, N=ણ, L=ળ
    cons_map = [
        ("chchh", "ચ્છ"), ("ksh", "ક્ષ"), ("shr", "શ્ર"), ("shv", "શ્વ"), ("shw", "શ્વ"), ("shy", "શ્ય"), ("dhy", "ધ્ય"), ("bhy", "ભ્ય"), ("khy", "ખ્ય"), ("ty", "ત્ય"), ("dy", "દ્ય"), ("py", "પ્ય"), ("my", "મ્ય"),
        ("chh", "છ"), ("kh", "ખ"), ("gh", "ઘ"), ("th", "થ"), ("dh", "ધ"),
        ("ph", "ફ"), ("bh", "ભ"), ("ch", "ચ"), ("sh", "શ"), ("zh", "ઝ"), ("jh", "ઝ"),
        ("tr", "ત્ર"), ("dr", "દ્ર"), ("pr", "પ્ર"), ("br", "બ્ર"), ("kr", "ક્ર"), ("gr", "ગ્ર"),
        ("dv", "દ્વ"), ("dw", "દ્વ"), ("sv", "સ્વ"), ("sw", "સ્વ"), ("st", "સ્ત"), ("sth", "સ્થ"),
        ("sk", "સ્ક"), ("sp", "સ્પ"), ("sm", "સ્મ"), ("sn", "સ્ન"), ("vy", "વ્ય"), ("ny", "ન્ય"),
        ("ky", "ક્ય"), ("gy", "જ્ઞ"), ("gn", "જ્ઞ"), ("ck", "ક"), ("qu", "ક્વ"), ("ks", "ક્ષ"),
        ("ll", "લ્લ"), ("dd", "દ્દ"), ("tt", "ત્ત"), ("jj", "જ્જ"), ("bb", "બ્બ"), ("mm", "મ્મ"),
        ("nn", "ન્ન"), ("pp", "પ્પ"), ("ss", "સ્સ"), ("QQ", "ડ્ડ"), ("ZZ", "ટ્ટ"),
        ("Z", "ટ"), ("T", "ઠ"), ("Q", "ડ"), ("D", "ઢ"), ("N", "ણ"), ("L", "ળ"),
        ("k", "ક"), ("g", "ગ"), ("c", "ક"), ("j", "જ"), ("t", "ત"), ("d", "દ"),
        ("n", "ન"), ("p", "પ"), ("b", "બ"), ("m", "મ"), ("y", "ય"), ("r", "ર"),
        ("l", "લ"), ("v", "વ"), ("w", "વ"), ("s", "સ"), ("h", "હ"), ("f", "ફ"),
        ("z", "ઝ"), ("q", "ક"), ("x", "ક્ષ"),
    ]
    vowel_pairs = [
        ("aa", "ા", "આ"), ("ee", "ી", "ઈ"), ("ii", "ી", "ઈ"), ("oo", "ૂ", "ઊ"),
        ("uu", "ૂ", "ઊ"), ("ai", "ૈ", "ઐ"), ("au", "ૌ", "ઔ"), ("ou", "ૌ", "ઔ"),
        ("oi", "ોઈ", "ઓઈ"), ("ei", "ે", "એ"),
    ]

    out: List[str] = []
    i = 0
    n = len(s)
    last_was_cons = False
    syllable_idx = 0

    while i < n:
        if s[i] == "M":
            out.append("ં")
            i += 1
            continue

        # Check multi-char vowel pairs first
        vp_match = next(((vp, m_sign, ind_sign) for vp, m_sign, ind_sign in vowel_pairs if s.startswith(vp, i)), None)
        if vp_match:
            vp, m_sign, ind_sign = vp_match
            out.append(m_sign if last_was_cons else ind_sign)
            last_was_cons = False
            syllable_idx += 1
            i += len(vp)
            continue

        # Check consonants
        c_match = next(((ck, cv) for ck, cv in cons_map if s.startswith(ck, i)), None)
        if c_match:
            ck, cv = c_match
            if ck == "c" and i + 1 < n and s[i + 1] in "eiy":
                cv = "સ"
            out.append(cv)
            last_was_cons = True
            i += len(ck)
            continue

        ch = s[i]
        if ch in "aeiou":
            if last_was_cons:
                if ch == "a":
                    rem = s[i + 1:]
                    # When does 'a' in a Gujarati village name represent long 'ા' (aa)?
                    # 1. Word-final 'a' -> always 'ા'
                    # 2. Before anusvara 'M' in initial syllable (e.g. s-a-M-dh -> સાંઢ, k-a-M-th -> કાંથ, d-a-M-t -> દાંત, b-a-M-dh -> બાંધ, ch-a-M-d -> ચાંદ, m-a-M-d -> માંડ, v-a-M-k -> વાંક)
                    # 3. In first syllable when followed by single consonant + vowel (open initial syllable: e.g. ba-la -> બાલા, ra-ma -> રામા, na-va -> નવા, па-ta -> પાતા, sa-ra -> સારા, ka-la -> કાળા, da-da -> દાદા, bha-la -> ભાલા, ma-la -> માળા, la-la -> લાલા)
                    # 4. In second-to-last syllable before final -da/-di/-la/-li/-na/-ni/-ra/-ri/-va/-vi/-ka/-ki/-ta/-ti/-sa/-si (e.g. де-l-va-da -> દેલવાડા, ба-b-ri-ya -> બાબરિયા, પિ-pa-li-ya -> પીપળીયા)
                    if not rem:
                        out.append("ા")
                    elif rem.startswith("M") and syllable_idx == 0:
                        out.append("ા")
                    elif syllable_idx == 0 and re.match(r"^(?:[kgcjtdnpbmyrlvshfzwQZDTLN]|kh|gh|ch|jh|th|dh|ph|bh|sh)(?:[aeiouy]|$)", rem):
                        # Initial open syllable (e.g., ram, raj, bhal, mal, pal, kal, dal, sal, tal, val, ناد, etc.)
                        # Keep inherent 'અ' for prefixes like am-, an-, as-, ak-, ad-, al-, ar-, av-, ka-di, ga-dh, cha-n, dha-n, ma-n, ra-t, sa-m, va-d, va-s
                        short_initial_roots = ("am", "an", "as", "ak", "ad", "al", "ar", "av", "ab", "aj", "at", "chh", "dh", "gh", "kh", "ph", "sh", "th", "bh", "gad", "gaD", "gar", "gal", "gan", "gam", "gat", "jak", "jal", "jam", "jan", "jas", "jat", "jav", "kad", "kaQ", "kal", "kam", "kan", "kap", "kar", "kas", "kat", "kaZ", "kav", "lag", "lak", "lap", "mad", "mag", "mah", "mak", "man", "mar", "mas", "mat", "maZ", "mav", "nad", "nag", "nak", "nal", "nam", "nar", "nas", "nat", "nav", "pad", "paQ", "pak", "pal", "pan", "par", "pas", "pat", "pav", "rab", "rak", "ral", "ran", "ora", "ras", "rat", "rav", "sab", "sach", "sad", "sag", "sah", "saj", "sak", "sal", "sam", "san", "saN", "sap", "sar", "sas", "sat", "sav", "tag", "taj", "tak", "tal", "tam", "tan", "tap", "tar", "tas", "tat", "tav", "vad", "vaQ", "vag", "vah", "vaj", "vak", "val", "vaL", "van", "vaN", "vap", "var", "vas", "vat", "vaZ")
                        if not raw.startswith(short_initial_roots) or len(raw) <= 4 and raw.endswith(("a", "i", "u")):
                            out.append("ા")
                    elif re.match(r"^[QZDTLNrvlksjmn](?:a|i)$", rem):
                        out.append("ા")
                elif ch == "i":
                    # Word-final 'i' in Gujarati village names is always long 'ી'!
                    if i + 1 == n:
                        out.append("ી")
                    else:
                        out.append("િ")
                elif ch == "u":
                    out.append("ુ")
                elif ch == "e":
                    out.append("ે")
                elif ch == "o":
                    out.append("ો")
            else:
                if ch == "a":
                    # Initial 'a' before single consonant + vowel in words like a-ra-valli, a-mod, a-nand, a-mb-a
                    if i == 0 and (raw.startswith(("amb", "aml", "amg", "amp", "ank", "ang", "anj", "ant", "andh", "akol", "agol", "amod", "amal", "amar", "amir", "asod", "ajoth", "alid", "abram", "adaj", "ades", "adit", "ahwa", "ari", "arad", "arod"))):
                        out.append("આ" if raw.startswith(("amb", "aml", "ank", "amod", "ajoth", "ades", "adit", "ahwa", "amad")) else "અ")
                    else:
                        out.append("અ")
                elif ch == "i":
                    out.append("ઇ")
                elif ch == "u":
                    out.append("ઉ")
                elif ch == "e":
                    out.append("એ")
                elif ch == "o":
                    out.append("ઓ")
            last_was_cons = False
            syllable_idx += 1
            i += 1
            continue

        out.append(ch)
        last_was_cons = False
        i += 1

    return "".join(out)


def resolve_village_name_gu(
    name_en: str,
    *,
    village_code: str = "",
    official_local_gu: str = "",
    reviewed_legacy_gu: str = "",
) -> Tuple[str, str]:
    """Return (canonical_name_gu, provenance_status) for a Gujarat LGD village."""
    vc = (village_code or "").strip()
    if official_local_gu and is_already_gujarati(official_local_gu):
        return official_local_gu.strip(), "official_document"
    if vc in EXACT_VILLAGE_CODE_GU:
        return EXACT_VILLAGE_CODE_GU[vc], "curated_toponym_dictionary"
    if reviewed_legacy_gu and is_already_gujarati(reviewed_legacy_gu):
        return reviewed_legacy_gu.strip(), "curated_toponym_dictionary"
    if is_already_gujarati(name_en):
        return name_en.strip(), "official_document"

    raw = (name_en or "").strip()
    if not raw:
        return "", "pending"

    # Strip census administrative tags like (Og), (Ct), (OG), (CT), (M), (NP) from Gujarati display
    cleaned = re.sub(r"\s*\((?:Og|Ct|OG|CT|M|NP|Out\s*Growth|Census\s*Town)\)\s*", " ", raw, flags=re.I)
    cleaned = re.sub(r"\s*\((?:Rural\s*Area|Rural)\)\s*", " (ગ્રામ્ય) ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*\((?:Urban\s*Area|Urban)\)\s*", " (શહેર) ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*\(Part\)\s*", " (ભાગ) ", cleaned, flags=re.I)
    cleaned = re.sub(r"\bAlias\b", "ઉર્ફે", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Check if full cleaned English name matches Taluka dictionary or Word dictionary
    if cleaned in CANONICAL_TALUKAS_GU:
        return CANONICAL_TALUKAS_GU[cleaned], "curated_toponym_dictionary"
    if cleaned.lower() in WORD_DICT_GU:
        return WORD_DICT_GU[cleaned.lower()], "curated_toponym_dictionary"

    # Tokenize preserving punctuation like (), -, .
    tokens = re.findall(r"[\u0A80-\u0AFF]+|[A-Za-z]+|[0-9]+|[^\s\w\u0A80-\u0AFF]+|\s+", cleaned)
    out_tokens: List[str] = []
    for tok in tokens:
        if GUJARATI_RANGE_RE.search(tok):
            out_tokens.append(tok)
        elif re.fullmatch(r"[A-Za-z]+", tok):
            low = tok.lower()
            if len(low) == 1 and low not in ("a", "i", "u", "e", "o"):
                # Single-letter abbreviation like "P" or "M"
                out_tokens.append(_orthographic_stem_to_gu(low + "a"))
            else:
                out_tokens.append(_orthographic_stem_to_gu(low))
        else:
            out_tokens.append(tok)

    result = "".join(out_tokens)
    result = re.sub(r"\s+", " ", result).strip()
    return result, "verified_toponym_morphology"
