import ast
import dataclasses
import os.path
from abc import ABC, abstractmethod
from collections import namedtuple
from dataclasses import dataclass
from enum import Enum
from logging import getLogger
from typing import Dict, Iterator, List, Optional

from thonny import get_workbench
from thonny.common import read_source
from thonny.misc_utils import local_path_to_uri

logger = getLogger(__name__)

Suggestion = namedtuple("Suggestion", ["symbol", "title", "body", "relevance"])


class ChatRole(Enum):
    """Unified chat roles for different AI providers"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    
    def to_openai(self) -> str:
        """Convert to OpenAI API format"""
        return self.value
    
    def to_claude(self) -> str:
        """Convert to Claude API format (same as OpenAI)"""
        return self.value
    
    def to_gemini(self) -> str:
        """Convert to Gemini API format"""
        if self == ChatRole.ASSISTANT:
            return "model"
        elif self == ChatRole.SYSTEM:
            return "user"  # Gemini doesn't have system role
        return self.value
    
    @classmethod
    def from_string(cls, role_str: str) -> "ChatRole":
        """Create ChatRole from string, handling both formats"""
        role_lower = role_str.lower()
        if role_lower == "model":
            return cls.ASSISTANT
        for role in cls:
            if role.value == role_lower:
                return role
        raise ValueError(f"Unknown role: {role_str}")


@dataclass
class Attachment:
    description: str
    tag: Optional[str]
    content: str


@dataclass
class ChatMessage:
    role: ChatRole
    content: str
    attachments: List[Attachment]
    is_debug_related: bool = False
    debug_session_id: Optional[str] = None
    image: Optional[Dict] = None  # {'base64': str, 'format': str} for image support


@dataclass
class ChatResponseChunk:
    content: str
    is_final: bool
    is_interal_error: bool = False


@dataclass
class ChatResponseFragmentWithRequestId:
    fragment: ChatResponseChunk
    request_id: str


@dataclass
class ChatContext:
    messages: List[ChatMessage]  # History (previous messages)
    current_message: Optional[ChatMessage] = None  # New message (not yet in history)
    active_file_path: Optional[str] = None
    active_file_selection: Optional[str] = None
    program_context: Optional[str] = None  # Contains either debug context or formatted code
    
    def has_image_in_last_message(self) -> bool:
        """Check if the last user message contains an image"""
        # Check current message first, then history
        if self.current_message and self.current_message.role == ChatRole.USER:
            return self.current_message.image is not None
        if not self.messages:
            return False
        last_msg = self.messages[-1]
        return last_msg.role == ChatRole.USER and last_msg.image is not None


@dataclass
class CodeViewContext:
    """Context for line explanation requests from code view"""
    line_num: int
    line_content: str
    program_context: str  # Always contains either debug context or formatted code


@dataclass
class TokenContext:
    """Context for token explanation requests from code view"""
    line_num: int
    line_content: str
    token: str
    token_type: str
    token_description: str
    program_context: str  # Always contains either debug context or formatted code


@dataclass
class SelectionContext:
    """Context for selected code explanation requests from code view"""
    selected_code: str
    start_line: int
    end_line: int
    program_context: str  # Always contains either debug context or formatted code


class Assistant(ABC):
    @abstractmethod
    def get_ready(self) -> bool:
        """Called in the UI thread before each request"""
        ...

    @abstractmethod
    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Called in a background thread"""
        ...

    @abstractmethod
    def cancel_completion(self) -> None:
        """Called in the UI thread"""
        ...

    def format_message(self, message: ChatMessage) -> str:
        result = self.format_attachments(message.attachments)

        if result:
            result += "User message:\n"

        result += message.content

        return result

    def format_attachments(self, attachments: List[Attachment]) -> str:
        result = ""
        for attachment in attachments:
            result += self.format_attachment(attachment)
        return result

    def format_attachment(self, attachment: Attachment) -> str:
        result = f"{attachment.description}"
        if attachment.tag is not None:
            result += f" (#{attachment.tag})"

        result += f":\n```\n{attachment.content}\n```\n\n"

        return result


class EchoAssistant(Assistant):

    def get_ready(self) -> bool:
        return True

    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        yield ChatResponseChunk(
            """Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

""",
            is_final=False,
            is_interal_error=False,
        )

        yield ChatResponseChunk(
            self.format_message(context.messages[-1]), is_final=True, is_interal_error=False
        )

    def cancel_completion(self) -> None:
        pass


def _get_imported_user_files(main_file, source=None) -> List[str]:
    assert os.path.isabs(main_file)

    if source is None:
        source = read_source(main_file)

    try:
        root = ast.parse(source, main_file)
    except SyntaxError:
        return []

    main_dir = os.path.dirname(main_file)
    module_names = set()
    # TODO: at the moment only considers non-package modules
    for node in ast.walk(root):
        if isinstance(node, ast.Import):
            for item in node.names:
                module_names.add(item.name)
        elif isinstance(node, ast.ImportFrom):
            module_names.add(node.module)

    imported_files = []

    for file in {
        name + ext for ext in [".py", ".pyw", "pyde"] for name in module_names if name is not None
    }:
        possible_path = os.path.join(main_dir, file)
        if os.path.exists(possible_path):
            imported_files.append(possible_path)

    return imported_files
    # TODO: add recursion


def format_file_url(filename, lineno, col_offset):
    s = local_path_to_uri(filename)
    if lineno is not None:
        s += "#" + str(lineno)
        if col_offset is not None:
            s += ":" + str(col_offset)

    return s


def init():
    get_workbench().set_default("assistance.open_assistant_on_errors", True)
    get_workbench().set_default("assistance.open_assistant_on_warnings", False)
    get_workbench().set_default("assistance.disabled_checks", [])
