"""iMessage (Linq) -> MiniLM intent -> CuBot V2 fold paths."""
from .bridge import Bridge, Outcome
from .config import Settings
from .intent import Classifier, IntentResult, IntentUnavailable
from .linq import InboundMessage, LinqClient, LinqError, parse_inbound
from .robot import FoldPlan, Move, ShapeLibrary, build_executor
from .vocab import Resolution, Vocabulary, label_to_icon

__version__ = "1.0.0"
__all__ = [
    "Bridge", "Outcome", "Settings", "Classifier", "IntentResult", "IntentUnavailable",
    "InboundMessage", "LinqClient", "LinqError", "parse_inbound", "FoldPlan", "Move",
    "ShapeLibrary", "build_executor", "Resolution", "Vocabulary", "label_to_icon",
]
