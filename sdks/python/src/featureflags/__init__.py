"""Feature flag Python SDK.

from featureflags import FlagClient

client = FlagClient("srv-...", base_url="https://flags.example.com")
if client.bool("new-checkout", {"id": "user-1", "country": "CA"}, default=False):
    ...
"""

from .client import EvaluationDetail, FlagClient
from .evaluation import EvaluationResult, evaluate

__version__ = "0.1.0"
__all__ = ["FlagClient", "EvaluationDetail", "EvaluationResult", "evaluate", "__version__"]
