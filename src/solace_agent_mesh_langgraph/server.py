# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Actual Solace messaging imports
SOLACE_AVAILABLE = True

try:
    import solace
    logger.debug("Solace package found at: %s", solace.__file__)

    from solace.messaging.messaging_service import MessagingService
    from solace.messaging.resources.queue import Queue
    from solace.messaging.resources.topic_subscription import TopicSubscription
    from solace.messaging.receiver.message_receiver import MessageHandler, InboundMessage
    from solace.messaging.publisher.direct_message_publisher import DirectMessagePublisher
    SOLACE_AVAILABLE = True
except ImportError as e:
    logger.error("Could not import Solace PubSub+ package: %s", e)
    SOLACE_AVAILABLE = False

from .adapter import LangChainA2AAdapter, Task, RequestContext, EventQueue
from .config import env_str

class A2ALangchainServer:
    """
    Hosts a LangChain agent, connecting it to the Solace Event Mesh.
    This class handles the SMF protocol connection and message dispatching.
    """

    def __init__(self, langgraph_app: Any, broker_properties: Dict, agent_card: Dict):
        """
        Initializes the server.

        Args:
            langgraph_app: The compiled LangGraph application.
            broker_properties (dict): Connection details for the Solace broker.
            agent_card (dict): The agent card metadata for discovery.
        """
        logger.debug("Initializing A2ALangchainServer...")

        if not langgraph_app:
            raise ValueError("A compiled LangGraph application is required.")
        if not broker_properties:
            raise ValueError("Solace broker properties are required.")
        if not agent_card or "name" not in agent_card:
            raise ValueError("Agent card with a 'name' is required.")

        self.agent_card = agent_card
        self.agent_name = agent_card["name"]
        self.namespace = env_str("SAM_NAMESPACE", "sam-demo")
        logger.debug("Agent name: %s  namespace: %s", self.agent_name, self.namespace)

        self.adapter = LangChainA2AAdapter(langgraph_app)
        logger.debug("Created LangChainA2AAdapter")

        self.broker_properties = broker_properties
        logger.info(
            "Broker host: %s  vpn: %s  user: %s",
            broker_properties.get("solace.messaging.transport.host", "<unset>"),
            broker_properties.get("solace.messaging.service.vpn-name", "<unset>"),
            broker_properties.get("solace.messaging.authentication.scheme.basic.username", "<unset>"),
        )

        self.messaging_service = None
        self.publisher = None
        self._is_running = False
        self._publish_card_task = None
        self._receive_task = None
        self.agent_registry = {}

        logger.debug("A2ALangchainServer initialization complete")

    async def start(self):
        """
        Connects to the Solace broker, creates and binds a queue, subscribes to topics, and starts listening.
        """
        if not SOLACE_AVAILABLE:
            raise RuntimeError("Solace PubSub+ package is required but not available. Install with: pip install solace-pubsubplus")

        logger.info("Starting A2A Langchain Server...")

        try:
            self.messaging_service = MessagingService.builder().from_properties(self.broker_properties).build()
            self.messaging_service.connect()
            logger.info("Connected to Solace PubSub+ broker")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Solace broker: {e}")

        self.outbound_message_builder = self.messaging_service.message_builder()

        try:
            from solace.messaging.resources.queue import Queue as SolaceQueue
            self.queue = SolaceQueue.non_durable_exclusive_queue("")
        except Exception as e:
            raise RuntimeError(f"Failed to create Solace queue reference: {e}")

        try:
            from solace.messaging.config.missing_resources_creation_configuration import MissingResourcesCreationStrategy
            receiver_builder = (
                self.messaging_service.create_persistent_message_receiver_builder()
                .with_message_auto_acknowledgement()
                .with_missing_resources_creation_strategy(MissingResourcesCreationStrategy.CREATE_ON_START)
            )
            self.receiver = receiver_builder.build(self.queue)
            self.receiver.start()
            logger.info("Queue '%s' created and receiver started", self.queue.get_name())
        except Exception as e:
            raise RuntimeError(f"Failed to create or start Solace queue receiver: {e}")

        subscriptions = [
            f"{self.namespace}/a2a/v1/agent/request/{self.agent_name}",
            f"{self.namespace}/a2a/v1/discovery/agentcards",
            f"{self.namespace}/a2a/v1/agent/response/{self.agent_name}/>",
            f"{self.namespace}/a2a/v1/agent/status/{self.agent_name}/>"
        ]
        for sub in subscriptions:
            self.receiver.add_subscription(TopicSubscription.of(sub))
            logger.debug("Subscribed: %s", sub)

        try:
            self.publisher = self.messaging_service.create_persistent_message_publisher_builder().build()
            self.publisher.start()
            logger.info("Solace publisher started")
        except Exception as e:
            raise RuntimeError(f"Failed to create Solace publisher: {e}")

        self._publish_card_task = asyncio.create_task(self._publish_agent_card())

        self._is_running = True
        self._receive_task = asyncio.create_task(self._message_receive_loop())

        logger.info(
            "A2A LangChain Server ready - agent=%s  queue=%s  request_topic=%s",
            self.agent_name,
            self.queue.get_name(),
            f"{self.namespace}/a2a/v1/agent/request/{self.agent_name}",
        )

        try:
            while self._is_running:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error("Error in server main loop: %s", e, exc_info=True)
            raise

    async def _message_receive_loop(self):
        """Background task for receiving messages."""
        logger.debug("Message receive loop started for queue: %s", self.queue.get_name())
        try:
            while self._is_running:
                try:
                    if self.receiver and hasattr(self.receiver, "receive_message"):
                        inbound_message = self.receiver.receive_message(500)  # 500 ms timeout
                        if inbound_message:
                            asyncio.create_task(self._message_handler(inbound_message))
                    await asyncio.sleep(0.1)
                except Exception as e:
                    if "timeout" not in str(e).lower():
                        logger.error("Error receiving message: %s", e)
                    await asyncio.sleep(0.1)
        except Exception as e:
            if "UNKNOWN_QUEUE_NAME" in str(e):
                logger.error("Queue '%s' does not exist on the Solace broker", self.queue.get_name())
            logger.error("Message receive loop error: %s", e, exc_info=True)
            self._is_running = False

    async def stop(self):
        """Stops the server and disconnects from the broker."""
        logger.info("Stopping server...")
        self._is_running = False
        if self._publish_card_task:
            self._publish_card_task.cancel()
        if self._receive_task:
            self._receive_task.cancel()
        logger.info("Server stopped.")

    async def _publish_agent_card(self):
        """Periodically publishes the agent card for discovery."""
        card_topic = f"{self.namespace}/a2a/v1/discovery/agentcards"
        while self._is_running:
            try:
                from solace.messaging.resources.topic import Topic
                destination = Topic.of(card_topic)
                message_payload = json.dumps(self.agent_card, indent=2)
                message_payload_bytearray = bytearray(message_payload, "utf-8")
                agent_card_message = self.outbound_message_builder.build(message_payload_bytearray)
                try:
                    self.publisher.publish(agent_card_message, destination)
                except Exception as pub_error:
                    logger.warning("Could not publish agent card: %s", pub_error)
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error publishing agent card: %s", e)
                await asyncio.sleep(10)

    async def _message_handler(self, message: InboundMessage):
        """
        Handles an incoming message by either storing agent cards or invoking the LangChain agent.
        """
        topic = message.get_destination_name()
        logger.debug("Received message on topic: %s", topic)

        # Handle agent card discovery messages
        if topic == f"{self.namespace}/a2a/v1/discovery/agentcards":
            try:
                agent_card = None

                if hasattr(message, "get_payload_as_bytes"):
                    try:
                        payload_bytes = message.get_payload_as_bytes()
                        if payload_bytes is not None:
                            try:
                                agent_card = json.loads(payload_bytes.decode("utf-8"))
                            except UnicodeDecodeError:
                                try:
                                    agent_card = json.loads(payload_bytes.decode("latin-1"))
                                    logger.debug("Parsed agent card from bytes (latin-1)")
                                except (UnicodeDecodeError, json.JSONDecodeError):
                                    logger.debug("Could not decode payload bytes as text (len=%d)", len(payload_bytes))
                    except Exception as e:
                        logger.debug("get_payload_as_bytes() failed: %s", e)

                if agent_card is None:
                    logger.warning("Could not extract agent card from discovery message")
                    return

                if isinstance(agent_card, dict) and "url" in agent_card:
                    agent_url = agent_card["url"]
                    if agent_url not in self.agent_registry:
                        self.agent_registry[agent_url] = agent_card
                        logger.info("Registered new agent: %s at %s", agent_card.get("name", "unknown"), agent_url)
                    else:
                        self.agent_registry[agent_url] = agent_card
                else:
                    logger.warning(
                        "Agent card missing 'url' field or not a dict - skipping (keys=%s)",
                        list(agent_card.keys()) if isinstance(agent_card, dict) else type(agent_card).__name__,
                    )
            except json.JSONDecodeError as e:
                logger.error("Error parsing agent card JSON: %s", e)
            except Exception as e:
                logger.error("Error handling agent card discovery: %s", e, exc_info=True)
            return

        # Handle agent request messages
        if topic == f"{self.namespace}/a2a/v1/agent/request/{self.agent_name}":
            request_a2aStatusTopic = None
            request_a2aUserConfig = None
            request_replyTo = None
            request_userId = None
            request_method = None
            request_Id = None
            request_context_id = None
            request_message_id = None

            logger.info("Received request for agent: %s", self.agent_name)

            try:
                # 1. Extract payload
                request_payload = None
                if hasattr(message, "get_payload_as_bytes"):
                    try:
                        payload_bytes = message.get_payload_as_bytes()
                        if payload_bytes is not None:
                            request_payload = payload_bytes.decode("utf-8")
                            logger.debug("Extracted payload from bytes (length=%d)", len(payload_bytes))
                    except Exception as e:
                        logger.debug("get_payload_as_bytes() failed: %s", e)

                logger.debug("Request payload: %s", request_payload)

                # 2. Extract Solace A2A request headers from user properties
                try:
                    request_a2aStatusTopic = message.get_property("a2aStatusTopic") if message.has_property("a2aStatusTopic") else None
                    request_a2aUserConfig = message.get_property("a2aUserConfig") if message.has_property("a2aUserConfig") else None
                    request_replyTo = message.get_property("replyTo") if message.has_property("replyTo") else None
                    request_userId = message.get_property("userId") if message.has_property("userId") else None
                except Exception as header_error:
                    logger.warning("Could not extract message properties: %s", header_error)

                if not request_payload or request_payload.strip() == "":
                    logger.error("Received empty request payload")
                    return

                # Parse JSONRPC request
                try:
                    jsonrpc_request = json.loads(request_payload)
                    logger.debug("Parsed JSONRPC request: %s", jsonrpc_request)

                    if jsonrpc_request.get("jsonrpc") != "2.0":
                        logger.error("Invalid JSONRPC version: %s", jsonrpc_request.get("jsonrpc"))
                        return

                    request_method = jsonrpc_request.get("method")
                    params = jsonrpc_request.get("params", {})
                    request_id = jsonrpc_request.get("id")

                    if params and "message" in params:
                        message_data = params["message"]
                        request_context_id = message_data.get("contextId")
                        request_message_id = message_data.get("messageId")

                    logger.debug("method=%s  id=%s  context_id=%s", request_method, request_id, request_context_id)

                    actual_message = None
                    agent_name_from_request = None

                    if request_method in ["message/send", "message/stream"]:
                        message_data = params.get("message", {})
                        parts = message_data.get("parts", [])
                        if parts:
                            text_parts = [
                                p.get("text", "")
                                for p in parts
                                if p.get("kind") == "text" and not p.get("text", "").startswith("Request received by gateway")
                            ]
                            if not text_parts:
                                text_parts = [p.get("text", "") for p in parts if p.get("kind") == "text"]
                            actual_message = "\n".join(text_parts)
                            logger.debug("Extracted message: %.100s", actual_message)
                        else:
                            logger.error("No message parts found in %s request", request_method)
                            return

                        metadata = message_data.get("metadata", {})
                        agent_name_from_request = metadata.get("agent_name")
                    else:
                        logger.error("Method not supported: %s", request_method)
                        return

                except json.JSONDecodeError as e:
                    logger.error("Failed to parse JSONRPC request: %s", e)
                    return

                # Map A2A contextId -> LangGraph thread_id so a checkpointer-
                # equipped graph keeps conversation state across turns. Fall
                # back to a fresh UUID only when the caller did not provide a
                # contextId.
                session_id = request_context_id or str(uuid.uuid4())
                logger.debug("Session ID: %s (contextId=%s)", session_id, request_context_id)

                task = Task(
                    session_id=session_id,
                    message={
                        "parts": [{"text": actual_message}],
                        "jsonrpc": {
                            "method": request_method,
                            "params": params,
                            "id": request_id,
                        },
                    },
                )
                context = RequestContext(task=task)
                event_queue = EventQueue()

                response_topic = request_replyTo
                logger.debug("Response topic: %s", response_topic)
                response_task = asyncio.create_task(
                    self._response_publisher(event_queue, response_topic, request_id,
                                             request_context_id, request_a2aUserConfig)
                )

                try:
                    logger.info("Executing %s agent (session=%s)...", self.agent_name, session_id)
                    await self.adapter.execute(context, event_queue)
                    logger.info("Agent execution completed (session=%s)", session_id)
                except Exception as e:
                    logger.error("Error during agent execution: %s", e, exc_info=True)
                finally:
                    await event_queue.put(None)
                    await response_task
                    logger.debug("Request processing complete (session=%s)", session_id)

            except Exception as e:
                logger.error("Error processing agent request: %s", e, exc_info=True)
        else:
            logger.debug("Message on unhandled topic: %s", topic)

    async def _response_publisher(self, event_queue: EventQueue, topic: str, request_id: str = None,
                                  context_id: str = None, request_a2aUserConfig: str = None):
        """
        Monitors the event queue and publishes JSONRPC formatted messages to the response topic.
        """
        logger.debug("Response publisher started - topic=%s  request_id=%s", topic, request_id)
        event_count = 0

        while True:
            event = await event_queue.get()

            if event is None:
                logger.debug("End-of-stream signal received - %d events published", event_count)
                break

            event_count += 1
            logger.debug("Event #%d from queue: %s", event_count, type(event).__name__)

            # Extract message content
            event_text = ""
            jsonrpc_info = {}

            if hasattr(event, "get") and callable(getattr(event, "get")):
                event_text = event.get("parts", [{}])[0].get("text", "")
                jsonrpc_info = event.get("jsonrpc", {})
            elif hasattr(event, "content"):
                event_text = str(event.content)
            elif hasattr(event, "text"):
                event_text = str(event.text)
            else:
                event_text = str(event)

            if jsonrpc_info and not request_id:
                request_id = jsonrpc_info.get("id")

            logger.debug("Event text (first 200 chars): %.200s", event_text)

            try:
                from datetime import datetime, timezone
                import uuid as _uuid

                message_text = event_text
                if not message_text and hasattr(event, "content"):
                    message_text = str(event.content)

                # Determine if this is a terminal event. The adapter emits
                # state="working" for streaming chunks and state="completed"
                # exactly once at the end. Anything other than "completed" is
                # treated as intermediate.
                state = event.get("state", "completed") if isinstance(event, dict) else "completed"
                is_final = state == "completed"

                status_message = {
                    "kind": "message",
                    "messageId": str(_uuid.uuid4()).replace("-", ""),
                    "parts": [{"kind": "text", "text": message_text}],
                    "role": "agent",
                }
                timestamp = datetime.now(timezone.utc).isoformat()

                if is_final:
                    # Terminal envelope: A2A `Task`. SAM gateway tears down the
                    # task context as soon as it sees one of these, so it must
                    # be sent exactly once and last.
                    result_data = {
                        "contextId": context_id,
                        "id": request_id,
                        "kind": "task",
                        "metadata": {"agent_name": self.agent_name},
                        "status": {
                            "message": status_message,
                            "state": state,
                            "timestamp": timestamp,
                        },
                        "artifacts": [
                            {
                                "artifactId": str(_uuid.uuid4()).replace("-", ""),
                                "name": "response",
                                "parts": [{"kind": "text", "text": message_text}],
                            }
                        ],
                    }
                else:
                    # Intermediate envelope: A2A `TaskStatusUpdateEvent`. Must
                    # set kind="status-update", taskId (not id), and final=False.
                    # No artifacts — those belong only on the terminal Task.
                    result_data = {
                        "contextId": context_id,
                        "taskId": request_id,
                        "kind": "status-update",
                        "metadata": {"agent_name": self.agent_name},
                        "status": {
                            "message": status_message,
                            "state": state,
                            "timestamp": timestamp,
                        },
                        "final": False,
                    }

                response_data = {
                    "jsonrpc": "2.0",
                    "result": result_data,
                    "id": request_id,
                }
            except Exception as e:
                logger.error("Error creating response result: %s", e)
                response_data = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                    "id": request_id,
                }

            message_payload = json.dumps(response_data, indent=2)
            message_payload_bytearray = bytearray(message_payload, "utf-8")
            logger.debug("Publishing response to %s (%d chars)", topic, len(message_payload))

            from solace.messaging.resources.topic import Topic
            destination = Topic.of(topic)

            try:
                self.outbound_message_builder \
                    .with_property("a2aUserConfig", request_a2aUserConfig) \
                    .with_property("solace.agent.name", self.agent_name) \
                    .build(message_payload_bytearray)
                self.publisher.publish(message_payload, destination)
                logger.debug("Published response to %s", topic)
            except Exception as pub_error:
                try:
                    self.publisher.publish(message_payload, destination)
                    logger.debug("Published response to %s (fallback method)", topic)
                except Exception as pub_error2:
                    try:
                        self.publisher.publish(message_payload.encode("utf-8"), destination)
                        logger.debug("Published response to %s (bytes method)", topic)
                    except Exception as pub_error3:
                        logger.error(
                            "All publish methods failed for topic %s: %s | %s | %s",
                            topic, pub_error, pub_error2, pub_error3,
                        )


if __name__ == "__main__":
    print("A2A Langchain Server is a reusable module.")
    print("To use this server, import it and provide a compiled LangGraph agent.")
    print("Example usage:")
    print("    from solace_agent_mesh_langgraph import A2ALangchainServer")
    print("    server = A2ALangchainServer(langgraph_app, broker_props, agent_card)")
    print("    await server.start()")
    print("See examples/doc_formatter/main.py for a complete implementation example.")
