"""
Media download logic with progress tracking
"""
import os
import asyncio
import json
import time
from datetime import datetime
from telethon.errors import FloodWaitError, RPCError
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, DownloadColumn, TransferSpeedColumn, TaskID
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
import config
import utils
from state_manager import StateManager

console = Console(width=120) # Set a fixed width for consistent output

def log_debug(message):
    """Print debug message if DEBUG is enabled"""
    if config.DEBUG:
        console.log(f"[DEBUG] {message}")


class MediaDownloader:
    def _message_cache_path(self, chat_name, topic_id=None):
        suffix = f"_{topic_id}" if topic_id is not None else ""
        fname = f".message_cache_{utils.sanitize_dirname(chat_name)}{suffix}.json"
        return os.path.join(self.output_dir, fname)

    def _reaction_count(self, msg):
        """Safely compute total reactions on a message"""
        try:
            reactions = getattr(msg, 'reactions', None)
            if not reactions:
                return 0
            results = getattr(reactions, 'results', None)
            if results:
                return sum(getattr(r, 'count', 0) for r in results)
            recent = getattr(reactions, 'recent_reactions', None)
            if recent:
                return len(recent)
            return 0
        except Exception:
            return 0

    def _load_message_cache(self, chat_name, cache_key, topic_id=None):
        cache_file = self._message_cache_path(chat_name, topic_id)
        if not os.path.exists(cache_file):
            return None
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            stored_key = data.get('cache_key')
            stored_at = data.get('stored_at', 0)
            if stored_key != cache_key:
                return None
            if (time.time() - stored_at) > config.CACHE_TTL_SECONDS:
                return None
            return data.get('messages', [])
        except Exception:
            return None

    def _save_message_cache(self, chat_name, cache_key, messages, topic_id=None):
        cache_file = self._message_cache_path(chat_name, topic_id)
        payload = {
            'stored_at': time.time(),
            'cache_key': cache_key,
            'messages': messages
        }
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
        except Exception:
            log_debug("Could not write message cache file")

    async def _iter_messages_by_id(self, entity, message_ids, batch_size=100):
        """Yield messages in the provided order by batching get_messages calls."""
        for i in range(0, len(message_ids), batch_size):
            chunk = message_ids[i:i + batch_size]
            msgs = await self.client.get_messages(entity, ids=chunk)
            if not isinstance(msgs, list):
                msgs = [msgs]
            msg_map = {m.id: m for m in msgs if m}
            for mid in chunk:
                if mid in msg_map:
                    yield msg_map[mid]

    async def _collect_media_candidates(self, entity, cache_name, cache_key, limit=None, date_from=None, date_to=None, sort_by=None, topic_id=None):
        """Collect media message candidates with caching support.
        
        Returns:
            tuple: (candidates_meta list, total_media_messages count)
        """
        cached_candidates = self._load_message_cache(cache_name, cache_key, topic_id=topic_id)
        candidates_meta = []

        if cached_candidates is not None:
            candidates_meta = cached_candidates
            total_media_messages = len(candidates_meta)
            if topic_id is None:
                console.print(f"[green]Using cached message list ({total_media_messages} items, valid for {config.CACHE_TTL_SECONDS}s).[/green]\n")
            else:
                console.print(f"     [green]Using cached topic message list ({total_media_messages} items).[/green]")
            return candidates_meta, total_media_messages

        # Collect messages from scratch
        total_media_messages = 0
        if topic_id is None:
            console.print(f"[bold magenta]🔍 Scanning messages to collect media list...[/bold magenta]")
            async for message in self.client.iter_messages(entity, limit=limit, offset_date=date_to, reverse=False):
                if date_from and message.date < date_from:
                    continue
                if date_to and message.date > date_to:
                    continue
                if self.state_manager and self.state_manager.validate_downloaded_file(message.id):
                    continue
                if self.state_manager and self.state_manager.is_message_skipped(message.id):
                    continue
                if self.media_filter.should_download(message):
                    reaction_count = self._reaction_count(message) if sort_by == "reactions_desc" else 0
                    candidates_meta.append({'id': message.id, 'reaction_count': reaction_count})
                    total_media_messages += 1
        else:
            async for message in self.client.iter_messages(entity, limit=limit, reply_to=topic_id):
                if self.state_manager and self.state_manager.validate_downloaded_file(message.id):
                    continue
                if self.state_manager and self.state_manager.is_message_skipped(message.id):
                    continue
                if self.media_filter.should_download(message):
                    reaction_count = self._reaction_count(message) if sort_by == "reactions_desc" else 0
                    candidates_meta.append({'id': message.id, 'reaction_count': reaction_count})
                    total_media_messages += 1

        if sort_by == "reactions_desc":
            candidates_meta.sort(key=lambda c: c.get('reaction_count', 0), reverse=True)
        
        if topic_id is None:
            console.print(f"[green]Found {total_media_messages} media messages to process.[/green]\n")
        
        self._save_message_cache(cache_name, cache_key, candidates_meta, topic_id=topic_id)
        return candidates_meta, total_media_messages

    async def _process_messages(self, entity, candidate_ids, output_dir):
        """Process messages from candidate list and download media.
        
        Returns:
            int: Number of messages processed
        """
        message_processed_count = 0
        if candidate_ids:
            async for message in self._iter_messages_by_id(entity, candidate_ids):
                message_processed_count += 1

                if self.state_manager and self.state_manager.validate_downloaded_file(message.id):
                    log_debug(f"Skipping already downloaded message {message.id}")
                    self._update_progress(downloaded=1, advance=0)
                    continue
                
                if self.state_manager and self.state_manager.is_message_skipped(message.id):
                    log_debug(f"Skipping previously skipped message {message.id}")
                    self._update_progress(skipped=1, advance=0)
                    continue
                
                if self.media_filter.should_download(message):
                    await self._download_media(message, output_dir)
        
        return message_processed_count

    def _init_and_validate_state(self, chat_name, chat_dir):
        """Initialize state manager and validate existing files."""
        state_file = os.path.join(self.output_dir, f".backup_state_{StateManager(self.output_dir, chat_name)._sanitize_for_filename(chat_name)}.json")
        self.state_manager = StateManager(self.output_dir, chat_name)
        
        # If state file does not exist, generate it from existing files
        if not os.path.exists(state_file):
            console.print(f"[bold yellow]⚠️  No state file found. Generating state from existing files in backup folder...[/bold yellow]")
            self.state_manager.generate_state_from_existing_files(chat_dir)
            console.print(f"[green]State file generated. Ready to resume backup.[/green]")
        
        if self.state_manager.is_resuming():
            resume_info = self.state_manager.get_resume_info()
            console.print(f"\n[bold blue]🔄 Resuming previous backup...[/bold blue]")
            console.print(f"   Started: [yellow]{resume_info['started_at'][:19]}[/yellow]")
            console.print(f"   Last updated: [yellow]{resume_info['last_updated'][:19] if resume_info['last_updated'] else 'N/A'}[/yellow]")
            console.print(f"   Already downloaded: [green]{resume_info['downloaded']}[/green] files")
            console.print(f"   [bold blue]📋 Validating existing files...[/bold blue]")
            
            # Validate and count corrupted files
            corrupted_count = 0
            if isinstance(self.state_manager.state['downloaded_messages'], dict):
                for msg_id in list(self.state_manager.state['downloaded_messages'].keys()):
                    if not self.state_manager.validate_downloaded_file(msg_id):
                        corrupted_count += 1
                        del self.state_manager.state['downloaded_messages'][msg_id]
            
            if corrupted_count > 0:
                console.print(f"   [bold yellow]⚠️  Found {corrupted_count} missing or corrupted files - will re-download[/bold yellow]")
            
            # Load previous stats
            state_stats = self.state_manager.get_stats()
            self.stats['downloaded'] = state_stats['downloaded']
            self.stats['skipped'] = state_stats['skipped']
            self.stats['errors'] = state_stats['failed']

    def _init_progress_bars(self, label="Overall Progress"):
        """Initialize and return overall and file progress bars and group for Live context."""
        from rich.console import Group
        self.overall_progress = Progress(
            TextColumn(f"[bold blue]{label}:") if label else TextColumn("[bold blue]Progress:"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("[cyan]{task.completed}/{task.total}"),
            TextColumn("[green]✓{task.fields[downloaded]}[/green]"),
            TextColumn("[yellow]⊙{task.fields[skipped]}[/yellow]"),
            TextColumn("[red]✗{task.fields[errors]}[/red]"),
            TimeElapsedColumn(),
            console=console,
            refresh_per_second=10
        )
        self.file_progress = Progress(
            TextColumn("[bold cyan]Current File:"),
            TextColumn("[green]{task.description}"),
            BarColumn(bar_width=40),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
            refresh_per_second=10
        )
        progress_group = Group(
            Panel(self.overall_progress, border_style="blue"),
            self.file_progress
        )
        return progress_group
    def __init__(self, client, media_filter, output_dir, max_file_size=None, simple_mode=False):
        self.client = client
        self.media_filter = media_filter
        self.output_dir = output_dir
        self.max_file_size = max_file_size  # in bytes, None = no limit
        self.simple_mode = simple_mode  # if True, use simple logging instead of progress bars
        self.state_manager = None
        self.progress_bar = None
        self.task_id = None
        self.overall_progress = None
        self.file_progress = None
        self.current_file_task = None
        self.stats = {
            'downloaded': 0,
            'skipped': 0,
            'errors': 0,
            'total_bytes': 0,
            'skipped_size': 0  # track files skipped due to size
        }
    
    async def auto_rename_old_topic_folders(self, entity, chat_dir):
        """If chat is a forum, fetch topics and rename old topic folders automatically."""
        from topic_handler import TopicHandler
        topic_handler = TopicHandler(self.client)
        is_forum = await topic_handler.is_forum(entity)
        if is_forum:
            topics = await topic_handler.get_topics(entity)
            renamed = utils.rename_old_topic_folders(chat_dir, topics)
            if renamed:
                console.print(f"[bold cyan]📁 Migrated {len(renamed)} old topic folder(s) to new names[/bold cyan]\n")

    async def download_from_chat(self, entity, chat_name, limit=None, date_from=None, date_to=None, sort_by=None):
        """Download media from a chat"""
        log_debug(f"Starting download from chat: {chat_name}")
        chat_dir = utils.create_directory(
            os.path.join(self.output_dir, utils.sanitize_dirname(chat_name))
        )
        log_debug(f"Output directory: {chat_dir}")
        
        # Automatically rename old topic folders if this is a forum
        await self.auto_rename_old_topic_folders(entity, chat_dir)

        # Initialize state manager and validate existing files
        self._init_and_validate_state(chat_name, chat_dir)
        
        # Fix existing files with wrong extension case and update state
        renamed_count = utils.fix_extensions_in_directory(chat_dir, self.state_manager)
        if renamed_count > 0:
            console.print(f"[bold cyan]📝 Fixed {renamed_count} file(s) with uppercase extensions[/bold cyan]\n")
        
        console.print(f"\n[bold cyan]📥 Downloading media from:[/bold cyan] {chat_name}")
        console.print(f"[bold cyan]📁 Output directory:[/bold cyan] {chat_dir}")

        cache_key = {
            'filter': sorted(list(self.media_filter.enabled_types)),
            'date_from': date_from.isoformat() if date_from else None,
            'date_to': date_to.isoformat() if date_to else None,
            'limit': limit,
            'sort_by': sort_by
        }

        # Collect media candidates with caching
        candidates_meta, total_media_messages = await self._collect_media_candidates(
            entity, chat_name, cache_key, limit, date_from, date_to, sort_by
        )

        # Process messages with or without progress bars
        candidate_ids = [c['id'] for c in candidates_meta]

        if self.simple_mode:
            # Simple logging mode
            message_processed_count = await self._process_messages(entity, candidate_ids, chat_dir)
        else:
            # Progress bar mode
            progress_group = self._init_progress_bars("Overall Progress")
            with Live(progress_group, console=console, refresh_per_second=10):
                self.progress_bar = self.overall_progress
                self.task_id = self.overall_progress.add_task(
                    "Processing...",
                    total=total_media_messages,
                    downloaded=self.stats['downloaded'],
                    skipped=self.stats['skipped'],
                    errors=self.stats['errors']
                )
                message_processed_count = await self._process_messages(entity, candidate_ids, chat_dir)
                
                # Ensure final state is updated
                self.overall_progress.update(self.task_id, completed=total_media_messages)

        self.state_manager.mark_completed()
        self._print_summary(chat_name, message_processed_count)
    
    async def download_from_topic(self, entity, topic_id, topic_name, chat_dir, limit=None, sort_by=None):
        """Download media from a forum topic, with progress bar"""
        # Ensure state manager is initialized for the parent chat
        if not self.state_manager or self.state_manager.chat_name != os.path.basename(chat_dir):
            self._init_and_validate_state(os.path.basename(chat_dir), chat_dir)
        
        topic_dir = utils.create_directory(
            os.path.join(chat_dir, utils.sanitize_dirname(topic_name))
        )
        console.print(f"  [bold magenta]📋 Topic:[/bold magenta] {topic_name}")
        console.print(f"     [dim]Scanning messages to count total media...[/dim]")

        cache_key = {
            'filter': sorted(list(self.media_filter.enabled_types)),
            'limit': limit,
            'sort_by': sort_by,
            'topic_id': topic_id
        }

        # Collect or count media messages in topic
        try:
            candidates_meta, total_media_messages = await self._collect_media_candidates(
                entity, topic_name, cache_key, limit=limit, sort_by=sort_by, topic_id=topic_id
            )
        except RPCError as e:
            if 'TOPIC_ID_INVALID' in str(e):
                console.print(f"     [bold red]❌ Error: Invalid topic ID. Skipping this topic.[/bold red]")
                return
            else:
                console.print(f"     [bold red]❌ Error accessing topic: {e}. Skipping this topic.[/bold red]")
                return

        console.print(f"     [bold blue]Total media messages:[/bold blue] {total_media_messages}")

        candidate_ids = [c['id'] for c in candidates_meta]
        
        try:
            if self.simple_mode:
                # Simple logging mode
                message_processed_count = await self._process_messages(entity, candidate_ids, topic_dir)
            else:
                # Progress bar mode
                progress_group = self._init_progress_bars("Topic Progress")
                with Live(progress_group, console=console, refresh_per_second=10):
                    self.progress_bar = self.overall_progress
                    self.task_id = self.overall_progress.add_task(
                        "Processing...",
                        total=total_media_messages,
                        downloaded=self.stats['downloaded'],
                        skipped=self.stats['skipped'],
                        errors=self.stats['errors']
                    )
                    message_processed_count = await self._process_messages(entity, candidate_ids, topic_dir)
                    
                    # Ensure final state is updated
                    self.overall_progress.update(self.task_id, completed=total_media_messages)
        except RPCError as e:
            console.print(f"     [bold red]❌ Error downloading from topic: {e}. Skipping.[/bold red]")
            return

        # Count media messages from processed count (approximate)
        media_count = len([c for c in candidates_meta if c['id']])
        console.print(f"     Processed {message_processed_count} messages ({media_count} with media)")
    
    async def _download_media(self, message, directory):
        """Download media from a single message"""
        retries = 0

        # Log media type for debugging
        media_type = type(message.media).__name__ if hasattr(message, 'media') else 'None'
        log_debug(f"Attempting download for message {message.id}, media type: {media_type}")

        # Check file size limit before downloading
        if self.max_file_size is not None:
            file_size = self._get_media_size(message)
            if file_size and file_size > self.max_file_size:
                if self.state_manager:
                    self.state_manager.mark_skipped(message.id)
                self.stats['skipped'] += 1
                self.stats['skipped_size'] += 1
                log_debug(f"Skipped message {message.id}: file size {utils.format_bytes(file_size)} exceeds limit {utils.format_bytes(self.max_file_size)}")
                self._update_progress(skipped=1)
                return

        # Use media_filter to get a safe filename, fallback to message id
        if hasattr(self, 'media_filter') and hasattr(self.media_filter, 'get_filename'):
            filename = utils.sanitize_filename(self.media_filter.get_filename(message) or f"media_{message.id}")
        else:
            filename = utils.sanitize_filename(f"media_{message.id}")

        intended_path = os.path.join(directory, filename)
        file_exists_on_disk = os.path.exists(intended_path)
        file_info = None
        if self.state_manager:
            file_info = self.state_manager.state.get('downloaded_messages', {}).get(str(message.id))

        # If file exists on disk but not tracked, add it to state
        if file_exists_on_disk and (not file_info or not self.state_manager.validate_downloaded_file(message.id)):
            file_size = os.path.getsize(intended_path)
            self.state_manager.state['downloaded_messages'][str(message.id)] = {
                'filename': filename,
                'size': file_size,
                'path': intended_path
            }
            self.state_manager._save_state()
            log_debug(f"File {filename} found on disk and added to state. Skipping download.")
            return

        # If file is tracked and valid, skip download
        if file_info and file_info.get('path') and self.state_manager.validate_downloaded_file(message.id):
            log_debug(f"File already downloaded and valid: {filename}, skipping download.")
            return

        # Otherwise, generate a unique filepath (may have _1 if file exists but not valid)
        filepath = utils.get_unique_filepath(directory, filename)

        def progress_callback(current, total):
            if self.file_progress and self.current_file_task is not None:
                self.file_progress.update(self.current_file_task, completed=current, total=total)

        while retries < config.MAX_RETRIES:
            try:
                # Add file download task or log start
                if self.simple_mode:
                    console.print(f"[cyan]📥 Downloading:[/cyan] {filename} (msg {message.id})")
                elif self.file_progress:
                    self.current_file_task = self.file_progress.add_task(
                        filename,
                        total=0
                    )

                # Log download attempt details
                expected_size = self._get_media_size(message)
                log_debug(f"Starting download to: {filepath}, expected size: {utils.format_bytes(expected_size) if expected_size else 'unknown'}")

                # Download media with progress callback
                result = await self.client.download_media(
                    message.media,
                    file=filepath,
                    progress_callback=progress_callback if not self.simple_mode else None
                )

                # Log download result
                log_debug(f"Download result: {result if result else 'None/Failed'}")

                # Remove file task after completion
                if self.file_progress and self.current_file_task is not None:
                    self.file_progress.remove_task(self.current_file_task)
                    self.current_file_task = None

                if result:
                    file_size = os.path.getsize(result) if os.path.exists(result) else 0
                    # Validate download (check for incomplete files)
                    if file_size == 0:
                        # Exponential backoff for retries
                        wait_time = config.RETRY_DELAY * (2 ** retries)
                        log_debug(f"Downloaded file is empty (0 bytes) for message {message.id}: {filename}. Retry {retries + 1}/{config.MAX_RETRIES} after {wait_time}s")
                        if os.path.exists(result):
                            os.remove(result)
                        retries += 1
                        if retries >= config.MAX_RETRIES:
                            log_debug(f"Failed to download non-empty file after {config.MAX_RETRIES} attempts: {filename}")
                            self.stats['errors'] += 1
                            if self.state_manager:
                                self.state_manager.mark_failed(message.id)
                            self._update_progress(errors=1)
                            return
                        await asyncio.sleep(wait_time)
                        continue
                    self.stats['downloaded'] += 1
                    self.stats['total_bytes'] += file_size
                    if self.state_manager:
                        self.state_manager.mark_downloaded(message.id, result, file_size)
                    log_debug(f"Successfully downloaded: {filename} ({utils.format_bytes(file_size)})")
                    if self.simple_mode:
                        console.print(f"[green]✓ Downloaded:[/green] {filename} ({utils.format_bytes(file_size)})")
                    self._update_progress(downloaded=1)
                else:
                    self.stats['skipped'] += 1
                    if self.state_manager:
                        self.state_manager.mark_skipped(message.id)
                    log_debug(f"Skipped: {filename} (no media)")
                    self._update_progress(skipped=1)
                return

            except FloodWaitError as e:
                wait_time = e.seconds
                log_debug(f"Rate limited. Waiting {wait_time}s...")
                if self.file_progress and self.current_file_task is not None:
                    self.file_progress.remove_task(self.current_file_task)
                    self.current_file_task = None
                await asyncio.sleep(wait_time)
                retries += 1

            except Exception as e:
                error_msg = str(e)
                if self.file_progress and self.current_file_task is not None:
                    self.file_progress.remove_task(self.current_file_task)
                    self.current_file_task = None

                if "FILE_REFERENCE" in error_msg:
                    self.stats['skipped'] += 1
                    if self.state_manager:
                        self.state_manager.mark_skipped(message.id)
                    log_debug(f"Skipped: {filename} (file reference expired)")
                    self._update_progress(skipped=1)
                    return

                retries += 1
                if retries >= config.MAX_RETRIES:
                    self.stats['errors'] += 1
                    if self.state_manager:
                        self.state_manager.mark_failed(message.id)
                    error_short = error_msg[:60] + "..." if len(error_msg) > 60 else error_msg
                    log_debug(f"Error: {filename} - {error_short}")
                    self._update_progress(errors=1)
                    return

                await asyncio.sleep(config.RETRY_DELAY)
    
    def _get_media_size(self, message):
        """Get file size from message media"""
        try:
            if hasattr(message, 'media'):
                if hasattr(message.media, 'document') and message.media.document:
                    return message.media.document.size
                elif hasattr(message.media, 'photo') and message.media.photo:
                    # Photos don't have direct size, return None to allow download
                    return None
        except Exception:
            pass
        return None

    def _update_progress(self, downloaded=0, skipped=0, errors=0, advance=1):
        """Update the progress bar"""
        if self.overall_progress and self.task_id is not None:
            self.overall_progress.update(
                self.task_id,
                advance=advance,
                downloaded=self.stats['downloaded'],
                skipped=self.stats['skipped'],
                errors=self.stats['errors']
            )
    
    def _print_summary(self, chat_name, message_count):
        """Print download summary"""
        console.print()
        
        table = Table(title="📊 Download Summary", show_header=False, box=None)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold")
        
        table.add_row("Chat", chat_name)
        table.add_row("Messages scanned", str(message_count))
        table.add_row("✓ Downloaded", f"[green]{self.stats['downloaded']}[/green] files")
        table.add_row("⊙ Skipped", f"[yellow]{self.stats['skipped']}[/yellow] files")
        if self.stats.get('skipped_size', 0) > 0:
            table.add_row("  ↳ Too large", f"[dim yellow]{self.stats['skipped_size']}[/dim yellow] files")
        table.add_row("✗ Errors", f"[red]{self.stats['errors']}[/red] files")
        table.add_row("📦 Total size", utils.format_bytes(self.stats['total_bytes']))
        
        console.print(table)
        console.print()

    def get_stats(self):
        """Return download statistics"""
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset statistics"""
        self.stats = {
            'downloaded': 0,
            'skipped': 0,
            'errors': 0,
            'total_bytes': 0,
            'skipped_size': 0
        }
