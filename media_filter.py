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
        return hasattr(message, 'media') and message.media is not None
    
    def should_download(self, message):
        """
        Return True if the message's media type is enabled for download.
        """
        if not self.is_media_message(message):
            return False
        media_type = self._get_media_type(message.media)
        return media_type in self.enabled_types
    
    def _get_media_type(self, media):
        """
        Identify the specific media type (photo, video, audio, etc).
        """
        if isinstance(media, MessageMediaPhoto):
            return "photo"
        
        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            
            # Check document attributes
            if doc and hasattr(doc, 'attributes'):
                for attr in doc.attributes:
                    if isinstance(attr, DocumentAttributeVideo):
                        # Video message or video note
                        if hasattr(attr, 'round_message') and attr.round_message:
                            return "video_note"
                        return "video"
                    
                    elif isinstance(attr, DocumentAttributeAudio):
                        # Voice message or audio file
                        if hasattr(attr, 'voice') and attr.voice:
                            return "voice"
                        return "audio"
                
                # Check MIME type
                if doc.mime_type:
                    mime_lower = doc.mime_type.lower()
                    if mime_lower.startswith('image/'):
                        return "sticker" if any(
                            hasattr(attr, 'stickerset') for attr in doc.attributes
                        ) else "photo"
                    elif mime_lower.startswith('video/'):
                        return "video"
                    elif mime_lower.startswith('audio/'):
                        return "audio"
            
            return "document"
        
        return "unknown"
    
    def get_filename(self, message):
        """
        Extract a filename from the message's media, or generate one if needed.
        """
        if not self.is_media_message(message):
            return None
        
        media = message.media
        
        # Photo - generate filename
        if isinstance(media, MessageMediaPhoto):
            return f"photo_{message.id}.jpg"
        
        # Document - try to get original filename
        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            
            if doc and hasattr(doc, 'attributes'):
                for attr in doc.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        # Normalize extension to lowercase
                        filename = attr.file_name
                        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
                        return f"{name}.{ext.lower()}" if ext else filename
            
            # Generate filename based on type
            media_type = self._get_media_type(media)
            ext = self._get_extension_from_mime(doc.mime_type) if doc else ""
            return f"{media_type}_{message.id}{ext}"
        
        return f"media_{message.id}"
    
    def _get_extension_from_mime(self, mime_type):
        """
        Get file extension from a MIME type string.
        """
        if not mime_type:
            return ""
        
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
