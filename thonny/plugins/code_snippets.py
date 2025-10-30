"""Code snippets plugin for Thonny"""
import tkinter as tk
from tkinter import ttk
from typing import List, Dict
from logging import getLogger

from thonny import get_workbench
from thonny.config_ui import ConfigurationPage
from thonny.languages import tr

logger = getLogger(__name__)


class SnippetEditDialog(tk.Toplevel):
    def __init__(self, master, name="", code=""):
        super().__init__(master)
        self.title(tr("Edit Snippet"))
        self.transient(master)
        self.grab_set()
        
        self.result = None
        
        main_frame = ttk.Frame(self, padding=15)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Name field
        ttk.Label(main_frame, text=tr("Name:")).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.name_entry = ttk.Entry(main_frame, width=40)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 5))
        self.name_entry.insert(0, name)
        
        # Code field
        ttk.Label(main_frame, text=tr("Code:")).grid(row=1, column=0, sticky="nw", pady=(5, 0))
        
        code_frame = ttk.Frame(main_frame)
        code_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(5, 10))
        code_frame.columnconfigure(0, weight=1)
        code_frame.rowconfigure(0, weight=1)
        
        self.code_text = tk.Text(code_frame, width=60, height=15, wrap=tk.NONE, insertbackground="black")
        self.code_text.grid(row=0, column=0, sticky="nsew")
        
        scrollbar_y = ttk.Scrollbar(code_frame, command=self.code_text.yview)
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        self.code_text.config(yscrollcommand=scrollbar_y.set)
        
        scrollbar_x = ttk.Scrollbar(code_frame, orient=tk.HORIZONTAL, command=self.code_text.xview)
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        self.code_text.config(xscrollcommand=scrollbar_x.set)
        
        self.code_text.insert("1.0", code)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="e")
        
        ttk.Button(button_frame, text=tr("OK"), command=self._ok).grid(row=0, column=0, padx=(0, 5))
        ttk.Button(button_frame, text=tr("Cancel"), command=self._cancel).grid(row=0, column=1)
        
        self.bind("<Escape>", lambda e: self._cancel())
        
        # Set focus to appropriate field
        if not name:
            self.name_entry.focus_set()
        else:
            self.code_text.focus_set()
            # Place cursor at end of code
            self.code_text.mark_set("insert", "end")
        
        # Center dialog
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'+{x}+{y}')
    
    def _ok(self):
        name = self.name_entry.get().strip()
        code = self.code_text.get("1.0", "end").strip()
        
        if not name:
            from tkinter import messagebox
            messagebox.showwarning(tr("Invalid Input"), tr("Name cannot be empty"))
            return
        
        self.result = (name, code)
        self.destroy()
    
    def _cancel(self):
        self.destroy()


