"""Intent system for network goals.

Allows users to express goals like:
- "Zoom calls should never lag"
- "Alert me if my ISP is the problem"
- "Gaming traffic is more important than streaming"
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Intent:
    """A network goal expressed in structured form."""
    id: str
    name: str
    target: str  # "zoom.us", "gaming", "all"
    metric: str  # "latency", "loss", "availability", "baseline_deviation"
    threshold: float
    comparison: str  # "<", ">", "=="
    priority: int  # 1-10
    actions: list[str]  # ["alert", "diagnose", "record"]
    enabled: bool = True


class IntentParser:
    """Convert natural language to structured intents."""

    # Common patterns for parsing
    LATENCY_KEYWORDS = ["lag", "slow", "latency", "ping", "delay"]
    LOSS_KEYWORDS = ["packet loss", "drops", "dropping", "unstable"]
    ALERT_KEYWORDS = ["alert", "notify", "tell me", "let me know"]

    # Target mappings
    TARGET_MAPPINGS = {
        "zoom": "zoom.us",
        "meet": "meet.google.com",
        "teams": "teams.microsoft.com",
        "gaming": "gaming",
        "video": "video",
        "streaming": "streaming",
    }

    async def parse(self, natural_language: str, intent_id: Optional[str] = None) -> Intent:
        """
        Convert natural language to structured intent.

        Examples:
        - "Zoom calls should never lag"
          → Intent(target="zoom.us", metric="latency", threshold=100, comparison="<")

        - "Alert me if gaming latency exceeds 50ms"
          → Intent(target="gaming", metric="latency", threshold=50, actions=["alert"])

        - "My connection should stay close to baseline"
          → Intent(target="all", metric="baseline_deviation", threshold=2.0)

        Args:
            natural_language: User's goal in plain English
            intent_id: Optional ID for this intent

        Returns:
            Structured Intent
        """
        import hashlib

        text = natural_language.lower()

        # Generate ID if not provided
        if intent_id is None:
            intent_id = hashlib.md5(natural_language.encode()).hexdigest()[:8]

        # Determine target
        target = "all"
        for keyword, mapped_target in self.TARGET_MAPPINGS.items():
            if keyword in text:
                target = mapped_target
                break

        # Determine metric
        metric = "latency"  # default
        if any(kw in text for kw in self.LOSS_KEYWORDS):
            metric = "loss"
        elif "baseline" in text or "normal" in text:
            metric = "baseline_deviation"

        # Determine threshold
        threshold = self._extract_threshold(text, metric)

        # Determine comparison
        comparison = "<"  # default (lower is better for latency/loss)
        if "exceed" in text or "over" in text or "above" in text:
            comparison = ">"

        # Determine actions
        actions = ["diagnose"]  # always diagnose
        if any(kw in text for kw in self.ALERT_KEYWORDS):
            actions.append("alert")

        # Determine priority (1-10, default 5)
        priority = 5
        if "important" in text or "critical" in text:
            priority = 8
        elif "nice to have" in text or "low priority" in text:
            priority = 3

        return Intent(
            id=intent_id,
            name=natural_language[:50],  # truncate for display
            target=target,
            metric=metric,
            threshold=threshold,
            comparison=comparison,
            priority=priority,
            actions=actions,
        )

    def _extract_threshold(self, text: str, metric: str) -> float:
        """Extract numeric threshold from text."""
        import re

        # Look for patterns like "50ms", "100 ms", "5%"
        patterns = [
            r'(\d+)\s*ms',  # milliseconds
            r'(\d+)\s*%',   # percentage
            r'(\d+)\s*seconds',
            r'under\s+(\d+)',
            r'below\s+(\d+)',
            r'exceeds?\s+(\d+)',
            r'over\s+(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))

        # Default thresholds based on metric
        defaults = {
            "latency": 100.0,  # 100ms
            "loss": 1.0,       # 1%
            "baseline_deviation": 2.0,  # 2x from baseline
        }

        return defaults.get(metric, 100.0)
