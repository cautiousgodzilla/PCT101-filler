"""Quick offline check of the XML form-fill engine — writes Forms 1/2/3/5 to
_out/ so you can open them in Word. No server, no API key.

    cd filler
    python _local_fill_test.py
    -> _out/Form_1.docx ... Form_5.docx
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))
from _forms import fill_form  # noqa: E402

# Sample matching the Bechtel new-template sample (edit freely to test counts).
DATA = {
    "title_of_invention": "SYSTEMS AND METHODS FOR AMMONIA PURIFICATION",
    "international_application_no": "PCT/US2024/032613",
    "international_filing_date": "05 June 2024",
    "application_number": "202617012345",
    "date": "23/06/2026",
    "description_pages": 14, "claims_count": 41, "claims_pages_listed": 8,
    "abstract_pages_listed": 1, "drawings_count": 4, "drawings_pages_listed": 3,
    "applicants": [
        {"name": "BECHTEL ENERGY TECHNOLOGIES & SOLUTIONS, INC.", "nationality": "US",
         "country_of_residence": "US",
         "address": "2105 Citywest Blvd, Houston, TX 77042, United States of America"},
    ],
    "inventors": [
        {"name": "TAYLOR, Martin", "nationality": "US", "country_of_residence": "US",
         "address": "11526 Meadow Lake Drive, Houston, TX 77077, United States of America"},
        {"name": "PETERS, Arlin", "nationality": "US", "country_of_residence": "US",
         "address": "211 Yale Avenue, Kensington, CA 94708, United States of America"},
        {"name": "KIMTANTAS, Charles", "nationality": "US", "country_of_residence": "US",
         "address": "2831 N. Blue Meadow Circle, Sugar Land, TX 77479, United States of America"},
    ],
}

OUT = os.path.join(os.path.dirname(__file__), "_out")
os.makedirs(OUT, exist_ok=True)
# Pass an email whose domain matches firm_config.json to fill the real roster:
EMAIL = os.environ.get("TEST_EMAIL", "")

for fid in ("1", "2", "3", "5"):
    blob = fill_form(fid, DATA, user_email=EMAIL)
    path = os.path.join(OUT, f"Form_{fid}.docx")
    with open(path, "wb") as fh:
        fh.write(blob)
    print(f"wrote {path}  ({len(blob)} bytes)")
print("\nOpen the files in _out/ with Microsoft Word to confirm styling.")
