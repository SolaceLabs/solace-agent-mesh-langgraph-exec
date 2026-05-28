# SPDX-License-Identifier: Apache-2.0
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Local classes for A2A framework compatibility
class Task:
    def __init__(self, session_id: str, message: Dict[str, Any]):
        self.session_id = session_id
        self.message = message

class RequestContext:
    def __init__(self, task: Task):
        self.task = task

class EventQueue:
    def __init__(self):
        import asyncio
        self._queue = asyncio.Queue()

    async def get(self):
        return await self._queue.get()

    async def put(self, item):
        await self._queue.put(item)

    async def enqueue(self, item):
        await self._queue.put(item)

class AgentExecutor:
    """Base class for agent executors."""
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        pass

def new_agent_text_message(content: str, state: str = "working") -> Dict[str, Any]:
    """Create a new agent text message.

    `state` must be a valid A2A TaskState enum: submitted, working,
    input-required, completed, canceled, failed, rejected, auth-required,
    unknown. SAM's gateway validates this strictly and NACKs payloads with
    out-of-spec values.
    """
    return {
        "parts": [{"text": content}],
        "role": "agent",
        "state": state
    }

class LangChainA2AAdapter(AgentExecutor):
    def __init__(self, langgraph_app):
        """
        :param langgraph_app: A compiled LangGraph (e.g., graph.compile())
        """
        self.app = langgraph_app

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        # 1. Extract the user message from the A2A payload
        # A2A messages contain 'parts' (text, data, etc.)
        user_input = context.task.message.get("parts", [{}])[0].get("text", "")

        # 2. Map A2A session_id to LangChain thread_id
        # This ensures the LangGraph checkpointer finds the right conversation state
        config = {"configurable": {"thread_id": context.task.session_id}}

        # 3. Create the LangChain HumanMessage
        inputs = {"messages": [HumanMessage(content=user_input)]}

        # 4. Execute the Graph
        # We use astream to support real-time updates back to the Mesh
        last_content = None
        try:
            async for chunk in self.app.astream(inputs, config=config, stream_mode="values"):
                if "messages" in chunk:
                    last_message = chunk["messages"][-1]

                    # If the latest message is from the AI, send an update to the Mesh
                    if isinstance(last_message, AIMessage) and last_message.content:
                        # Translate AIMessage -> A2A Event. Use "working" (not
                        # "processing") — only valid A2A TaskState enum for
                        # in-progress is "working". SAM gateway NACKs anything
                        # else and the UI never sees the response.
                        a2a_msg = new_agent_text_message(last_message.content, state="working")
                        await event_queue.enqueue(a2a_msg)
                        last_content = last_message.content

            # Loop finished successfully - Send the final confirmation
            if last_content:
                # Mark the LAST observed message as "completed"
                # This ensures the Orchestrator knows the transaction is done.
                a2a_msg = new_agent_text_message(last_content, state="completed")
                await event_queue.enqueue(a2a_msg)

        except Exception as e:
            # Catch errors during execution and send them as A2A messages
            error_msg = f"Error executing task: {str(e)}"
            # Errors are typically terminal, so mark as completed
            a2a_msg = new_agent_text_message(error_msg, state="completed")
            await event_queue.enqueue(a2a_msg)
            raise e

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        # Optional: Handle task cancellation logic here
        pass
