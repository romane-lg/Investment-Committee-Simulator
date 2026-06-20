import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from portfolio_mas.blackboard import Blackboard
from portfolio_mas.models import (
    HumanApproval,
    Mandate,
    Message,
    MessageType,
    Portfolio,
)
from portfolio_mas.supervisor import CommitteeSupervisor


def portfolio() -> Portfolio:
    return Portfolio(
        {"TECH_ETF": .20, "BOND_ETF": .30, "ENERGY_ETF": .10, "HEALTH_ETF": .25, "CASH": .15},
        {"TECH_ETF": "Technology", "BOND_ETF": "Fixed Income", "ENERGY_ETF": "Energy", "HEALTH_ETF": "Healthcare", "CASH": "Cash"},
    )


def approve(proposal_hash: str) -> HumanApproval:
    return HumanApproval(
        approver="chair@example.com",
        proposal_hash=proposal_hash,
        approved=True,
        rationale="Risk and compliance controls cleared.",
    )


class CommitteeSafetyTests(unittest.TestCase):
    def test_compliance_veto_removes_restricted_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "audit.jsonl"
            supervisor = CommitteeSupervisor(audit)
            result = supervisor.run(portfolio(), Mandate(), approve)
            self.assertEqual(result.status, "APPROVED")
            self.assertNotIn("SANCTIONED_OIL", result.final.weights)
            self.assertTrue(any(m.message_type is MessageType.VETO for m in supervisor.board.messages))
            self.assertEqual(audit.read_text().count("\n"), result.message_count)

    def test_human_gate_blocks_and_rolls_back_without_approval(self) -> None:
        result = CommitteeSupervisor().run(
            portfolio(), Mandate(human_approval_threshold=.05)
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.final.weights, result.initial.weights)

    def test_approval_is_bound_to_exact_proposal_hash(self) -> None:
        def stale_approval(_: str) -> HumanApproval:
            return HumanApproval(
                approver="chair@example.com",
                proposal_hash="hash-from-an-older-proposal",
                approved=True,
                rationale="Previously approved.",
            )

        supervisor = CommitteeSupervisor()
        result = supervisor.run(portfolio(), Mandate(), stale_approval)
        self.assertEqual(result.status, "BLOCKED")
        approval = next(
            m for m in supervisor.board.messages
            if m.message_type is MessageType.APPROVAL
        )
        self.assertFalse(approval.payload["hash_matches"])

    def test_stale_approval_is_rejected(self) -> None:
        def stale_approval(proposal_hash: str) -> HumanApproval:
            return HumanApproval(
                approver="chair@example.com",
                proposal_hash=proposal_hash,
                approved=True,
                rationale="Approval is too old.",
                timestamp=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            )

        result = CommitteeSupervisor().run(portfolio(), Mandate(), stale_approval)
        self.assertEqual(result.status, "BLOCKED")

    def test_approval_cannot_be_replayed(self) -> None:
        supervisor = CommitteeSupervisor()
        issued: HumanApproval | None = None

        def reused_approval(proposal_hash: str) -> HumanApproval:
            nonlocal issued
            if issued is None:
                issued = approve(proposal_hash)
            return issued

        self.assertEqual(
            supervisor.run(portfolio(), Mandate(), reused_approval).status,
            "APPROVED",
        )
        self.assertEqual(
            supervisor.run(portfolio(), Mandate(), reused_approval).status,
            "BLOCKED",
        )

    def test_risk_breach_blocks_even_with_human_approval(self) -> None:
        result = CommitteeSupervisor().run(
            portfolio(), Mandate(max_sector_weight=.16), approve
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.final.weights, result.initial.weights)

    def test_weights_remain_balanced(self) -> None:
        result = CommitteeSupervisor().run(portfolio(), Mandate(), approve)
        self.assertEqual(round(sum(result.final.weights.values()), 6), 1.0)


class BlackboardContractTests(unittest.TestCase):
    def message(self, **changes: object) -> Message:
        values = {
            "sender": "macro",
            "recipients": ("portfolio_manager",),
            "message_type": MessageType.OBSERVATION,
            "subject": "Scenario",
            "payload": {"value": 1},
            "correlation_id": "run-1",
        }
        values.update(changes)
        return Message(**values)  # type: ignore[arg-type]

    def test_rejects_malformed_or_unauthorized_messages(self) -> None:
        board = Blackboard()
        with self.assertRaisesRegex(ValueError, "correlation_id"):
            board.publish(self.message(correlation_id=""))
        with self.assertRaisesRegex(ValueError, "unknown sender"):
            board.publish(self.message(sender="intruder"))
        with self.assertRaisesRegex(ValueError, "unknown recipients"):
            board.publish(self.message(recipients=("brokerage",)))
        with self.assertRaisesRegex(ValueError, "cannot publish decision"):
            board.publish(self.message(message_type=MessageType.DECISION))

    def test_routes_only_to_declared_recipient_inboxes(self) -> None:
        board = Blackboard()
        message = self.message(recipients=("portfolio_manager", "risk"))
        board.publish(message)
        self.assertEqual(board.for_recipient("portfolio_manager"), [message])
        self.assertEqual(board.for_recipient("risk"), [message])
        self.assertEqual(board.for_recipient("compliance"), [])

    def test_audit_persists_across_blackboard_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "audit.jsonl"
            Blackboard(audit).publish(self.message(correlation_id="run-1"))
            Blackboard(audit).publish(self.message(correlation_id="run-2"))
            self.assertEqual(audit.read_text().count("\n"), 2)


if __name__ == "__main__":
    unittest.main()
