#!/usr/bin/env python3
"""
Entry point for Telegram Media Backup CLI.
Handles user interaction, configuration, and main workflow.
"""
import asyncio
import os
import sys
import json
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
    def __init__(self, debug=False, simple_mode=False, use_last_config=True):
        config.DEBUG = debug
        self.simple_mode = simple_mode
        self.use_last_config = use_last_config
        self.client_manager = TelegramClientManager()
        self.client = None
        self.last_max_file_size_input = None
        
    async def run(self):
        """
        Main execution flow for the backup tool.
        Handles user prompts, dialog selection, and download process.
        """
        try:
            console.print(Panel(
                "[bold green]TELEGRAM MEDIA BACKUP[/bold green]\n" +
                "[dim]Options: --logout to sign out, --debug for verbose logging, --simple for simple log output[/dim]",
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

            last_config = self._load_last_config() if self.use_last_config else {}

            # Prompt for user preferences (prefilled when possible)
            media_types = self._prompt_media_types(last_config.get('media_types'))
            if not media_types:
                console.print("[bold red]No media types selected. Exiting.[/bold red]")
                return
            message_limit = self._prompt_message_limit(last_config.get('message_limit'))
            max_file_size = self._prompt_max_file_size(last_config.get('max_file_size_input'))
            date_range = self._prompt_date_range(last_config.get('date_from'), last_config.get('date_to'))
            sort_by = self._prompt_sorting(last_config.get('sort_by'))
            output_dir = self._prompt_output_directory(last_config.get('output_dir'))

            # Persist last used config for quicker reruns
            self._save_last_config({
                'media_types': media_types,
                'message_limit': message_limit,
                'max_file_size_input': self.last_max_file_size_input,
                'max_file_size_bytes': max_file_size,
                'date_from': date_range[0].isoformat() if date_range[0] else None,
                'date_to': date_range[1].isoformat() if date_range[1] else None,
                'output_dir': output_dir,
                'sort_by': sort_by
            })

            # Set up main components
            media_filter = MediaFilter(media_types)
            topic_handler = TopicHandler(self.client)
            downloader = MediaDownloader(self.client, media_filter, output_dir, max_file_size=max_file_size, simple_mode=self.simple_mode)

            # Download from forum or regular chat
            is_forum = await topic_handler.is_forum(dialog.entity)
            if is_forum:
                await self._download_forum_media(dialog, topic_handler, downloader, message_limit, sort_by)
            else:
                await downloader.download_from_chat(
                    dialog.entity,
                    dialog.name,
                    limit=message_limit,
                    date_from=date_range[0],
                    date_to=date_range[1],
                    sort_by=sort_by
                )
            # Summary is printed by downloader now  
        except KeyboardInterrupt:
            console.print("\n\n[bold yellow]⚠️  Operation cancelled by user.[/bold yellow]")
        except Exception as e:
            console.print(f"\n[bold red]❌ Error: {str(e)}[/bold red]")
            sys.exit(1)
        finally:
            await self.client_manager.disconnect()
    
    async def _download_forum_media(self, dialog, topic_handler, downloader, limit, sort_by):
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
                    limit=limit,
                    sort_by=sort_by
                )
    
    def _prompt_media_types(self, last_selected=None):
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
        default_hint = "" if not last_selected else " (Enter to reuse last selection)"
        choice = Prompt.ask("[bold cyan]Select media types (comma-separated numbers or 'all')[/bold cyan]" + default_hint, default="" if last_selected else "all").strip().lower()
        
        if not choice and last_selected:
            return last_selected
        if choice == 'all' or choice == str(len(types) + 1) or (not choice and not last_selected):
            return types
        
        try:
            indices = [int(x.strip()) for x in choice.split(',')]
            selected = [types[i-1] for i in indices if 0 < i <= len(types)]
            return selected if selected else (last_selected or types)
        except (ValueError, IndexError):
            console.print("[yellow]Invalid input. Selecting previous or all media types.[/yellow]")
            return last_selected or types

    def _prompt_message_limit(self, last_limit=None):
        """
        Prompt user for a message limit (number of messages to process).
        Returns an integer or None for no limit.
        """
        console.print("\n[bold yellow]=== Message Limit ===[/bold yellow]")
        default_val = str(last_limit) if last_limit else ""
        choice = Prompt.ask("[bold cyan]Enter message limit (press Enter for all messages)[/bold cyan]", default=default_val).strip()
        
        if not choice:
            return last_limit
        
        try:
            limit = int(choice)
            return limit if limit > 0 else last_limit
        except ValueError:
            console.print("[yellow]Invalid input. Using previous or no limit.[/yellow]")
            return last_limit

    def _prompt_max_file_size(self, last_input=None):
        """
        Prompt user for max file size to download.
        Returns size in bytes or None for no limit.
        """
        console.print("\n[bold yellow]=== Max File Size ===[/bold yellow]")
        console.print("Skip files larger than specified size (e.g., 100MB, 2GB)")
        default_val = last_input or ""
        choice = Prompt.ask("[bold cyan]Enter max file size (press Enter for no limit)[/bold cyan]", default=default_val).strip()
        
        if not choice and last_input:
            choice = last_input
        if not choice:
            self.last_max_file_size_input = None
            return None
        raw_choice = choice
        try:
            # Parse size with unit (e.g., "100MB", "2GB", "500KB")
            choice_proc = raw_choice.upper().replace(" ", "")
            
            if choice_proc.endswith("GB"):
                size_value = float(choice_proc[:-2])
                size_bytes = int(size_value * 1024 * 1024 * 1024)
            elif choice_proc.endswith("MB"):
                size_value = float(choice_proc[:-2])
                size_bytes = int(size_value * 1024 * 1024)
            elif choice_proc.endswith("KB"):
                size_value = float(choice_proc[:-2])
                size_bytes = int(size_value * 1024)
            elif choice_proc.endswith("B"):
                size_bytes = int(float(choice_proc[:-1]))
            else:
                # Assume MB if no unit specified
                size_value = float(choice_proc)
                size_bytes = int(size_value * 1024 * 1024)
            self.last_max_file_size_input = raw_choice
            return size_bytes
        except (ValueError, IndexError):
            console.print("[yellow]Invalid input. Using previous or no size limit.[/yellow]")
            self.last_max_file_size_input = last_input
            return None

    def _prompt_date_range(self, default_from=None, default_to=None):
        """
        Prompt user for an optional date range.
        Returns a tuple (start_date, end_date) or (None, None).
        """
        console.print("\n[bold yellow]=== Date Range (Optional) ===[/bold yellow]")
        console.print("Format: YYYY-MM-DD")
        
        date_from = Prompt.ask("[bold cyan]From date (press Enter to skip)[/bold cyan]", default=default_from or "").strip()
        date_to = Prompt.ask("[bold cyan]To date (press Enter to skip)[/bold cyan]", default=default_to or "").strip()
        
        def parse_date(date_str):
            if not date_str:
                return None
            try:
                return datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                console.print(f"[yellow]Invalid date format: {date_str}[/yellow]")
                return None
        
        return (parse_date(date_from), parse_date(date_to))

    def _prompt_output_directory(self, last_output_dir=None):
        """Prompt user for output directory"""
        console.print("\n[bold yellow]=== Output Directory ===[/bold yellow]")
        default_dir = last_output_dir or config.DEFAULT_OUTPUT_DIR
        choice = Prompt.ask(f"[bold cyan]Enter directory (default: {default_dir})[/bold cyan]", default=default_dir).strip()
        
        output_dir = choice if choice else default_dir
        
        try:
            utils.create_directory(output_dir)
            return output_dir
        except Exception as e:
            console.print(f"[bold red]Cannot create directory: {e}[/bold red]")
            console.print(f"[yellow]Using default: {config.DEFAULT_OUTPUT_DIR}[/yellow]")
            return config.DEFAULT_OUTPUT_DIR

    def _prompt_sorting(self, last_sort_by=None):
        """Prompt for optional sorting preference"""
        console.print("\n[bold yellow]=== Sorting (Optional) ===[/bold yellow]")
        console.print("1. Default (by date)")
        console.print("2. Most reactions first")
        default_choice = "2" if last_sort_by == "reactions_desc" else "1"
        choice = Prompt.ask("[bold cyan]Choose sorting (1/2)[/bold cyan]", default=default_choice).strip()
        if choice == "2":
            return "reactions_desc"
        return None

    def _load_last_config(self):
        path = config.LAST_CONFIG_FILE
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_last_config(self, data):
        path = config.LAST_CONFIG_FILE
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log_debug(f"Could not write last config file: {e}")

def print_help():
    """Display help message from help.txt file"""
    try:
        help_file = os.path.join(os.path.dirname(__file__), 'help.txt')
        with open(help_file, 'r', encoding='utf-8') as f:
            help_text = f.read()
        print(help_text)
    except FileNotFoundError:
        console.print("[bold red]Error: help.txt file not found[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Error reading help file: {e}[/bold red]")

def main():
    """Entry point"""
    # Check for help flag
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        return
    
    # Check for logout flag
    if '--logout' in sys.argv or '--signout' in sys.argv:
        console.print("[bold blue]Logging out...[/bold blue]\n")
        client_manager = TelegramClientManager()
        asyncio.run(logout_session(client_manager))
        return
    
    # Handle consolidate-duplicates mode
    if '--consolidate-duplicates' in sys.argv or '--find-duplicates' in sys.argv:
        # Get directory from command line or prompt
        target_dir = None
        for i, arg in enumerate(sys.argv):
            if arg in ['--consolidate-duplicates', '--find-duplicates'] and i + 1 < len(sys.argv):
                target_dir = sys.argv[i + 1]
                break
        
        if not target_dir:
            target_dir = Prompt.ask("[cyan]Enter backup directory path to scan for duplicates[/cyan]")
        
        if not os.path.isdir(target_dir):
            console.print(f"[bold red]Error: '{target_dir}' is not a valid directory[/bold red]")
            sys.exit(1)
        
        # Create a downloader instance just for consolidation (no client needed)
        from downloader import MediaDownloader
        downloader = MediaDownloader(None, None, target_dir)
        downloader.consolidate_duplicates(target_dir)
        return
    
    debug = '--debug' in sys.argv or '--verbose' in sys.argv or '-v' in sys.argv
    simple_mode = '--simple' in sys.argv or '--no-progress' in sys.argv
    use_last_config = '--fresh' not in sys.argv and '--no-cache' not in sys.argv
    
    if debug:
        console.print("[bold yellow]Starting in DEBUG mode...[/bold yellow]\n")
    
    if simple_mode:
        console.print("[bold cyan]Using simple logging mode (progress bars disabled)...[/bold cyan]\n")
    
    if not use_last_config:
        console.print("[bold cyan]Fresh mode: ignoring last used settings...[/bold cyan]\n")
    
    backup = TelegramMediaBackup(debug=debug, simple_mode=simple_mode, use_last_config=use_last_config)
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