class CodeSnippetsConfigPage(ConfigurationPage):
    def __init__(self, master):
        super().__init__(master)
        
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        
        # Title
        title_label = ttk.Label(self, text=tr("Code Snippets"), font="TkDefaultFont 10 bold")
        title_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        
        # Tree view for snippets
        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.tree = ttk.Treeview(tree_frame, columns=("name", "code"), show="headings", height=15)
        self.tree.heading("name", text=tr("Name"))
        self.tree.heading("code", text=tr("Code Preview"))
        self.tree.column("name", width=150)
        self.tree.column("code", width=350)
        self.tree.grid(row=0, column=0, sticky="nsew")
        
        scrollbar = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.config(yscrollcommand=scrollbar.set)
        
        # Double-click to edit
        self.tree.bind("<Double-Button-1>", lambda e: self._edit_snippet())
        
        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.grid(row=1, column=1, sticky="n")
        
        ttk.Button(button_frame, text=tr("Add"), command=self._add_snippet, width=12).grid(row=0, column=0, pady=(0, 5))
        ttk.Button(button_frame, text=tr("Edit"), command=self._edit_snippet, width=12).grid(row=1, column=0, pady=(0, 5))
        ttk.Button(button_frame, text=tr("Remove"), command=self._remove_snippet, width=12).grid(row=2, column=0, pady=(0, 5))
        ttk.Button(button_frame, text=tr("Reset"), command=self._reset_snippets, width=12).grid(row=3, column=0)
        
        # Store snippets data
        self.snippets_data = {}  # {tree_id: (name, code)}
        
        # Load existing snippets
        self._load_snippets()
    
    def _load_snippets(self):
        """Load snippets from config"""
        snippets_list = get_workbench().get_option("snippets.items", [])
        
        for snippet_str in snippets_list:
            name, code = _parse_snippet(snippet_str)
            if name and code:
                # Show only first line of code in preview
                code_preview = code.split("\n")[0]
                if len(code_preview) > 50:
                    code_preview = code_preview[:47] + "..."
                
                item_id = self.tree.insert("", "end", values=(name, code_preview))
                self.snippets_data[item_id] = (name, code)
    
    def _add_snippet(self):
        """Add new snippet"""
        dlg = SnippetEditDialog(self)
        self.wait_window(dlg)
        
        if dlg.result:
            name, code = dlg.result
            code_preview = code.split("\n")[0]
            if len(code_preview) > 50:
                code_preview = code_preview[:47] + "..."
            
            item_id = self.tree.insert("", "end", values=(name, code_preview))
            self.snippets_data[item_id] = (name, code)
            
            # Mark as changed to trigger apply()
            import time
            get_workbench().set_option("snippets._dummy_trigger", str(time.time()))
            
    
    def _edit_snippet(self):
        """Edit selected snippet"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        name, code = self.snippets_data[item_id]
        
        dlg = SnippetEditDialog(self, name, code)
        self.wait_window(dlg)
        
        if dlg.result:
            name, code = dlg.result
            code_preview = code.split("\n")[0]
            if len(code_preview) > 50:
                code_preview = code_preview[:47] + "..."
            
            self.tree.item(item_id, values=(name, code_preview))
            self.snippets_data[item_id] = (name, code)
            
            # Mark as changed to trigger apply()
            import time
            get_workbench().set_option("snippets._dummy_trigger", str(time.time()))
    
    def _remove_snippet(self):
        """Remove selected snippet"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        self.tree.delete(item_id)
        del self.snippets_data[item_id]
        
        # Mark as changed to trigger apply()
        import time
        get_workbench().set_option("snippets._dummy_trigger", str(time.time()))
    
    def _reset_snippets(self):
        """Reset snippets to default values"""
        from tkinter import messagebox
        
        if messagebox.askyesno(
            tr("Reset Snippets"),
            tr("Reset all snippets to default values?"),
            master=self
        ):
            # Clear current snippets
            for item_id in self.tree.get_children():
                self.tree.delete(item_id)
            self.snippets_data.clear()
            
            # Load default snippets
            default_snippets = [
                "input ryad:ryad=input(\"ryad=\")\\n",
                "input n:n=int(input(\"n=\"))\\n",
                "input mas:mas=list(map(int, input(\"mas=\").split()))\\n",
            ]
            
            for snippet_str in default_snippets:
                if ":" in snippet_str:
                    name, code = snippet_str.split(":", 1)
                    # Decode newlines and tabs
                    code = code.replace("\\n", "\n").replace("\\t", "\t")
                    
                    # Add to tree
                    code_preview = code.replace("\n", " ")[:50]
                    item_id = self.tree.insert("", "end", values=(name, code_preview))
                    self.snippets_data[item_id] = (name, code)
            
            # Mark as changed to trigger apply()
            import time
            get_workbench().set_option("snippets._dummy_trigger", str(time.time()))
    
    def apply(self, changed_options: List[str]) -> bool:
        """Save snippets to config"""
        snippets_list = []
        
        # Collect all snippets from tree
        for item_id in self.tree.get_children():
            if item_id in self.snippets_data:
                name, code = self.snippets_data[item_id]
                # Encode newlines and tabs for storage
                code_encoded = code.replace("\n", "\\n").replace("\t", "\\t")
                snippet_str = f"{name}:{code_encoded}"
                snippets_list.append(snippet_str)
            else:
                logger.warning(f"Item {item_id} not found in snippets_data")
        
        get_workbench().set_option("snippets.items", snippets_list)
        
        # Verify save
        saved = get_workbench().get_option("snippets.items", [])
        
        # Trigger dummy option change to ensure apply() is called next time
        import time
        get_workbench().set_option("snippets._dummy_trigger", str(time.time()))
        
        return True


