import tempfile
import unittest
from pathlib import Path

from portfolio_mas.models import Mandate, MessageType, Portfolio
from portfolio_mas.supervisor import CommitteeSupervisor


def portfolio() -> Portfolio:
    return Portfolio(
        {"TECH_ETF": .20, "BOND_ETF": .30, "ENERGY_ETF": .10, "HEALTH_ETF": .25, "CASH": .15},
        {"TECH_ETF": "Technology", "BOND_ETF": "Fixed Income", "ENERGY_ETF": "Energy", "HEALTH_ETF": "Healthcare", "CASH": "Cash"},
    )


class CommitteeSafetyTests(unittest.TestCase):
    def test_compliance_veto_removes_restricted_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "audit.jsonl"
            supervisor = CommitteeSupervisor(audit)
            result = supervisor.run(portfolio(), Mandate(), human_approved=True)
            self.assertEqual(result.status, "APPROVED")
            self.assertNotIn("SANCTIONED_OIL", result.final.weights)
            self.assertTrue(any(m.message_type is MessageType.VETO for m in supervisor.board.messages))
            self.assertEqual(audit.read_text().count("\n"), result.message_count)

    def test_human_gate_blocks_and_rolls_back(self) -> None:
        result = CommitteeSupervisor().run(
            portfolio(), Mandate(human_approval_threshold=.05), human_approved=False
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.final.weights, result.initial.weights)

    def test_weights_remain_balanced(self) -> None:
        result = CommitteeSupervisor().run(portfolio(), Mandate(), human_approved=True)
        self.assertEqual(round(sum(result.final.weights.values()), 6), 1.0)


if __name__ == "__main__":
    unittest.main()
