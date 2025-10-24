from typing import Iterator, List

from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, ChatRole


class OllamaAssistant(Assistant):
    def get_ready(self) -> bool:
        return True

    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        import ollama

        # Build messages list (history + current message)
        all_messages = list(context.messages)
        if context.current_message:
            all_messages.append(context.current_message)
        
        api_messages = [{"role": msg.role.value, "content": msg.content} for msg in all_messages]
        response = ollama.chat(
            model="codellama:7b-instruct",
            messages=api_messages,
            stream=False,
        )

        content = response["message"]["content"] if response.get("message") else ""
        yield ChatResponseChunk(content)

    def cancel_completion(self) -> None:
        pass
