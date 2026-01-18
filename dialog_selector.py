"""
Dialog (chat/group) listing and selection utilities for Telegram backup.
Handles user-friendly chat selection.
"""
from telethon.tl.types import Chat, Channel, User
import config
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

console = Console()

def log_debug(message):
    """
    Print debug message if DEBUG is enabled in config.
    """
    if config.DEBUG:
        console.log(f"[DEBUG] {message}")


class DialogSelector:
    def __init__(self, client):
        self.client = client

    async def list_dialogs(self):
        """
        Fetch and return a list of dialogs (chats, groups, channels).
        Ensures 'Saved Messages' is always present.
        """
        log_debug("Fetching dialogs...")
        dialogs = []
        me = await self.client.get_me()
        async for dialog in self.client.iter_dialogs():
            dialogs.append(dialog)
        log_debug(f"Found {len(dialogs)} dialogs")
        # Ensure 'Saved Messages' is present
        has_saved_messages = any(
            isinstance(d.entity, User) and d.entity.id == me.id 
            for d in dialogs
        )
        if not has_saved_messages:
            log_debug("Saved Messages not found in dialogs, adding it...")
            saved_dialog = await self.client.get_dialogs(limit=None)
            for d in saved_dialog:
                if isinstance(d.entity, User) and d.entity.id == me.id:
                    dialogs.insert(0, d)
                    break
        return dialogs

    def display_dialogs(self, dialogs):
        """
        Display dialogs in a numbered list using a Rich Table.
        """
        console.print("\n[bold yellow]=== Available Chats & Groups ===[/bold yellow]\n")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("No.", style="cyan", justify="right")
        table.add_column("Name", style="green", justify="left")
        table.add_column("Type", style="blue", justify="left")
        table.add_column("Unread", style="dim", justify="right")
        for idx, dialog in enumerate(dialogs, 1):
            entity = dialog.entity
            type_str = self._get_entity_type(entity)
            unread = str(dialog.unread_count) if dialog.unread_count > 0 else "-"
            table.add_row(str(idx), dialog.name, type_str, unread)
        console.print(table)
        console.print()

    def _get_entity_type(self, entity):
        """
        Return a string describing the entity type (user, group, channel, etc).
        """
        if isinstance(entity, User):
            if entity.is_self:
                return "Saved Messages"
            return "Private Chat"
        elif isinstance(entity, Chat):
            return "Group"
        elif isinstance(entity, Channel):
            if entity.megagroup:
                return "Supergroup"
            elif entity.broadcast:
                return "Channel"
            return "Channel"
        return "Unknown"

    async def select_dialog(self):
        """
        Interactive dialog selection from the list of available chats.
        Returns the selected dialog or None.
        """
        dialogs = await self.list_dialogs()
        if not dialogs:
            console.print("[bold red]No dialogs found.[/bold red]")
            return None
        self.display_dialogs(dialogs)
        while True:
            try:
                choice = Prompt.ask("[bold cyan]Select a chat (enter number)[/bold cyan]").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(dialogs):
                    selected = dialogs[idx]
                    confirm = Prompt.ask(f"\n[bold yellow]Selected:[/bold yellow] [green]{selected.name}[/green]\n[bold cyan]Proceed? (y/n)[/bold cyan]", default="y").strip().lower()
                    if confirm == 'y':
                        return selected
                    else:
                        console.print("[yellow]Selection cancelled.[/yellow]\n")
                        return None
                else:
                    console.print(f"[red]Invalid choice. Please enter a number between 1 and {len(dialogs)}[/red]")
            except ValueError:
                console.print("[red]Invalid input. Please enter a number.[/red]")
            except KeyboardInterrupt:
                console.print("\n\n[bold yellow]⚠️  Selection cancelled.[/bold yellow]")
                return None
