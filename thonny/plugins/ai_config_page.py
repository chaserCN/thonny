from tkinter import ttk
from typing import List
from logging import getLogger

from thonny import get_workbench
from thonny.config_ui import ConfigurationPage, add_option_entry, add_vertical_separator
from thonny.languages import tr

logger = getLogger(__name__)


class AIConfigPage(ConfigurationPage):
    def __init__(self, master):
        super().__init__(master)
        
        self.columnconfigure(1, weight=1)
        
        # Track if any keys were modified
        self._keys_modified = False
        
        # Gemini settings
        self._add_section_label("Gemini", row=0)
        
        self.gemini_key_entry = self._add_secret_entry(
            "Gemini.api_key",
            tr("API Key:"),
            row=1
        )
        
        add_option_entry(
            self,
            "ai.gemini_model",
            tr("Model name:"),
            width=30,
            row=2
        )
        
        add_vertical_separator(self, row=3)
        
        # Claude settings
        self._add_section_label("Claude", row=4)
        
        self.claude_key_entry = self._add_secret_entry(
            "Claude.api_key",
            tr("API Key:"),
            row=5
        )
        
        add_option_entry(
            self,
            "ai.claude_model",
            tr("Model name:"),
            width=30,
            row=6
        )
        
        add_vertical_separator(self, row=7)
        
        # GPT settings
        self._add_section_label("GPT (OpenAI)", row=8)
        
        self.gpt_key_entry = self._add_secret_entry(
            "OpenAI.api_key",
            tr("API Key:"),
            row=9
        )
        
        add_option_entry(
            self,
            "ai.gpt_model",
            tr("Model name:"),
            width=30,
            row=10
        )
    
    def _add_section_label(self, text: str, row: int):
        """Add a bold section label"""
        label = ttk.Label(self, text=text, font="TkDefaultFont 10 bold")
        label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
    
    def _add_secret_entry(self, secret_key: str, label_text: str, row: int):
        """Add an entry field for API key (secret) with masking"""
        label = ttk.Label(self, text=label_text)
        label.grid(row=row, column=0, sticky="w", pady=(5, 5), padx=(0, 10))
        
        # Create entry with masked display
        entry = ttk.Entry(self, width=40, show="*")
        entry.grid(row=row, column=1, sticky="w", pady=(5, 5))
        
        # Load current secret value
        current_secret = get_workbench().get_secret(secret_key)
        if current_secret:
            entry.insert(0, current_secret)
        
        # Store secret_key for later use in apply()
        entry.secret_key = secret_key
        
        # Mark as modified when text changes - set a dummy option to trigger apply()
        def on_key_change(e):
            self._keys_modified = True
            # Set a dummy option to make changed_options non-empty
            # This ensures apply() will be called
            import time
            get_workbench().set_option("ai._dummy_trigger", str(time.time()))
        
        entry.bind("<KeyRelease>", on_key_change)
        
        return entry
    
    def apply(self, changed_options: List[str]) -> bool:
        """Save API keys as secrets
        
        Note: This is called only if regular options changed.
        For secrets, we override to always save if modified.
        """
        logger.info(f"AIConfigPage.apply() called with changed_options={changed_options}, keys_modified={self._keys_modified}")
        
        # Always try to save secrets (they're not tracked as "options")
        # Save Gemini key
        gemini_key = self.gemini_key_entry.get().strip()
        logger.info(f"Gemini key from entry: length={len(gemini_key)}, value='{gemini_key[:10] if gemini_key else ''}'...")
        if gemini_key:
            get_workbench().set_secret(self.gemini_key_entry.secret_key, gemini_key)
            logger.info(f"Gemini API key saved to secrets")
        
        # Save Claude key
        claude_key = self.claude_key_entry.get().strip()
        logger.info(f"Claude key from entry: length={len(claude_key)}, value='{claude_key[:10] if claude_key else ''}'...")
        if claude_key:
            get_workbench().set_secret(self.claude_key_entry.secret_key, claude_key)
            logger.info(f"Claude API key saved to secrets")
        
        # Save GPT key
        gpt_key = self.gpt_key_entry.get().strip()
        logger.info(f"GPT key from entry: length={len(gpt_key)}, value='{gpt_key[:10] if gpt_key else ''}'...")
        if gpt_key:
            get_workbench().set_secret(self.gpt_key_entry.secret_key, gpt_key)
            logger.info(f"GPT API key saved to secrets")
        
        return True


def load_plugin():
    # Register model name defaults (taken from plugin files)
    get_workbench().set_default("ai.gemini_model", "gemini-2.5-pro")
    get_workbench().set_default("ai.claude_model", "claude-sonnet-4-5")
    get_workbench().set_default("ai.gpt_model", "gpt-5")
    
    # Dummy option to trigger apply() when only secrets change
    get_workbench().set_default("ai._dummy_trigger", "")
    
    get_workbench().add_configuration_page("ai", tr("AI Models"), AIConfigPage, 81)

