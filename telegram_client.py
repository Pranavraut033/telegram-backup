"""
Telegram client initialization and session management
"""
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
import asyncio
import sys
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
        console.print("[bold blue]Choose authentication method:[/bold blue]")
        console.print("1. Phone number (default)")
        console.print("2. QR code (scan with your phone)")
        
        method = console.input("[bold cyan]Select method (1/2):[/bold cyan] ").strip()
        
        if method == '2':
            await self._authorize_qr()
        else:
            await self._authorize_phone()
        
        console.print("[green]✓ Authentication successful![/green]\n")
    
    async def _authorize_qr(self):
        """Handle QR code authorization"""
        try:
            import qrcode
        except ImportError:
            console.print("[bold red]QR code library not installed. Installing...[/bold red]")
            import subprocess
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'qrcode'])
            import qrcode
        
        console.print("\n[bold blue]🔲 QR Code Authentication[/bold blue]")
        console.print("[dim]Preparing QR code login...[/dim]\n")
        
        try:
            # Start QR login
            qr_login = await self.client.qr_login()
            log_debug("QR login initiated")
            
            # Generate and display QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_login.url)
            qr.make(fit=True)
            
            console.print("[bold yellow]Scan this QR code with your Telegram app:[/bold yellow]")
            console.print("[dim]Open Telegram → Settings → Devices → Link Desktop Device[/dim]\n")
            
            # Print QR code to terminal
            qr.print_ascii(invert=True)
            
            console.print("\n[dim]Waiting for you to scan the QR code...[/dim]")
            console.print("[dim](QR code will expire in 30 seconds)[/dim]\n")
            
            # Wait for user to scan
            await qr_login.wait()
            console.print("[green]✓ QR code scanned successfully![/green]")
            
        except asyncio.TimeoutError:
            console.print("[yellow]⚠️  QR code expired.[/yellow]")
            console.print("[yellow]Falling back to phone number authentication...[/yellow]\n")
            await self._authorize_phone()
            return
        except Exception as e:
            error_msg = str(e)
            log_debug(f"QR login error: {error_msg}")
            
            # Check if it's actually successful despite the error
            if await self.client.is_user_authorized():
                console.print("[green]✓ Authentication successful![/green]\n")
                return
            
            console.print(f"[red]⚠️  QR code login failed: {error_msg[:100]}[/red]")
            console.print("[yellow]Falling back to phone number authentication...[/yellow]\n")
            await self._authorize_phone()
            return
        
        console.print("[green]✓ Authentication successful![/green]\n")
    
    async def _authorize_phone(self):
        """Handle phone number authorization (separated for fallback)"""
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
                console.print("   • [bold yellow]CHECK TELEGRAM WEB if you're logged in there![/bold yellow]")
            elif 'Sms' in type_name:
                console.print("   • Check your SMS messages")
            elif 'Call' in type_name:
                console.print("   • You'll receive a phone call with the code")
            elif 'Flash' in type_name:
                console.print("   • Check for a flash SMS message")
        else:
            console.print("   • Check your Telegram app on any device where you're logged in")
            console.print("   • [bold yellow]CHECK TELEGRAM WEB - codes often appear there![/bold yellow]")
            console.print("   • The code might also come via SMS or phone call")
        
        console.print("\n[dim]💡 Tip: The code usually appears in Telegram notifications or the official[/dim]")
        console.print("[dim]   'Telegram' service chat. It may take a few seconds to arrive.[/dim]\n")
        
        while True:
            code = console.input("[bold cyan]Enter the code you received (or 'resend' to get a new code, 'help' for info):[/bold cyan] ").strip()
            
            if code.lower() == 'help':
                console.print("\n[bold blue]📋 Where to find your Telegram login code:[/bold blue]")
                console.print("   1. Open Telegram on ANY device (phone, tablet, computer, WEB)")
                console.print("   2. Look for a message from 'Telegram' (official account)")
                console.print("   3. Check your notifications/alerts")
                console.print("   4. [bold yellow]CHECK TELEGRAM WEB - codes often appear there first![/bold yellow]")
                console.print("   5. The code might also come via SMS to your phone")
                console.print("   6. Wait at least 30-60 seconds if you just requested it")
                console.print("\n   [dim]If still no code, type 'resend' (limited attempts) or restart with QR code login.[/dim]\n")
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
                        console.print("[bold yellow]⚠️  Cannot resend code right now (limit reached).[/bold yellow]")
                        console.print("[bold yellow]    OPTIONS:[/bold yellow]")
                        console.print("[bold yellow]    1. Use the code you already received (check Telegram Web!)[/bold yellow]")
                        console.print("[bold yellow]    2. Wait 10-15 minutes and try again[/bold yellow]")
                        console.print("[bold yellow]    3. Restart and use QR code login (option 2)[/bold yellow]\n")
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
