from pathlib import Path

from .models import Mandate, Portfolio
from .supervisor import CommitteeSupervisor


def main() -> None:
    initial = Portfolio(
        weights={"TECH_ETF": 0.20, "BOND_ETF": 0.30, "ENERGY_ETF": 0.10, "HEALTH_ETF": 0.25, "CASH": 0.15},
        sectors={"TECH_ETF": "Technology", "BOND_ETF": "Fixed Income", "ENERGY_ETF": "Energy", "HEALTH_ETF": "Healthcare", "CASH": "Cash"},
    )
    audit = Path("runs/latest-audit.jsonl")
    result = CommitteeSupervisor(audit).run(initial, Mandate(), human_approved=True)
    print(f"Status: {result.status}")
    print(f"Initial: {result.initial.weights}")
    print(f"Unsafe proposal: {result.proposed.weights}")
    print(f"Final after veto/review: {result.final.weights}")
    print(f"Messages: {result.message_count}; audit: {audit}")


if __name__ == "__main__":
    main()

