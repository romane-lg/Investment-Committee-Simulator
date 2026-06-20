from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class MessageType(str, Enum):
    OBSERVATION = "observation"
    RECOMMENDATION = "recommendation"
    CHALLENGE = "challenge"
    VETO = "veto"
    ESCALATION = "escalation"
    DECISION = "decision"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Message:
    sender: str
    recipients: tuple[str, ...]
    message_type: MessageType
    subject: str
    payload: dict[str, Any]
    evidence: tuple[str, ...] = ()
    severity: Severity = Severity.INFO
    correlation_id: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["message_type"] = self.message_type.value
        result["severity"] = self.severity.value
        return result


@dataclass(frozen=True)
class Trade:
    asset: str
    delta_weight: float
    sector: str


@dataclass
class Portfolio:
    weights: dict[str, float]
    sectors: dict[str, str]

    def apply(self, trades: list[Trade]) -> "Portfolio":
        weights = self.weights.copy()
        sectors = self.sectors.copy()
        for trade in trades:
            weights[trade.asset] = round(weights.get(trade.asset, 0) + trade.delta_weight, 6)
            sectors[trade.asset] = trade.sector
        weights = {asset: weight for asset, weight in weights.items() if weight > 0.000001}
        return Portfolio(weights, sectors)

    def sector_weights(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for asset, weight in self.weights.items():
            sector = self.sectors[asset]
            totals[sector] = round(totals.get(sector, 0) + weight, 6)
        return totals


@dataclass(frozen=True)
class Mandate:
    max_asset_weight: float = 0.30
    max_sector_weight: float = 0.35
    min_cash_weight: float = 0.05
    restricted_assets: tuple[str, ...] = ("SANCTIONED_OIL",)
    human_approval_threshold: float = 0.10
