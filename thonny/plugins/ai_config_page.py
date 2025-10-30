from tkinter import ttk, messagebox, simpledialog
import tkinter as tk
from typing import List
from logging import getLogger

from thonny import get_workbench
from thonny.config_ui import ConfigurationPage, add_option_entry, add_vertical_separator
from thonny.languages import tr
from thonny.plugins.ai_models import (
    AIModel, 
    get_default_models_json, 
    parse_models_from_json,
    get_provider_display_name
)

logger = getLogger(__name__)


class AIConfigPage(ConfigurationPage):
    def __init__(self, master):
        super().__init__(master)
        
        self.columnconfigure(1, weight=1)
        
        # Track if any keys were modified
        self._keys_modified = False
        
        # ==================== API KEYS SECTION ====================
        keys_label = ttk.Label(self, text=tr("API Keys"), font="TkDefaultFont 12 bold")
        keys_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        
        # Gemini settings
        self._add_section_label("Gemini", row=1)
        
        self.gemini_key_entry = self._add_secret_entry(
            "Gemini.api_key",
            tr("API Key:"),
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
        
        add_vertical_separator(self, row=6)
        
        # GPT settings
        self._add_section_label("GPT (OpenAI)", row=7)
        
        self.gpt_key_entry = self._add_secret_entry(
            "OpenAI.api_key",
            tr("API Key:"),
            row=8
        )
        
        add_vertical_separator(self, row=9)
        
        # ==================== MODELS SECTION ====================
        models_label = ttk.Label(self, text=tr("AI Models"), font="TkDefaultFont 12 bold")
        models_label.grid(row=10, column=0, columnspan=2, sticky="w", pady=(10, 5))
        
        # Models list with Treeview
        models_frame = ttk.Frame(self)
        models_frame.grid(row=11, column=0, columnspan=2, sticky="nsew", pady=(5, 5))
        models_frame.columnconfigure(0, weight=1)
        models_frame.rowconfigure(0, weight=1)
        
        # Treeview with columns
        self.models_tree = ttk.Treeview(
            models_frame,
            columns=("provider", "api_name"),
            show="tree headings",
            height=8,
            selectmode="browse"
        )
        self.models_tree.heading("#0", text=tr("Display Name"))
        self.models_tree.heading("provider", text=tr("Provider"))
        self.models_tree.heading("api_name", text=tr("API Name"))
        
        self.models_tree.column("#0", width=200, minwidth=150)
        self.models_tree.column("provider", width=100, minwidth=80)
        self.models_tree.column("api_name", width=200, minwidth=150)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(models_frame, orient="vertical", command=self.models_tree.yview)
        self.models_tree.configure(yscrollcommand=scrollbar.set)
        
        self.models_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        # Buttons frame
        buttons_frame = ttk.Frame(self)
        buttons_frame.grid(row=12, column=0, columnspan=2, sticky="w", pady=(5, 0))
        
        ttk.Button(buttons_frame, text=tr("Add Model"), command=self._add_model).pack(side="left", padx=(0, 5))
        ttk.Button(buttons_frame, text=tr("Edit Model"), command=self._edit_model).pack(side="left", padx=(0, 5))
        ttk.Button(buttons_frame, text=tr("Delete Model"), command=self._delete_model).pack(side="left", padx=(0, 5))
        
        # Load models
        self._load_models()
        
        # Make the page expandable
        self.rowconfigure(11, weight=1)
    
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
        
        # Mark as modified when text changes
        def on_key_change(e):
            self._keys_modified = True
            import time
            get_workbench().set_option("ai._dummy_trigger", str(time.time()))
        
        entry.bind("<KeyRelease>", on_key_change)
        
        return entry
    
    def _load_models(self):
        """Load models from options and populate treeview"""
        models_json = get_workbench().get_option("ai.models_json")
        models = parse_models_from_json(models_json)
        
        # Clear existing items
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)
        
        # Add models to tree (without star - default is just for initial selection)
        for model in models:
            self.models_tree.insert(
                "",
                "end",
                text=model.ui_name,
                values=(get_provider_display_name(model.provider), model.api_name)
            )
    
    def _get_models_from_tree(self) -> List[AIModel]:
        """Extract models from treeview"""
        models = []
        for item in self.models_tree.get_children():
            display_name = self.models_tree.item(item, "text").strip()
            
            values = self.models_tree.item(item, "values")
            provider_display = values[0]
            api_name = values[1]
            
            # Map display name back to internal provider name
            provider = provider_display.lower()
            
            models.append(AIModel(
                ui_name=display_name,
                provider=provider,
                api_name=api_name
            ))
        return models
    
    def _add_model(self):
        """Add a new model"""
        dialog = ModelEditDialog(self, None)
        if dialog.result:
            model = dialog.result
            
            # Check if model with same name already exists
            for item in self.models_tree.get_children():
                existing_name = self.models_tree.item(item, "text").replace("⭐ ", "").strip()
                if existing_name == model.ui_name:
                    messagebox.showerror(
                        tr("Error"),
                        tr("Model with this name already exists")
                    )
                    return
            
            # Add to tree
            self.models_tree.insert(
                "",
                "end",
                text=model.ui_name,
                values=(get_provider_display_name(model.provider), model.api_name)
            )
            
            # Save immediately
            self._save_models()
    
    def _edit_model(self):
        """Edit selected model"""
        selection = self.models_tree.selection()
        if not selection:
            messagebox.showinfo(tr("Info"), tr("Please select a model to edit"))
            return
        
        item = selection[0]
        display_name = self.models_tree.item(item, "text").strip()
        values = self.models_tree.item(item, "values")
        provider_display = values[0]
        api_name = values[1]
        
        provider = provider_display.lower()
        
        current_model = AIModel(
            ui_name=display_name,
            provider=provider,
            api_name=api_name
        )
        
        dialog = ModelEditDialog(self, current_model)
        if dialog.result:
            model = dialog.result
            
            # Update tree item
            self.models_tree.item(
                item,
                text=model.ui_name,
                values=(get_provider_display_name(model.provider), model.api_name)
            )
            
            # Save immediately
            self._save_models()
    
    def _delete_model(self):
        """Delete selected model"""
        selection = self.models_tree.selection()
        if not selection:
            messagebox.showinfo(tr("Info"), tr("Please select a model to delete"))
            return
        
        item = selection[0]
        display_name = self.models_tree.item(item, "text").strip()
        
        if messagebox.askyesno(
            tr("Confirm Delete"),
            tr(f"Delete model '{display_name}'?")
        ):
            self.models_tree.delete(item)
            self._save_models()
    
    def _save_models(self):
        """Save models to options"""
        models = self._get_models_from_tree()
        models_json = "[" + ",\n".join([
            f'{{"ui_name": "{m.ui_name}", "provider": "{m.provider}", "api_name": "{m.api_name}"}}'
            for m in models
        ]) + "]"
        get_workbench().set_option("ai.models_json", models_json)
    
    def apply(self, changed_options: List[str]) -> bool:
        """Save API keys as secrets"""
        # Save API keys
        gemini_key = self.gemini_key_entry.get().strip()
        if gemini_key:
            get_workbench().set_secret(self.gemini_key_entry.secret_key, gemini_key)
        
        claude_key = self.claude_key_entry.get().strip()
        if claude_key:
            get_workbench().set_secret(self.claude_key_entry.secret_key, claude_key)
        
        gpt_key = self.gpt_key_entry.get().strip()
        if gpt_key:
            get_workbench().set_secret(self.gpt_key_entry.secret_key, gpt_key)
        
        # Save models (already saved on each edit, but ensure it's persisted)
        self._save_models()
        
        return True


