"""
Forum topic detection and handling for Telegram backup.
Helps identify and process forum topics in chats.
"""
from telethon.tl.types import Channel
import config


def log_debug(message):
    """Print debug message if DEBUG is enabled"""
    if config.DEBUG:
        print(f"[DEBUG] {message}")


class TopicHandler:
    def __init__(self, client):
        """
        Initialize topic handler for a Telegram client.
        """
        self.client = client

    async def is_forum(self, entity):
        """
        Return True if the entity is a forum-enabled chat.
        """
        if not isinstance(entity, Channel):
            return False
        return getattr(entity, 'forum', False)

    async def get_topics(self, entity):
        """
        Fetch all topics from a forum chat.
        Returns a list of topic objects or dicts.
        Note: GetForumTopicsRequest is not available in this version of Telethon,
        so we use the fallback message scanning method.
        """
        if not await self.is_forum(entity):
            return []
        
        log_debug("Fetching topics from forum (using message scanning)")
        # Use message scanning fallback since GetForumTopicsRequest is not available
        topics = await self._extract_topics_from_messages(entity)
        return topics

    async def _extract_topics_from_messages(self, entity):
        """
        Extract topics by scanning messages in a chat.
        Returns a list of topic dicts.
        """
        topics_dict = {}
        try:
            log_debug("Extracting topics from messages")
            async for message in self.client.iter_messages(entity, limit=1000):
                if hasattr(message, 'reply_to') and message.reply_to:
                    # Forum topics use reply_to_msg_id for the root topic message
                    # Check for forum_topic attribute (if present) or reply_to_msg_id
                    topic_id = None
                    if hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic:
                        # This is a forum topic message
                        topic_id = message.reply_to.reply_to_msg_id
                    elif hasattr(message.reply_to, 'reply_to_msg_id') and message.reply_to.reply_to_msg_id:
                        # Could be a forum topic or regular reply - check if message is part of a topic thread
                        topic_id = message.reply_to.reply_to_msg_id
                    
                    if topic_id and topic_id not in topics_dict:
                        # Try to get the actual topic title from the first message
                        try:
                            topic_msg = await self.client.get_messages(entity, ids=topic_id)
                            if topic_msg and hasattr(topic_msg, 'message') and topic_msg.message:
                                title = topic_msg.message[:50]  # Limit title length
                            else:
                                title = f"Topic {topic_id}"
                        except Exception as e:
                            log_debug(f"Failed to fetch topic message {topic_id}: {e}")
                            title = f"Topic {topic_id}"
                        
                        topics_dict[topic_id] = {
                            'id': topic_id,
                            'title': title
                        }
            
            log_debug(f"Found {len(topics_dict)} topics via message scanning")
        except Exception as e:
            log_debug(f"Error extracting topics from messages: {e}")
        
        return list(topics_dict.values())

    async def get_topic_messages(self, entity, topic_id, limit=None):
        """
        Get messages from a specific topic in a forum chat.
        Returns a list of messages.
        """
        try:
            messages = []
            async for message in self.client.iter_messages(
                entity,
                limit=limit,
                reply_to=topic_id
            ):
                messages.append(message)
            log_debug(f"Retrieved {len(messages)} messages from topic {topic_id}")
            return messages
        except Exception as e:
            log_debug(f"Error getting messages for topic {topic_id}: {e}")
            return []

    def get_topic_name(self, topic):
        """
        Extract a topic name from a topic object or dict.
        """
        # Prefer .title attribute if present (Telethon topic object)
        if hasattr(topic, 'title') and getattr(topic, 'title', None):
            return topic.title
        # If dict, prefer 'title' key if not default
        if isinstance(topic, dict):
            title = topic.get('title', '')
            topic_id = topic.get('id', None)
            if title and topic_id and title != f"Topic {topic_id}":
                return title
            if topic_id:
                return f"Topic {topic_id}"
            return title or 'Unknown Topic'
        # fallback
        return f"Topic {getattr(topic, 'id', 'unknown')}"
