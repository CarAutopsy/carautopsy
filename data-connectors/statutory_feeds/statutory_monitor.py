"""
Agent 2: Statutory Monitor
Watches BMF and E-Control for tax/tariff changes.
"""
import json
import requests
from pathlib import Path
from datetime import datetime

class StatutoryMonitor:
    BMF_NOVA_URL = "https://www.bmf.gv.at/themen/steuern/verbrauchsteuern/nova.html"
    ECONTROL_URL = "https://www.e-control.at/statistik/haushalt/strompreise"

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.alerts_dir = repo_root / "data-connectors" / "statutory_feeds" / "alerts"
        self.alerts_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": "CarAutopsy-Statutory-Monitor/1.0 (contact: ermiya.karan@gmx.ch)"}

    def check_source(self, name: str, url: str) -> dict:
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            return {"source": name, "url": url, "status_code": response.status_code, "checked_at": datetime.utcnow().isoformat() + "Z", "status": "reachable"}
        except Exception as e:
            return {"source": name, "url": url, "status": "error", "error": str(e)}

    def run_all(self) -> list:
        results = [
            self.check_source("BMF NoVA", self.BMF_NOVA_URL),
            self.check_source("E-Control", self.ECONTROL_URL)
        ]
        alert_file = self.alerts_dir / f"check_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
        with open(alert_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        return results

if __name__ == "__main__":
    monitor = StatutoryMonitor(Path(__file__).resolve().parent.parent.parent)
    results = monitor.run_all()
    for r in results:
        print(f"  {r['source']}: {r['status']}")
