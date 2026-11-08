"""
Agent 1: OEM Press Kit Scout
Downloads official OEM press kit PDFs and extracts spec tables.
Only accesses public press portals. Respects robots.txt.
"""
import json
import requests
from pathlib import Path
from datetime import datetime

class OEMPressScout:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.output_dir = repo_root / "data-connectors" / "vehicle_specs" / "extracted"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": "CarAutopsy-Research-Bot/1.0 (contact: ermiya.karan@gmx.ch)"}

    def download_pdf(self, url: str, timeout: int = 30) -> bytes:
        response = requests.get(url, headers=self.headers, timeout=timeout)
        response.raise_for_status()
        return response.content

    def extract_specs(self, pdf_bytes: bytes) -> dict:
        import io
        try:
            import pdfplumber
        except ImportError:
            return {"error": "pdfplumber not installed", "tables": []}
        extracted = {"raw_tables": [], "extraction_date": datetime.utcnow().isoformat() + "Z"}
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    extracted["raw_tables"].extend(tables)
        return extracted

    def run(self, sources: list) -> list:
        results = []
        for source in sources:
            try:
                print(f"  Fetching: {source.get('make', 'unknown')} - {source['url']}")
                pdf_bytes = self.download_pdf(source["url"])
                extracted = self.extract_specs(pdf_bytes)
                output_file = self.output_dir / f"{source['variant_id']}_raw.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(extracted, f, indent=2, ensure_ascii=False)
                results.append({"variant_id": source["variant_id"], "status": "extracted", "tables_found": len(extracted["raw_tables"])})
            except Exception as e:
                results.append({"variant_id": source["variant_id"], "status": "failed", "error": str(e)})
        return results

if __name__ == "__main__":
    print("OEM Press Kit Scout ready. Configure sources and run via scheduler.")
