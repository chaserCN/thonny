"""
AI Models configuration and management.

Provides default models and utilities for managing AI model list.
"""
from typing import List, Dict, Any
from dataclasses import dataclass, asdict
import json


@dataclass
class AIModel:
    """Represents an AI model configuration"""
    ui_name: str        # Display name in UI (e.g., "Gemini 2.5 Pro")
    provider: str       # Provider type: "gemini", "gpt", "claude"
    api_name: str       # Model name for API (e.g., "gemini-2.5-pro")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AIModel':
        """Create from dictionary (ignore unknown fields for backward compatibility)"""
        # Filter only known fields
        valid_fields = {'ui_name', 'provider', 'api_name'}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


# Default models shipped with Thonny
# First model in list is used as default on first install
DEFAULT_MODELS = [
    AIModel(
        ui_name="Gemini 2.5 Pro",
        provider="gemini",
        api_name="gemini-2.5-pro"
    ),
    AIModel(
        ui_name="Gemini 2.5 Flash",
        provider="gemini",
        api_name="gemini-2.5-flash"
    ),
    AIModel(
        ui_name="Gemini 2.5 Flash Lite",
        provider="gemini",
        api_name="gemini-2.5-flash-lite"
    ),
    AIModel(
        ui_name="GPT-5",
        provider="gpt",
        api_name="gpt-5"
    ),
    AIModel(
        ui_name="GPT-5 Codex",
        provider="gpt",
        api_name="gpt-5-codex"
    ),
    AIModel(
        ui_name="Claude Sonnet 4.5",
        provider="claude",
        api_name="claude-sonnet-4-5"
    ),
    AIModel(
        ui_name="Claude Haiku 4.5",
        provider="claude",
        api_name="claude-haiku-4-5"
    ),
]


def get_default_models_json() -> str:
    """Get default models as JSON string"""
    return json.dumps([model.to_dict() for model in DEFAULT_MODELS], indent=2)


def parse_models_from_json(json_str: str) -> List[AIModel]:
    """Parse models from JSON string"""
    try:
        data = json.loads(json_str)
        return [AIModel.from_dict(item) for item in data]
    except Exception:
        # Fallback to default models if parsing fails
        return DEFAULT_MODELS.copy()


def get_default_model() -> AIModel:
    """Get the default model (first in list)"""
    return DEFAULT_MODELS[0]


def get_provider_display_name(provider: str) -> str:
    """Get display name for provider"""
    return {
        "gemini": "Gemini",
        "gpt": "GPT",
        "claude": "Claude"
    }.get(provider, provider.title())