def _parse_snippet(snippet_str: str) -> tuple:
    """Parse 'name:code' format into (name, code)"""
    if ":" not in snippet_str:
        return None, None
    
    parts = snippet_str.split(":", 1)
    name = parts[0].strip()
    code = parts[1].strip()
    
    # Replace \\n with actual newlines
    code = code.replace("\\n", "\n")
    code = code.replace("\\t", "\t")
    
    return name, code


def _insert_snippet(code: str):
    """Insert snippet code at cursor position in active editor"""
    editor = get_workbench().get_editor_notebook().get_current_editor()
    if not editor:
        return
    
    text_widget = editor.get_text_widget()
    
    # Get current cursor position
    cursor_pos = text_widget.index("insert")
    
    # Insert code
    text_widget.insert(cursor_pos, code)
    
    # Move cursor to end of inserted code
    lines = code.count("\n")
    if lines > 0:
        last_line_length = len(code.split("\n")[-1])
        new_pos = f"{cursor_pos} + {lines} lines + {last_line_length} chars"
    else:
        new_pos = f"{cursor_pos} + {len(code)} chars"
    
    text_widget.mark_set("insert", new_pos)
    text_widget.see("insert")
    text_widget.focus_set()


def _create_snippet_submenu():
    """Create submenu with all snippets"""
    snippets = get_workbench().get_option("snippets.items", [])
    
    submenu = tk.Menu(get_workbench(), tearoff=False)
    
    if not snippets:
        submenu.add_command(label=tr("(No snippets configured)"), state="disabled")
    else:
        for snippet_str in snippets:
            name, code = _parse_snippet(snippet_str)
            if name and code:
                submenu.add_command(
                    label=name,
                    command=lambda c=code: _insert_snippet(c)
                )
    
    return submenu


def _refresh_editor_menu():
    """Refresh the editor context menu with current snippets"""
    # This will be called when snippets are updated
    pass


def _populate_editor_menu(menu: tk.Menu):
    """Add snippets submenu to editor context menu"""
    menu.add_separator()
    submenu = _create_snippet_submenu()
    menu.add_cascade(label=tr("Insert snippet"), menu=submenu)


def load_plugin():
    # Register default snippets
    default_snippets = [
        "input ryad:ryad=input(\"ryad=\")\\n",
        "input n:n=int(input(\"n=\"))\\n",
        "input mas:mas=list(map(int, input(\"mas=\").split()))\\n",
    ]
    get_workbench().set_default("snippets.items", default_snippets)
    
    # Dummy option to trigger apply() when only snippets change
    get_workbench().set_default("snippets._dummy_trigger", "")
    
    # Add configuration page
    get_workbench().add_configuration_page(
        "snippets",
        tr("Code Snippets"),
        CodeSnippetsConfigPage,
        85
    )
    
    # Hook into editor context menu creation
    # We need to find where editor creates its context menu and add our items
    # For now, we'll add it via workbench event
    def on_editor_menu_populate(event):
        menu = event.menu
        _populate_editor_menu(menu)
    
    # Note: This might need adjustment depending on how Thonny's menu system works
    # For now, this is a template that shows the structure