class ModelEditDialog(simpledialog.Dialog):
    """Dialog for adding/editing AI model"""
    
    def __init__(self, parent, model: AIModel = None):
        self.model = model  # None for new model
        self.result = None
        super().__init__(parent, title=tr("Edit Model") if model else tr("Add Model"))
    
    def buttonbox(self):
        """Create button box with Thonny-styled ttk buttons"""
        from thonny.ui_utils import lookup_style_option
        
        # Create frame for buttons
        box = ttk.Frame(self)
        
        # Create OK and Cancel buttons using ttk
        ok_button = ttk.Button(box, text="OK", width=10, command=self.ok, default=tk.ACTIVE)
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text="Cancel", width=10, command=self.cancel)
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # Bind Enter and Escape
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        
        box.pack()
        
        # Apply background to dialog window
        bg = lookup_style_option("TFrame", "background")
        if bg:
            try:
                self.configure(background=bg)
            except:
                pass
    
    def body(self, master):
        """Create dialog body"""
        from thonny.ui_utils import lookup_style_option
        
        # Set Thonny-consistent background for body frame
        bg = lookup_style_option("TFrame", "background")
        if bg:
            master.configure(background=bg)
        
        ttk.Label(master, text=tr("Display Name:")).grid(row=0, column=0, sticky="w", pady=5, padx=5)
        self.name_entry = ttk.Entry(master, width=30)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        
        ttk.Label(master, text=tr("Provider:")).grid(row=1, column=0, sticky="w", pady=5, padx=5)
        self.provider_combo = ttk.Combobox(
            master,
            values=["Gemini", "GPT", "Claude"],
            state="readonly",
            width=28
        )
        self.provider_combo.grid(row=1, column=1, sticky="ew", pady=5, padx=5)
        
        ttk.Label(master, text=tr("API Name:")).grid(row=2, column=0, sticky="w", pady=5, padx=5)
        self.api_entry = ttk.Entry(master, width=30)
        self.api_entry.grid(row=2, column=1, sticky="ew", pady=5, padx=5)
        
        # Populate if editing
        if self.model:
            self.name_entry.insert(0, self.model.ui_name)
            self.provider_combo.set(get_provider_display_name(self.model.provider))
            self.api_entry.insert(0, self.model.api_name)
        else:
            # Default to Gemini for new models
            self.provider_combo.set("Gemini")
        
        master.columnconfigure(1, weight=1)
        return self.name_entry  # Focus on name entry
    
    def validate(self):
        """Validate input"""
        if not self.name_entry.get().strip():
            messagebox.showerror(tr("Error"), tr("Display name cannot be empty"))
            return False
        
        if not self.api_entry.get().strip():
            messagebox.showerror(tr("Error"), tr("API name cannot be empty"))
            return False
        
        return True
    
    def apply(self):
        """Create result model"""
        provider_display = self.provider_combo.get()
        provider = provider_display.lower()
        
        self.result = AIModel(
            ui_name=self.name_entry.get().strip(),
            provider=provider,
            api_name=self.api_entry.get().strip()
        )


def load_plugin():
    # Register default models JSON
    get_workbench().set_default("ai.models_json", get_default_models_json())
    
    # Dummy option to trigger apply() when only secrets change
    get_workbench().set_default("ai._dummy_trigger", "")
    
    get_workbench().add_configuration_page("ai", tr("AI Models"), AIConfigPage, 81)
