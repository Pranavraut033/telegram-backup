"""
Media type filtering and message validation for Telegram backup.
Helps decide which messages to download.
"""
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    DocumentAttributeVideo, DocumentAttributeAudio,
    DocumentAttributeFilename
)
import config


def log_debug(message):
    """Print debug message if DEBUG is enabled"""
    if config.DEBUG:
        print(f"[DEBUG] {message}")


class MediaFilter:
    def __init__(self, enabled_types):
        """
        Initialize with enabled media types.
        enabled_types: list of media type keys from config.MEDIA_TYPES.
        """
        self.enabled_types = set()
        for media_type in enabled_types:
            if media_type in config.MEDIA_TYPES:
                self.enabled_types.update(config.MEDIA_TYPES[media_type])
    
    def is_media_message(self, message):
        """
        Return True if the message contains media.
        """
        try:
            return hasattr(message, 'media') and message.media is not None
        except Exception as e:
            log_debug(f"Error checking if message is media: {e}")
            return False
    
    def should_download(self, message):
        """
        Return True if the message's media type is enabled for download.
        """
        if not self.is_media_message(message):
            return False
        try:
            media_type = self._get_media_type(message.media)
            should = media_type in self.enabled_types
            if should:
                log_debug(f"Message {message.id} has media type '{media_type}' - will download")
            return should
        except Exception as e:
            log_debug(f"Error determining if should download message {message.id}: {e}")
            return False
    
    def _get_media_type(self, media):
        """
        Identify the specific media type (photo, video, audio, etc).
        """
        try:
            if isinstance(media, MessageMediaPhoto):
                return "photo"
            
            elif isinstance(media, MessageMediaDocument):
                doc = getattr(media, 'document', None)
                if not doc:
                    return "document"
                
                # Check document attributes
                attributes = getattr(doc, 'attributes', None)
                if attributes:
                    for attr in attributes:
                        try:
                            if isinstance(attr, DocumentAttributeVideo):
                                # Video message or video note
                                if getattr(attr, 'round_message', False):
                                    return "video_note"
                                return "video"
                            
                            elif isinstance(attr, DocumentAttributeAudio):
                                # Voice message or audio file
                                if getattr(attr, 'voice', False):
                                    return "voice"
                                return "audio"
                        except Exception as e:
                            log_debug(f"Error checking document attribute: {e}")
                            continue
                
                # Check MIME type
                mime_type = getattr(doc, 'mime_type', None)
                if mime_type:
                    mime_lower = mime_type.lower()
                    if mime_lower.startswith('image/'):
                        # Check if sticker
                        has_sticker = any(
                            hasattr(attr, 'stickerset') for attr in attributes
                        ) if attributes else False
                        return "sticker" if has_sticker else "photo"
                    elif mime_lower.startswith('video/'):
                        return "video"
                    elif mime_lower.startswith('audio/'):
                        return "audio"
                
                return "document"
            
            return "unknown"
        except Exception as e:
            log_debug(f"Error getting media type: {e}")
            return "unknown"
    
    def get_filename(self, message):
        """
        Extract a filename from the message's media, or generate one if needed.
        Returns None if message has no media.
        """
        try:
            if not self.is_media_message(message):
                return None
            
            media = message.media
            
            # Photo - generate filename
            if isinstance(media, MessageMediaPhoto):
                return f"photo_{message.id}.jpg"
            
            # Document - try to get original filename
            elif isinstance(media, MessageMediaDocument):
                doc = getattr(media, 'document', None)
                if not doc:
                    return f"media_{message.id}"
                
                # Try to get filename from attributes
                attributes = getattr(doc, 'attributes', None)
                if attributes:
                    for attr in attributes:
                        if isinstance(attr, DocumentAttributeFilename):
                            try:
                                filename = getattr(attr, 'file_name', None)
                                if filename and '.' in filename:
                                    name, ext = filename.rsplit('.', 1)
                                    return f"{name}.{ext.lower()}"
                                return filename if filename else f"media_{message.id}"
                            except Exception as e:
                                log_debug(f"Error extracting filename: {e}")
                                break
                
                # Generate filename based on type and MIME type
                media_type = self._get_media_type(media)
                mime_type = getattr(doc, 'mime_type', None)
                ext = self._get_extension_from_mime(mime_type) if mime_type else ""
                return f"{media_type}_{message.id}{ext}"
            
            return f"media_{message.id}"
        except Exception as e:
            log_debug(f"Error generating filename for message {message.id}: {e}")
            return f"media_{message.id}"
    
    def _get_extension_from_mime(self, mime_type):
        """
        Get file extension from a MIME type string.
        Returns empty string if MIME type is unknown or None.
        """
        if not mime_type:
            return ""
        
        try:
            mime_map = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'video/mp4': '.mp4',
                'video/webm': '.webm',
                'audio/mpeg': '.mp3',
                'audio/ogg': '.ogg',
                'audio/opus': '.opus',
                'application/pdf': '.pdf',
                'application/zip': '.zip',
            }
            
            return mime_map.get(mime_type.lower(), '')
        except Exception as e:
            log_debug(f"Error getting extension from MIME type '{mime_type}': {e}")
            return ""
