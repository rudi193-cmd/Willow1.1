#!/usr/bin/env python3
import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from core.coherence import compute_delta_e, get_knowledge_atoms

# Configure logging
LOG_FILE = Path(__file__).parent / "coherence_scan.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class CoherenceScannerDaemon:
    def __init__(self, interval: int = 3600, drift_threshold: float = 0.5, contradiction_threshold: float = 0.8):
        self.interval = interval
        self.drift_threshold = drift_threshold
        self.contradiction_threshold = contradiction_threshold
        self.running = False

    def scan_coherence(self) -> None:
        """Scan the knowledge base for coherence issues."""
        try:
            atoms = get_knowledge_atoms()
            if not atoms:
                logger.warning("No knowledge atoms found to scan")
                return

            issues = self._analyze_coherence(atoms)
            self._log_issues(issues)

        except Exception as e:
            logger.error(f"Error during coherence scan: {str(e)}", exc_info=True)

    def _analyze_coherence(self, atoms: List[Dict]) -> Dict[str, List[Tuple[str, str]]]:
        """Analyze coherence between knowledge atoms."""
        issues = {
            "drift": [],
            "contradiction": [],
            "gap": []
        }

        # Check for gaps (orphaned atoms)
        connected_atoms = set()
        for atom in atoms:
            for related in atom.get("related_atoms", []):
                connected_atoms.add(related)

        for atom in atoms:
            if atom["id"] not in connected_atoms and atom["id"] not in [a["id"] for a in atoms if a["id"] != atom["id"]]:
                issues["gap"].append((atom["id"], "No connections found"))

        # Check for drift and contradictions between related atoms
        for atom in atoms:
            for related_id in atom.get("related_atoms", []):
                related_atom = next((a for a in atoms if a["id"] == related_id), None)
                if not related_atom:
                    continue

                delta_e = compute_delta_e(atom, related_atom)
                if delta_e > self.contradiction_threshold:
                    issues["contradiction"].append((atom["id"], related_atom["id"]))
                elif delta_e > self.drift_threshold:
                    issues["drift"].append((atom["id"], related_atom["id"]))

        return issues

    def _log_issues(self, issues: Dict[str, List[Tuple[str, str]]]) -> None:
        """Log coherence issues."""
        for issue_type, atom_pairs in issues.items():
            if not atom_pairs:
                continue

            for atom1, atom2 in atom_pairs:
                if issue_type == "gap":
                    logger.warning(f"Gap detected: {atom1}")
                else:
                    logger.warning(f"{issue_type.capitalize()} between {atom1} and {atom2}")

    def run(self) -> None:
        """Run the daemon in a loop."""
        self.running = True
        logger.info(f"Starting coherence scanner with interval {self.interval} seconds")

        try:
            while self.running:
                self.scan_coherence()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            logger.info("Shutting down coherence scanner")
        except Exception as e:
            logger.error(f"Unexpected error in daemon: {str(e)}", exc_info=True)
        finally:
            self.running = False

def main():
    parser = argparse.ArgumentParser(description="Coherence Scanner Daemon")
    parser.add_argument("--interval", type=int, default=3600,
                        help="Scan interval in seconds (default: 3600)")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Drift threshold (default: 0.5)")
    parser.add_argument("--daemon", action="store_true",
                        help="Run as a daemon")
    args = parser.parse_args()

    scanner = CoherenceScannerDaemon(
        interval=args.interval,
        drift_threshold=args.threshold,
        contradiction_threshold=0.8  # Hardcoded contradiction threshold
    )

    if args.daemon:
        scanner.run()
    else:
        scanner.scan_coherence()

if __name__ == "__main__":
    main()
