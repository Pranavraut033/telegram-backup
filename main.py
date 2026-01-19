#!/usr/bin/env python3
"""
Entry point for Telegram Media Backup CLI.
Handles user interaction, configuration, and main workflow.
"""
import asyncio
import os
import sys
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from telegram_client import TelegramClientManager, log_debug
from dialog_selector import DialogSelector
from media_filter import MediaFilter
from topic_handler import TopicHandler
from downloader import MediaDownloader
import config
import utils

console = Console()

class TelegramMediaBackup:
    def __init__(self, debug=False):
        config.DEBUG = debug
        self.client_manager = TelegramClientManager()
        self.client = None
        
    async def run(self):
        """
        Main execution flow for the backup tool.
        Handles user prompts, dialog selection, and download process.
        """
        try:
            console.print(Panel(
                "[bold green]TELEGRAM MEDIA BACKUP[/bold green]\n" +
                "[dim]Options: --logout to sign out, --debug for verbose logging[/dim]",
                expand=False,
                border_style="blue"
            ))

            if config.DEBUG:
                console.print("[bold yellow][DEBUG MODE ENABLED][/bold yellow]\n")
            
            if not sys.stdout.isatty():
                console.print("[bold yellow]⚠️  Warning: Terminal is not interactive. Progress bar and rich formatting may not display correctly.[/bold yellow]\n")

            # Initialize Telegram client
            log_debug("Starting client initialization")
            self.client = await self.client_manager.initialize()
            log_debug("Client initialized successfully")

            # Let user select a chat or group
            log_debug("Starting dialog selection")
            selector = DialogSelector(self.client)
            dialog = await selector.select_dialog()
            if not dialog:
                console.print("[bold red]No dialog selected. Exiting.[/bold red]")
                return

            # Prompt for user preferences
            media_types = self._prompt_media_types()
            if not media_types:
                console.print("[bold red]No media types selected. Exiting.[/bold red]")
                return
            message_limit = self._prompt_message_limit()
            max_file_size = self._prompt_max_file_size()
            date_range = self._prompt_date_range()
            output_dir = self._prompt_output_directory()

            # Set up main components
            media_filter = MediaFilter(media_types)
            topic_handler = TopicHandler(self.client)
            downloader = MediaDownloader(self.client, media_filter, output_dir, max_file_size=max_file_size)

            # Download from forum or regular chat
            is_forum = await topic_handler.is_forum(dialog.entity)
            if is_forum:
                await self._download_forum_media(dialog, topic_handler, downloader, message_limit)
            else:
                await downloader.download_from_chat(
                    dialog.entity,
                    dialog.name,
                    limit=message_limit,
                    date_from=date_range[0],
                    date_to=date_range[1]
                )
            # Summary is printed by downloader now  
        except KeyboardInterrupt:
            console.print("\n\n[bold yellow]⚠️  Operation cancelled by user.[/bold yellow]")
        except Exception as e:
            console.print(f"\n[bold red]❌ Error: {str(e)}[/bold red]")
            sys.exit(1)
        finally:
            await self.client_manager.disconnect()
    
    async def _download_forum_media(self, dialog, topic_handler, downloader, limit):
        """
        Download media from a forum chat, handling topics if present.
        """
        chat_dir = utils.create_directory(
            os.path.join(downloader.output_dir, utils.sanitize_dirname(dialog.name))
        )
        
        console.print(f"\n[bold blue]📥 Forum detected:[/bold blue] {dialog.name}")
        console.print("[bold magenta]🔍 Fetching topics...[/bold magenta]\n")
        
        topics = await topic_handler.get_topics(dialog.entity)
        
        if not topics:
            console.print("[yellow]No topics found. Downloading from main chat...[/yellow]")
            await downloader.download_from_chat(
                dialog.entity,
                dialog.name,
                limit=limit
            )
            return
        
        console.print(f"[green]Found {len(topics)} topics[/green]\n")
        
        # Rename old topic folders for backward compatibility
        renamed = utils.rename_old_topic_folders(chat_dir, topics)
        if renamed:
            console.print(f"[bold cyan]📁 Migrated {len(renamed)} old topic folder(s) to new names[/bold cyan]\n")
        
        for topic in topics:
            topic_name = topic_handler.get_topic_name(topic)
            topic_id = topic.get('id') if isinstance(topic, dict) else getattr(topic, 'id', None)
            
            if topic_id:
                await downloader.download_from_topic(
                    dialog.entity,
                    topic_id,
                    topic_name,
                    chat_dir,
                    limit=limit
                )
    
    def _prompt_media_types(self):
        """
        Prompt user to select which media types to download.
        Returns a list of selected types.
        """
        console.print("\n[bold yellow]=== Media Types ===[/bold yellow]")
        console.print("Available types:")
        
        types = list(config.MEDIA_TYPES.keys())
        for idx, media_type in enumerate(types, 1):
            console.print(f"{idx}. {media_type}")
        
        console.print(f"{len(types) + 1}. All")
        
        choice = Prompt.ask("[bold cyan]Select media types (comma-separated numbers or 'all')[/bold cyan]", default="all").strip().lower()
        
        if choice == 'all' or choice == str(len(types) + 1):
            return types
        
        try:
            indices = [int(x.strip()) for x in choice.split(',')]
            selected = [types[i-1] for i in indices if 0 < i <= len(types)]
            return selected if selected else types
        except (ValueError, IndexError):
            console.print("[yellow]Invalid input. Selecting all media types.[/yellow]")
            return types
    
    def _prompt_message_limit(self):
        """
        Prompt user for a message limit (number of messages to process).
        Returns an integer or None for no limit.
        """
        console.print("\n[bold yellow]=== Message Limit ===[/bold yellow]")
        choice = Prompt.ask("[bold cyan]Enter message limit (press Enter for all messages)[/bold cyan]", default="").strip()
        
        if not choice:
            return None
        
        try:
            limit = int(choice)
            return limit if limit > 0 else None
        except ValueError:
            console.print("[yellow]Invalid input. Using no limit.[/yellow]")
            return None
    
    def _prompt_max_file_size(self):
        """
        Prompt user for max file size to download.
        Returns size in bytes or None for no limit.
        """
        console.print("\n[bold yellow]=== Max File Size ===[/bold yellow]")
        console.print("Skip files larger than specified size (e.g., 100MB, 2GB)")
        choice = Prompt.ask("[bold cyan]Enter max file size (press Enter for no limit)[/bold cyan]", default="").strip()
        
        if not choice:
            return None
        
        try:
            # Parse size with unit (e.g., "100MB", "2GB", "500KB")
            choice = choice.upper().replace(" ", "")
            
            if choice.endswith("GB"):
                size_value = float(choice[:-2])
                return int(size_value * 1024 * 1024 * 1024)
            elif choice.endswith("MB"):
                size_value = float(choice[:-2])
                return int(size_value * 1024 * 1024)
            elif choice.endswith("KB"):
                size_value = float(choice[:-2])
                return int(size_value * 1024)
            elif choice.endswith("B"):
                return int(float(choice[:-1]))
            else:
                # Assume MB if no unit specified
                size_value = float(choice)
                return int(size_value * 1024 * 1024)
        except (ValueError, IndexError):
            console.print("[yellow]Invalid input. Using no size limit.[/yellow]")
            return None
    
    def _prompt_date_range(self):
        """
        Prompt user for an optional date range.
        Returns a tuple (start_date, end_date) or (None, None).
        """
        console.print("\n[bold yellow]=== Date Range (Optional) ===[/bold yellow]")
        console.print("Format: YYYY-MM-DD")
        
        date_from = Prompt.ask("[bold cyan]From date (press Enter to skip)[/bold cyan]", default="").strip()
        date_to = Prompt.ask("[bold cyan]To date (press Enter to skip)[/bold cyan]", default="").strip()
        
        def parse_date(date_str):
            if not date_str:
                return None
            try:
                return datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                console.print(f"[yellow]Invalid date format: {date_str}[/yellow]")
                return None
        
        return (parse_date(date_from), parse_date(date_to))
    
    def _prompt_output_directory(self):
        """Prompt user for output directory"""
        console.print("\n[bold yellow]=== Output Directory ===[/bold yellow]")
        choice = Prompt.ask(f"[bold cyan]Enter directory (default: {config.DEFAULT_OUTPUT_DIR})[/bold cyan]", default=config.DEFAULT_OUTPUT_DIR).strip()
        
        output_dir = choice if choice else config.DEFAULT_OUTPUT_DIR
        
        try:
            utils.create_directory(output_dir)
            return output_dir
        except Exception as e:
            console.print(f"[bold red]Cannot create directory: {e}[/bold red]")
            console.print(f"[yellow]Using default: {config.DEFAULT_OUTPUT_DIR}[/yellow]")
            return config.DEFAULT_OUTPUT_DIR


def main():
    """Entry point"""
    # Check for logout flag
    if '--logout' in sys.argv or '--signout' in sys.argv:
        console.print("[bold blue]Logging out...[/bold blue]\n")
        client_manager = TelegramClientManager()
        asyncio.run(logout_session(client_manager))
        return
    
    debug = '--debug' in sys.argv or '--verbose' in sys.argv or '-v' in sys.argv
    
    if debug:
        console.print("[bold yellow]Starting in DEBUG mode...[/bold yellow]\n")
    
    backup = TelegramMediaBackup(debug=debug)
    asyncio.run(backup.run())


async def logout_session(client_manager):
    """Handle logout"""
    try:
        await client_manager.initialize()
        await client_manager.logout()
    except Exception as e:
        # If can't connect, just remove session files
        import os
        session_file = f"{config.SESSION_NAME}.session"
        session_journal = f"{config.SESSION_NAME}.session-journal"
        
        for file in [session_file, session_journal]:
            if os.path.exists(file):
                os.remove(file)
        
        console.print("[green]✓ Session files cleared.[/green]\n")


if __name__ == "__main__":
    main()