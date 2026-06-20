from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .agents import ComplianceAgent, MacroAgent, PortfolioManagerAgent, RiskAgent, SectorAgent
from .blackboard import Blackboard
from .models import HumanApproval, Mandate, Message, MessageType, Portfolio, Severity


ApprovalProvider = Callable[[str], HumanApproval | None]


@dataclass
class RunResult:
    status: str
    initial: Portfolio
    proposed: Portfolio
    final: Portfolio
    correlation_id: str
    message_count: int


class CommitteeSupervisor:
    """Orchestrates stages but cannot bypass code-enforced veto and approval gates."""

    def __init__(self, audit_path: Path | None = None) -> None:
        self.board = Blackboard(audit_path)
        self.macro = MacroAgent()
        self.sector = SectorAgent()
        self.risk = RiskAgent()
        self.compliance = ComplianceAgent()
        self.pm = PortfolioManagerAgent()
        self._used_approval_ids: set[str] = set()

    def _approval_is_fresh(self, approval: HumanApproval) -> bool:
        try:
            timestamp = datetime.fromisoformat(approval.timestamp)
        except (TypeError, ValueError):
            return False
        if timestamp.tzinfo is None:
            return False
        age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
        return timedelta(0) <= age <= timedelta(minutes=15)

    def run(
        self,
        initial: Portfolio,
        mandate: Mandate,
        approval_provider: ApprovalProvider | None = None,
    ) -> RunResult:
        cid = str(uuid4())
        macro = self.macro.assess(cid)
        recommendation = self.sector.recommend(cid)
        self.board.publish(macro)
        self.board.publish(recommendation)

        trades = self.pm.parse_trades(recommendation)
        proposed = initial.apply(trades)
        risk = self.risk.review(initial, trades, mandate, cid)
        compliance = self.compliance.review(trades, mandate, cid)
        self.board.publish(risk)
        self.board.publish(compliance)

        if compliance.message_type is MessageType.VETO:
            trades = self.pm.revise_after_veto(trades, compliance)
            self.board.publish(Message(
                sender="portfolio_manager", recipients=("risk", "compliance", "supervisor"),
                message_type=MessageType.RECOMMENDATION, subject="Revised trade list after veto",
                payload={"trades": [t.__dict__ for t in trades]}, correlation_id=cid,
            ))
            risk = self.risk.review(initial, trades, mandate, cid)
            compliance = self.compliance.review(trades, mandate, cid)
            self.board.publish(risk)
            self.board.publish(compliance)

        unresolved = risk.payload["breaches"] or compliance.message_type is MessageType.VETO
        turnover = risk.payload["gross_turnover"]
        needs_human = turnover >= mandate.human_approval_threshold
        controlled_proposal = initial.apply(trades)
        proposal_hash = controlled_proposal.proposal_hash()
        approval = approval_provider(proposal_hash) if needs_human and approval_provider else None
        valid_approval = bool(
            approval
            and approval.approved
            and approval.proposal_hash == proposal_hash
            and approval.approver.strip()
            and self._approval_is_fresh(approval)
            and approval.id not in self._used_approval_ids
        )
        if approval:
            approval_fresh = self._approval_is_fresh(approval)
            approval_replayed = approval.id in self._used_approval_ids
            self.board.publish(Message(
                sender="human_chair", recipients=("supervisor", "audit"),
                message_type=MessageType.APPROVAL, subject="Human approval response",
                payload={
                    "approval_id": approval.id,
                    "approver": approval.approver,
                    "approved": approval.approved,
                    "proposal_hash": approval.proposal_hash,
                    "rationale": approval.rationale,
                    "approval_timestamp": approval.timestamp,
                    "hash_matches": approval.proposal_hash == proposal_hash,
                    "fresh": approval_fresh,
                    "replayed": approval_replayed,
                },
                severity=Severity.INFO if valid_approval else Severity.CRITICAL,
                correlation_id=cid,
            ))
            self._used_approval_ids.add(approval.id)

        if unresolved or (needs_human and not valid_approval):
            if unresolved:
                reason = "unresolved_control_breach"
            elif approval:
                reason = "invalid_or_rejected_human_approval"
            else:
                reason = "human_approval_required"
            self.board.publish(Message(
                sender="supervisor", recipients=("human_chair",),
                message_type=MessageType.ESCALATION, subject="Decision blocked",
                payload={"reason": reason, "rollback": "initial_portfolio"},
                severity=Severity.CRITICAL, correlation_id=cid,
            ))
            return RunResult("BLOCKED", initial, proposed, initial, cid, len(self.board.by_correlation(cid)))

        final = controlled_proposal
        self.board.publish(Message(
            sender="supervisor", recipients=("human_chair", "audit"),
            message_type=MessageType.DECISION, subject="Rebalance approved",
            payload={
                "human_approved": valid_approval if needs_human else None,
                "approval_id": approval.id if approval else None,
                "proposal_hash": proposal_hash,
                "final_weights": final.weights,
            },
            correlation_id=cid,
        ))
        return RunResult("APPROVED", initial, proposed, final, cid, len(self.board.by_correlation(cid)))
