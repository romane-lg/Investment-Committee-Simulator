from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .agents import ComplianceAgent, MacroAgent, PortfolioManagerAgent, RiskAgent, SectorAgent
from .blackboard import Blackboard
from .models import Mandate, Message, MessageType, Portfolio, Severity


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

    def run(self, initial: Portfolio, mandate: Mandate, human_approved: bool) -> RunResult:
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
        if unresolved or (needs_human and not human_approved):
            reason = "unresolved_control_breach" if unresolved else "human_approval_required"
            self.board.publish(Message(
                sender="supervisor", recipients=("human_chair",),
                message_type=MessageType.ESCALATION, subject="Decision blocked",
                payload={"reason": reason, "rollback": "initial_portfolio"},
                severity=Severity.CRITICAL, correlation_id=cid,
            ))
            return RunResult("BLOCKED", initial, proposed, initial, cid, len(self.board.messages))

        final = initial.apply(trades)
        self.board.publish(Message(
            sender="supervisor", recipients=("human_chair", "audit"),
            message_type=MessageType.DECISION, subject="Rebalance approved",
            payload={"human_approved": human_approved, "final_weights": final.weights},
            correlation_id=cid,
        ))
        return RunResult("APPROVED", initial, proposed, final, cid, len(self.board.messages))

