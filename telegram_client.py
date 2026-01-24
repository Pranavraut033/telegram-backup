"""
Telegram client initialization and session management
"""
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
import asyncio
import config
from rich.console import Console

console = Console()

def log_debug(message):
    """Print debug message if DEBUG is enabled"""
    if config.DEBUG:
        console.print(f"[DEBUG] {message}")


class TelegramClientManager:
    def __init__(self):
        self.client = None
        
    async def initialize(self):
        """Initialize and connect the Telegram client"""
        log_debug("Initializing Telegram client...")
        
        if config.API_ID == 0 or not config.API_HASH:
            raise ValueError(
                "Please set API_ID and API_HASH in a .env file (see .env.example)\n"
                "Get them from https://my.telegram.org/apps"
            )
        
        log_debug(f"Creating client with session: {config.SESSION_NAME}")
        self.client = TelegramClient(
            config.SESSION_NAME,
            config.API_ID,
            config.API_HASH
        )
        
        log_debug("Connecting to Telegram...")
        await self.client.connect()
        log_debug("Connected successfully")
        
        if not await self.client.is_user_authorized():
            log_debug("User not authorized, starting authentication flow")
            await self._authorize()
        else:
            log_debug("User already authorized")
        
        return self.client
    
    async def _authorize(self):
        """Handle user authorization"""
        console.print("\n[bold yellow]=== Telegram Authentication ===[/bold yellow]")
        phone = console.input("[bold cyan]Enter your phone number (including + and country code, e.g., +1234567890):[/bold cyan] ").strip()
        
        # Add + if missing
        if not phone.startswith('+'):
            phone = '+' + phone
            log_debug(f"Added + prefix to phone number: {phone}")
        
        log_debug(f"Sending code request to {phone}")
        sent_code = await self.client.send_code_request(phone)
        
        console.print("[green]✓ Code sent successfully![/green]\n")
        console.print("[bold blue]📱 Where to find your code:[/bold blue]")
        
        # Determine where the code was sent
        if hasattr(sent_code, 'type'):
            code_type = sent_code.type
            if hasattr(code_type, 'length'):
                console.print(f"   • Look for a [bold]{code_type.length}[/bold]-digit code")
            
            type_name = type(code_type).__name__
            if 'App' in type_name:
                console.print("   • Check your Telegram app (any device where you're logged in)")
                console.print("   • Look in 'Telegram' official chat or notifications")
            elif 'Sms' in type_name:
                console.print("   • Check your SMS messages")
            elif 'Call' in type_name:
                console.print("   • You'll receive a phone call with the code")
            elif 'Flash' in type_name:
                console.print("   • Check for a flash SMS message")
        else:
            console.print("   • Check your Telegram app on any device where you're logged in")
            console.print("   • The code might also come via SMS or phone call")
        
        console.print("\n[dim]💡 Tip: The code usually appears in Telegram notifications or the official[/dim]")
        console.print("[dim]   'Telegram' service chat. It may take a few seconds to arrive.[/dim]\n")
        
        while True:
            code = console.input("[bold cyan]Enter the code you received (or 'resend' to get a new code, 'help' for info):[/bold cyan] ").strip()
            
            if code.lower() == 'help':
                console.print("\n[bold blue]📋 Where to find your Telegram login code:[/bold blue]")
                console.print("   1. Open Telegram on ANY device (phone, tablet, computer)")
                console.print("   2. Look for a message from 'Telegram' (official account)")
                console.print("   3. Check your notifications/alerts")
                console.print("   4. The code might also come via SMS to your phone")
                console.print("   5. Wait at least 30-60 seconds if you just requested it")
                console.print("\n   [dim]If still no code, type 'resend' to request a new one.[/dim]\n")
                continue
            
            if code.lower() == 'resend':
                try:
                    log_debug("Resending code...")
                    await self.client.send_code_request(phone)
                    console.print("[green]✓ Code resent successfully![/green]\n")
                except FloodWaitError as e:
                    console.print(f"[yellow]⏳ Please wait {e.seconds} seconds before requesting another code.[/yellow]\n")
                    log_debug(f"FloodWaitError: {e.seconds} seconds")
                except Exception as e:
                    error_msg = str(e)
                    if "SEND_CODE_UNAVAILABLE" in error_msg or "available options" in error_msg.lower():
                        console.print("[bold yellow]⚠️  Cannot resend code right now. Please use the code you already received,[/bold yellow]")
                        console.print("[bold yellow]    or wait a few minutes before trying again.[/bold yellow]\n")
                        log_debug(f"Resend error: {error_msg}")
                    else:
                        console.print(f"[bold red]⚠️  Failed to resend code: {error_msg[:80]}[/bold red]\n")
                        log_debug(f"Unexpected resend error: {error_msg}")
                continue
            
            try:
                log_debug("Attempting to sign in with code")
                await self.client.sign_in(phone, code)
                break
            except PhoneCodeInvalidError:
                console.print("[bold red]✗ Invalid code. Please try again.[/bold red]\n")
                continue
            except SessionPasswordNeededError:
                log_debug("Two-factor authentication required")
                password = console.input("[bold yellow]Two-factor authentication enabled. Enter your password:[/bold yellow] ")
                await self.client.sign_in(password=password)
                break
        
        console.print("[green]✓ Authentication successful![/green]\n")
    
    async def logout(self):
        """Logout and remove session"""
        import os
        
        if self.client:
            try:
                log_debug("Logging out from Telegram...")
                await self.client.log_out()
                log_debug("Logged out successfully")
            except Exception as e:
                log_debug(f"Logout error (might be already logged out): {e}")
            
            await self.client.disconnect()
        
        # Remove session files
        session_file = f"{config.SESSION_NAME}.session"
        session_journal = f"{config.SESSION_NAME}.session-journal"
        
        for file in [session_file, session_journal]:
            if os.path.exists(file):
                try:
                    os.remove(file)
                    log_debug(f"Removed {file}")
                except Exception as e:
                    log_debug(f"Could not remove {file}: {e}")
        
        console.print("[green]✓ Logged out successfully. Session cleared.[/green]\n")
    
    async def disconnect(self):
        """Disconnect the client"""
        if self.client:
            await self.client.disconnect()
    
    def get_client(self):
        """Get the active client"""
        return self.client
