"""Fetches the Stage 1 corpus (15+ long public docs with numeric tables) into corpus/.

corpus/ is gitignored — this script is the reproducible source of truth for the corpus,
not the PDFs themselves. Network required to run this script; the QA/verify/quant pipeline
itself never needs network at runtime (constraint #1).

Usage: python download_corpus.py
"""
import sys
import time
import urllib.request
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

# CORPUS: list of {doc_id, title, org, url}. Every entry was confirmed by an actual HTTP fetch
# (200 + content-type: application/pdf) AND opened with a PDF parser to confirm selectable text
# (i.e. not scanned/image-only, so no OCR dependency) before being added. See AI_LOG.md Phase 1.
#
# Reproducibility note: dated/archive URLs were preferred over rolling "current release" links
# wherever both existed, so the corpus is a fixed snapshot. `census_housing_vacancies` is the one
# exception — Census publishes it only at a rolling URL whose content changes quarterly.
CORPUS = [
    {
        "doc_id": "fdic_quarterly_banking_profile_2024q1",
        "title": "Quarterly Banking Profile, Q1 2024",
        "org": "FDIC",
        "url": "https://www.fdic.gov/analysis/quarterly-banking-profile/qbp/2024mar/qbp.pdf",
    },
    {
        "doc_id": "bea_gdp_2024q1_second_estimate",
        "title": "Gross Domestic Product, First Quarter 2024 (Second Estimate)",
        "org": "Bureau of Economic Analysis",
        "url": "https://www.bea.gov/sites/default/files/2024-05/gdp1q24-2nd.pdf",
    },
    {
        "doc_id": "bea_personal_income_outlays_2024_04",
        "title": "Personal Income and Outlays, April 2024",
        "org": "Bureau of Economic Analysis",
        "url": "https://www.bea.gov/sites/default/files/2024-06/pi0524.pdf",
    },
    {
        "doc_id": "census_ft900_trade_2024_03",
        "title": "U.S. International Trade in Goods and Services (FT-900), March 2024",
        "org": "Census Bureau / BEA",
        "url": "https://www.census.gov/foreign-trade/Press-Release/ft900/ft900_2403.pdf",
    },
    {
        "doc_id": "census_poverty_2022_p60_280",
        "title": "Poverty in the United States: 2022 (P60-280)",
        "org": "Census Bureau",
        "url": "https://www.census.gov/content/dam/Census/library/publications/2023/demo/p60-280.pdf",
    },
    {
        "doc_id": "fed_survey_consumer_finances_2022",
        "title": "Changes in U.S. Family Finances from 2019 to 2022 (SCF Bulletin)",
        "org": "Federal Reserve Board",
        "url": "https://www.federalreserve.gov/publications/files/scf23.pdf",
    },
    {
        "doc_id": "usda_wasde_2026_06",
        "title": "World Agricultural Supply and Demand Estimates (WASDE), June 2026",
        "org": "USDA",
        "url": "https://esmis.nal.usda.gov/sites/default/release-files/795937/wasde0626v2.pdf",
    },
    {
        "doc_id": "oecd_economic_outlook_116_annex",
        "title": "OECD Economic Outlook, Statistical Annex (Vol 2024 Issue 2)",
        "org": "OECD",
        "url": "https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/economic-outlook/eo116/EO116_Annexes_E.pdf",
    },
    {
        "doc_id": "treasury_monthly_statement_2024_06",
        "title": "Monthly Treasury Statement, June 2024",
        "org": "U.S. Treasury, Bureau of the Fiscal Service",
        "url": "https://fiscaldata.treasury.gov/static-data/published-reports/mts/MonthlyTreasuryStatement_202406.pdf",
    },
    {
        "doc_id": "bea_international_transactions_2024q1",
        "title": "U.S. International Transactions, First Quarter 2024",
        "org": "Bureau of Economic Analysis",
        "url": "https://www.bea.gov/sites/default/files/2024-06/trans124.pdf",
    },
    {
        "doc_id": "fed_monetary_policy_report_2024_03",
        "title": "Monetary Policy Report, March 2024",
        "org": "Federal Reserve Board",
        "url": "https://www.federalreserve.gov/publications/files/20240301_mprfullreport.pdf",
    },
    {
        "doc_id": "worldbank_commodity_markets_2025_04",
        "title": "Commodity Markets Outlook, April 2025",
        "org": "World Bank",
        "url": "https://thedocs.worldbank.org/en/doc/1b388949805c9a0ae3736bdacb32ea94-0050012025/original/CMO-April-2025.pdf",
    },
    {
        "doc_id": "epa_automotive_trends_2024_exec_summary",
        "title": "The 2024 EPA Automotive Trends Report — Executive Summary",
        "org": "EPA",
        "url": "https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P101CUZD.pdf",
    },
    {
        "doc_id": "eia_short_term_energy_outlook_2025_05",
        "title": "Short-Term Energy Outlook, May 2025",
        "org": "U.S. Energy Information Administration",
        "url": "https://www.eia.gov/outlooks/steo/archives/may25.pdf",
    },
    {
        "doc_id": "usda_agricultural_prices_2025_09",
        "title": "Agricultural Prices, September 2025",
        "org": "USDA NASS",
        "url": "https://esmis.nal.usda.gov/sites/default/release-files/c821gj76b/xg94kp17m/c534hn55p/agpr0925.pdf",
    },
    {
        "doc_id": "census_housing_vacancies",
        "title": "Housing Vacancies and Homeownership (CPS/HVS), current quarterly release",
        "org": "Census Bureau",
        "url": "https://www.census.gov/housing/hvs/files/currenthvspress.pdf",
    },
]


def download_one(entry, dest_dir=CORPUS_DIR, timeout=60, retries=2):
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{entry['doc_id']}.pdf"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  already have {dest.name} ({dest.stat().st_size // 1024} KB)")
        return True

    req = urllib.request.Request(entry["url"], headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(1, retries + 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read()
            if b"%PDF" not in data[:1024]:
                print(f"  FAILED {entry['doc_id']}: response is not a PDF "
                      f"(content-type={content_type!r}, first bytes={data[:16]!r})")
                return False
            dest.write_bytes(data)
            print(f"  OK {entry['doc_id']} ({len(data) // 1024} KB)")
            return True
        except Exception as e:
            print(f"  attempt {attempt} failed for {entry['doc_id']}: {type(e).__name__}: {e}")
            if attempt <= retries:
                time.sleep(2 * attempt)
    return False


def main():
    if not CORPUS:
        print("CORPUS is empty — populate the list in download_corpus.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Downloading {len(CORPUS)} documents into {CORPUS_DIR}/ ...")
    failures = []
    for entry in CORPUS:
        print(f"[{entry['doc_id']}] {entry['title']}")
        if not download_one(entry):
            failures.append(entry["doc_id"])

    print(f"\nDone: {len(CORPUS) - len(failures)}/{len(CORPUS)} succeeded.")
    if failures:
        print(f"Failed: {failures}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
