"""
Agent 3: Schema Enforcer
Maps extracted data to canonical JSON schema. Stages for human review.
"""
import json
from pathlib import Path
from datetime import datetime

class SchemaEnforcer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.variants_dir = repo_root / "catalog" / "variants"
        self.staging_dir = repo_root / "catalog" / "staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def stage_for_review(self, variant: dict) -> Path:
        path = self.staging_dir / f"{variant['variant_id']}_REVIEW.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(variant, f, indent=2, ensure_ascii=False)
        return path

    def promote_to_catalog(self, variant_id: str) -> bool:
        staged = self.staging_dir / f"{variant_id}_REVIEW.json"
        if not staged.exists():
            return False
        with open(staged, "r", encoding="utf-8") as f:
            data = json.load(f)
        target = self.variants_dir / f"{variant_id}.json"
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        staged.unlink()
        return True

if __name__ == "__main__":
    print("Schema Enforcer ready. Use stage_for_review() and promote_to_catalog().")
