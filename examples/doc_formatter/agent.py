"""
Technical Documentation Formatter Agent
A simple LangGraph agent that formats raw technical notes into structured Markdown.
"""

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState
from sam_langgraph_a2a import env_str
import os
from typing import Literal

# Load environment variables
load_dotenv()

# System prompt for the documentation specialist
SYSTEM_PROMPT = """You are a Technical Documentation Specialist. Your sole purpose is to take raw, unorganized technical notes and format them into a structured Markdown document.

STRICT ADHERENCE RULES:
1. Use exactly three sections: ## Summary, ## Technical Details, and ## Action Items.
2. If the user mentions a specific technology (e.g., Kafka, Solace, Python), bold it.
3. Keep the tone professional, concise, and academic.
4. Do not provide preamble; start immediately with the ## Summary header.
5. If the input is empty or nonsensical, politely ask for technical input to format.

Current Environment Context: You are running as a LangGraph Cloud Deployment."""


class DocumentationFormatterAgent:
    """
    A LangGraph agent that formats technical notes into structured Markdown documentation.
    """

    def __init__(self, model_name: str = None, openai_api_key: str = None, openai_base_url: str = None, checkpointer=None):
        """
        Initialize the Documentation Formatter Agent.

        Args:
            model_name (str): The name of the language model. Defaults to LLM_MODEL_NAME env var or "gpt-4o".
            openai_api_key (str): OpenAI API key. Defaults to OPENAI_API_KEY env var.
            openai_base_url (str): OpenAI base URL. Defaults to OPENAI_BASE_URL env var.
            checkpointer: Optional LangGraph checkpointer (e.g. MemorySaver, SqliteSaver,
                PostgresSaver). When set, the compiled graph persists state across
                invocations sharing the same thread_id. Leave None for `langgraph dev`
                (the platform supplies its own persistence). Set from main.py for the
                SAM/A2A deployment path where contextId → thread_id continuity matters.
        """
        self.checkpointer = checkpointer

        # Use env_str() instead of os.getenv() so quoted values from .env
        # behave the same whether loaded by python-dotenv (CLI invocations)
        # or Docker/Podman --env-file (which doesn't strip surrounding
        # quotes). See sam_langgraph_a2a.env_str docstring for context.
        if model_name is None:
            model_name = env_str("LLM_MODEL_NAME", "gpt-4o")

        # Strip provider prefixes if present
        if "/" in model_name:
            _, model_name = model_name.split("/", 1)
        elif ":" in model_name:
            _, model_name = model_name.split(":", 1)

        llm_kwargs = {
            "model": model_name,
            "temperature": 0.3  # Lower temperature for more consistent formatting
        }

        api_key = openai_api_key or env_str("OPENAI_API_KEY")
        if api_key:
            llm_kwargs["api_key"] = api_key

        base_url = openai_base_url or env_str("OPENAI_BASE_URL")
        if base_url:
            llm_kwargs["base_url"] = base_url

        self.llm = ChatOpenAI(**llm_kwargs)

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph workflow with a single documentation formatting node.
        """
        # Define the agent node
        def documentation_formatter(state: MessagesState) -> MessagesState:
            """
            Formats technical notes into structured Markdown documentation.
            """
            messages = state["messages"]

            # Prepend the system prompt
            messages_with_system = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

            # Call the LLM
            response = self.llm.invoke(messages_with_system)

            return {"messages": [response]}

        # Create the graph
        workflow = StateGraph(MessagesState)

        # Add the single node
        workflow.add_node("formatter", documentation_formatter)

        # Define the flow: START -> formatter -> END
        workflow.add_edge(START, "formatter")
        workflow.add_edge("formatter", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def ainvoke(self, messages: list, config: dict = None):
        """
        Asynchronously invoke the agent with a list of messages.

        Args:
            messages: List of messages or a dict with "messages" key
            config: Optional configuration dict with thread_id for persistence

        Returns:
            The final state after processing
        """
        if isinstance(messages, list):
            input_data = {"messages": messages}
        else:
            input_data = messages

        if config is None:
            config = {"configurable": {"thread_id": "default"}}

        return await self.graph.ainvoke(input_data, config=config)

    def invoke(self, messages: list, config: dict = None):
        """
        Synchronously invoke the agent with a list of messages.

        Args:
            messages: List of messages or a dict with "messages" key
            config: Optional configuration dict with thread_id for persistence

        Returns:
            The final state after processing
        """
        if isinstance(messages, list):
            input_data = {"messages": messages}
        else:
            input_data = messages

        if config is None:
            config = {"configurable": {"thread_id": "default"}}

        return self.graph.invoke(input_data, config=config)


# Create the agent instance
print("Initializing Documentation Formatter Agent...")
agent_instance = DocumentationFormatterAgent()
graph = agent_instance.graph

# Export for LangGraph Cloud
__all__ = ["graph", "DocumentationFormatterAgent"]


if __name__ == "__main__":
    """
    Simple test of the documentation formatter agent.
    """
    import asyncio

    async def test_agent():
        print("\n" + "="*60)
        print("Testing Documentation Formatter Agent")
        print("="*60 + "\n")

        agent = DocumentationFormatterAgent()

        # Test input: raw technical notes
        test_input = """
        Had a meeting about the new Kafka integration. Need to use Solace for message routing.
        Python version should be 3.11. The API endpoint is /api/v1/process.
        Todo: Set up the dev environment, configure Kafka brokers, test the Solace connection.
        Main issue is the latency between services - averaging 200ms.
        """

        config = {"configurable": {"thread_id": "test-1"}}

        result = await agent.ainvoke(
            [HumanMessage(content=test_input)],
            config=config
        )

        # Extract and print the formatted response
        final_message = result["messages"][-1]
        print("FORMATTED OUTPUT:")
        print("-" * 60)
        print(final_message.content)
        print("-" * 60)

        # Test with empty input
        print("\n\nTesting with empty input...")
        result2 = await agent.ainvoke(
            [HumanMessage(content="")],
            config={"configurable": {"thread_id": "test-2"}}
        )

        final_message2 = result2["messages"][-1]
        print("RESPONSE TO EMPTY INPUT:")
        print("-" * 60)
        print(final_message2.content)
        print("-" * 60)

    asyncio.run(test_agent())
