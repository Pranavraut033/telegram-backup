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
        if not candidate_ids:
            return message_processed_count

        async def process_single_message(message):
            try:
                if self.state_manager and self.state_manager.validate_downloaded_file(message.id):
                    log_debug(f"Skipping already downloaded message {message.id}")
                    self._update_progress(downloaded=1, advance=0)
                    return

                if self.state_manager and self.state_manager.is_message_skipped(message.id):
                    log_debug(f"Skipping previously skipped message {message.id}")
                    self._update_progress(skipped=1, advance=0)
                    return

                if self.media_filter.should_download(message):
                    await self._download_media(message, output_dir)
            except Exception as e:
                self.stats['errors'] += 1
                log_debug(f"Unexpected processing error for message {message.id}: {e}")
                if self.state_manager:
                    self.state_manager.mark_failed(message.id)
                self._update_progress(errors=1)

        running_tasks = set()
        async for message in self._iter_messages_by_id(entity, candidate_ids):
            message_processed_count += 1

            task = asyncio.create_task(process_single_message(message))
            running_tasks.add(task)

            if len(running_tasks) >= self.max_concurrent_downloads:
                done, pending = await asyncio.wait(running_tasks, return_when=asyncio.FIRST_COMPLETED)
                for done_task in done:
                    await done_task
                running_tasks = pending

        if running_tasks:
            await asyncio.gather(*running_tasks)
        
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
        
        # Ensure hash_index and duplicate_map exist (for backward compatibility - JSON only)
        if not self.state_manager.use_db:
            if 'hash_index' not in self.state_manager.state:
                self.state_manager.state['hash_index'] = {}
            if 'duplicate_map' not in self.state_manager.state:
                self.state_manager.state['duplicate_map'] = {}
        
        if self.state_manager.is_resuming():
            resume_info = self.state_manager.get_resume_info()
            console.print(f"\n[bold blue]🔄 Resuming previous backup...[/bold blue]")
            console.print(f"   Started: [yellow]{resume_info['started_at'][:19]}[/yellow]")
            console.print(f"   Last updated: [yellow]{resume_info['last_updated'][:19] if resume_info['last_updated'] else 'N/A'}[/yellow]")
            console.print(f"   Already downloaded: [green]{resume_info['downloaded']}[/green] files")
            console.print(f"   [bold blue]📋 Validating existing files...[/bold blue]")
            
            # Validate and count corrupted files (but skip duplicates) - JSON only
            corrupted_count = 0
            if not self.state_manager.use_db:
                if isinstance(self.state_manager.state['downloaded_messages'], dict):
                    for msg_id in list(self.state_manager.state['downloaded_messages'].keys()):
                        # Skip validation for duplicate messages (they don't have their own file)
                        if self.state_manager.is_duplicate(msg_id):
                            continue
                        
                        if not self.state_manager.validate_downloaded_file(msg_id):
                            corrupted_count += 1
                            del self.state_manager.state['downloaded_messages'][msg_id]
                
                if corrupted_count > 0:
                    console.print(f"   [bold yellow]⚠️  Found {corrupted_count} missing or corrupted files - will re-download[/bold yellow]")
                
                # Rebuild hash index if it's empty but we have downloaded files with hashes
                if not self.state_manager.state.get('hash_index'):
                    console.print(f"   [bold cyan]🔨 Building hash index for duplicate detection...[/bold cyan]")
                    self.state_manager.rebuild_hash_index()
            
            # Rebuild global hash index if it's empty (first run or migration) - JSON only
            if not self.state_manager.use_db and not self.state_manager.global_state.use_db:
                if not self.state_manager.global_state.state.get('hash_index') or len(self.state_manager.global_state.state['hash_index']) == 0:
                    console.print(f"   [bold cyan]🌐 Building global hash index for cross-chat duplicate detection...[/bold cyan]")
                    count = self.state_manager.global_state.rebuild_from_directory(self.output_dir)
                    if count > 0:
                        console.print(f"   [green]✓ Global index built with {count} unique files[/green]")
            
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
    def __init__(self, client, media_filter, output_dir, max_file_size=None, simple_mode=False, max_concurrent_downloads=3):
        self.client = client
        self.media_filter = media_filter
        self.output_dir = output_dir
        self.max_file_size = max_file_size  # in bytes, None = no limit
        self.simple_mode = simple_mode  # if True, use simple logging instead of progress bars
        self.max_concurrent_downloads = max(1, int(max_concurrent_downloads or config.DEFAULT_DOWNLOAD_CONCURRENCY))
        self.state_manager = None
        self.progress_bar = None
        self.task_id = None
        self.overall_progress = None
        self.file_progress = None
        self.current_file_task = None
        self._state_update_lock = None
        self.stats = {
            'downloaded': 0,
            'skipped': 0,
            'errors': 0,
            'total_bytes': 0,
            'skipped_size': 0  # track files skipped due to size
        }

    def _ensure_state_lock(self):
        """Lazy-initialize async lock for state updates."""
        if self._state_update_lock is None:
            self._state_update_lock = asyncio.Lock()
        return self._state_update_lock
    
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
        """Download media from a single message with duplicate detection"""
        retries = 0

        # Log media type for debugging
        media_type = type(message.media).__name__ if hasattr(message, 'media') else 'None'
        log_debug(f"Attempting download for message {message.id}, media type: {media_type}")

        # Check if this message is already marked as a duplicate
        if self.state_manager:
            canonical_id = self.state_manager.is_duplicate(message.id)
            if canonical_id:
                log_debug(f"Message {message.id} is marked as duplicate of {canonical_id}, skipping download")
                self._update_progress(skipped=1, advance=1)
                return

        # Check file size limit before downloading
        file_size = self._get_media_size(message)
        if self.max_file_size is not None:
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
            if self.state_manager.use_db:
                file_info = self.state_manager.db.get_message(self.state_manager.chat_id, message.id)
            else:
                file_info = self.state_manager.state.get('downloaded_messages', {}).get(str(message.id))

        # If file exists on disk but not tracked, compute hash and add to state
        if file_exists_on_disk and (not file_info or not self.state_manager.validate_downloaded_file(message.id)):
            actual_size = os.path.getsize(intended_path)
            sample_hash = utils.sample_hash_file(intended_path)
            if self.state_manager.use_db:
                self.state_manager.mark_downloaded(
                    message.id,
                    intended_path,
                    actual_size,
                    sample_hash=sample_hash
                )
            else:
                self.state_manager.state['downloaded_messages'][str(message.id)] = {
                    'filename': filename,
                    'size': actual_size,
                    'path': intended_path,
                    'sample_hash': sample_hash
                }
                # Update hash index
                if sample_hash:
                    self.state_manager._update_hash_index(actual_size, sample_hash, message.id)
                self.state_manager._save_state()
            log_debug(f"File {filename} found on disk and added to state with hash. Skipping download.")
            return

        # If file is tracked and valid, skip download
        if file_info and file_info.get('path') and self.state_manager.validate_downloaded_file(message.id):
            log_debug(f"File already downloaded and valid: {filename}, skipping download.")
            return

        # Check for duplicates by size and hash BEFORE downloading
        if self.state_manager and file_size and file_size > 0:
            # For large files, check if we already have a file with the same size
            # to avoid unnecessary downloads
            existing_msg_id, existing_path = self.state_manager.find_duplicate(file_size, None)
            
            # If we found potential duplicates by size, we need to download to compute hash
            # But for now, let's proceed with download and check hash after
            pass

        # Otherwise, generate a unique filepath (may have _1 if file exists but not valid)
        filepath = utils.get_unique_filepath(directory, filename)

        while retries < config.MAX_RETRIES:
            file_task_id = None
            try:
                # Add file download task or log start
                if self.simple_mode:
                    console.print(f"[cyan]📥 Downloading:[/cyan] {filename} (msg {message.id})")
                elif self.file_progress:
                    file_task_id = self.file_progress.add_task(
                        filename,
                        total=0
                    )

                # Log download attempt details
                expected_size = self._get_media_size(message)
                log_debug(f"Starting download to: {filepath}, expected size: {utils.format_bytes(expected_size) if expected_size else 'unknown'}")

                def progress_callback(current, total):
                    if self.file_progress and file_task_id is not None:
                        self.file_progress.update(file_task_id, completed=current, total=total)

                # Download media with progress callback
                result = await self.client.download_media(
                    message.media,
                    file=filepath,
                    progress_callback=progress_callback if not self.simple_mode else None
                )

                # Log download result
                log_debug(f"Download result: {result if result else 'None/Failed'}")

                # Remove file task after completion
                if self.file_progress and file_task_id is not None:
                    self.file_progress.remove_task(file_task_id)
                    file_task_id = None

                if result:
                    actual_size = os.path.getsize(result) if os.path.exists(result) else 0
                    # Validate download (check for incomplete files)
                    if actual_size == 0:
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
                    
                    # Compute sample hash after successful download
                    sample_hash = utils.sample_hash_file(result) if actual_size > 0 else None
                    
                    # Check if this file is a duplicate of an already downloaded file (local or remote)
                    if self.state_manager and sample_hash and actual_size > 0:
                        async with self._ensure_state_lock():
                            existing_msg_id, existing_location = self.state_manager.find_duplicate(actual_size, sample_hash)

                            if existing_msg_id and existing_location:
                                # Found a duplicate! Remove the just-downloaded file and mark as duplicate
                                
                                # Handle location-aware duplicate info
                                if isinstance(existing_location, dict):
                                    # Location-aware duplicate (remote or both)
                                    storage_status = existing_location.get('storage_status', 'unknown')
                                    remote_path = existing_location.get('remote_path')
                                    
                                    if existing_msg_id == 'global':
                                        # Cross-chat duplicate (remote or both)
                                        log_debug(f"Detected cross-chat duplicate (remote): message {message.id} -> {remote_path or storage_status}")
                                        os.remove(result)
                                        self.state_manager.mark_duplicate(message.id, existing_location)
                                        self.stats['skipped'] += 1
                                        if self.simple_mode:
                                            console.print(f"[yellow]⊙ Duplicate:[/yellow] {filename} (exists remotely in another chat)")
                                        self._update_progress(skipped=1)
                                    else:
                                        # Same chat duplicate (remote or both)
                                        log_debug(f"Detected duplicate (remote): message {message.id} is duplicate of {existing_msg_id}")
                                        os.remove(result)
                                        self.state_manager.mark_duplicate(message.id, existing_msg_id)
                                        self.stats['skipped'] += 1
                                        if self.simple_mode:
                                            console.print(f"[yellow]⊙ Duplicate:[/yellow] {filename} (remote duplicate of message {existing_msg_id})")
                                        self._update_progress(skipped=1)
                                    return
                                
                                elif isinstance(existing_location, str):
                                    # String path - local file
                                    if os.path.exists(existing_location):
                                        # Determine if it's same chat or cross-chat duplicate
                                        if existing_msg_id == 'global':
                                            # Cross-chat duplicate
                                            chat_name = os.path.basename(os.path.dirname(existing_location))
                                            log_debug(f"Detected cross-chat duplicate: message {message.id} is duplicate of file in chat '{chat_name}'")
                                            os.remove(result)
                                            self.state_manager.mark_duplicate(message.id, f"global:{existing_location}")
                                            self.stats['skipped'] += 1
                                            if self.simple_mode:
                                                console.print(f"[yellow]⊙ Duplicate:[/yellow] {filename} (exists in '{chat_name}')")
                                            self._update_progress(skipped=1)
                                        else:
                                            # Same chat duplicate
                                            log_debug(f"Detected duplicate: message {message.id} is duplicate of {existing_msg_id}")
                                            os.remove(result)
                                            self.state_manager.mark_duplicate(message.id, existing_msg_id)
                                            self.stats['skipped'] += 1
                                            if self.simple_mode:
                                                console.print(f"[yellow]⊙ Duplicate:[/yellow] {filename} (same as message {existing_msg_id})")
                                            self._update_progress(skipped=1)
                                        return

                            # Not a duplicate, mark as downloaded with hash
                            self.stats['downloaded'] += 1
                            self.stats['total_bytes'] += actual_size
                            self.state_manager.mark_downloaded(message.id, result, actual_size, sample_hash=sample_hash)
                    else:
                        # Not a duplicate-checking path, still count as downloaded
                        self.stats['downloaded'] += 1
                        self.stats['total_bytes'] += actual_size
                        if self.state_manager:
                            self.state_manager.mark_downloaded(message.id, result, actual_size, sample_hash=sample_hash)

                    log_debug(f"Successfully downloaded: {filename} ({utils.format_bytes(actual_size)})")
                    if self.simple_mode:
                        console.print(f"[green]✓ Downloaded:[/green] {filename} ({utils.format_bytes(actual_size)})")
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
                if self.file_progress and file_task_id is not None:
                    self.file_progress.remove_task(file_task_id)
                    file_task_id = None
                await asyncio.sleep(wait_time)
                retries += 1

            except Exception as e:
                error_msg = str(e)
                if self.file_progress and file_task_id is not None:
                    self.file_progress.remove_task(file_task_id)
                    file_task_id = None

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
    
    def consolidate_duplicates(self, backup_dir):
        """
        Find and consolidate duplicate files in a backup directory.
        Keeps one copy of each unique file and moves duplicates to a 'duplicates' subfolder.
        
        Args:
            backup_dir: Path to the backup directory to scan
            
        Returns:
            dict: Statistics about consolidation (files_scanned, duplicates_found, bytes_saved)
        """
        console.print(f"\n[bold cyan]🔍 Scanning for duplicate files in: {backup_dir}[/bold cyan]")
        
        # Use find_duplicates logic from find_duplicates.py
        from collections import defaultdict
        
        # Stage 1: Group files by size
        console.print("[dim]Stage 1/3: Grouping files by size...[/dim]")
        size_groups = defaultdict(list)
        total_files = 0
        
        for root, _, files in os.walk(backup_dir):
            # Skip the duplicates folder itself
            if 'duplicates' in root:
                continue
            for fname in files:
                if fname.startswith('.'):
                    continue
                fpath = os.path.join(root, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    size = os.path.getsize(fpath)
                    size_groups[size].append(fpath)
                    total_files += 1
                except Exception:
                    continue
        
        console.print(f"[green]Found {total_files} files[/green]")
        
        # Stage 2: For files with same size, compute sample hashes
        console.print("[dim]Stage 2/3: Computing sample hashes for size collisions...[/dim]")
        sample_hash_groups = defaultdict(list)
        
        for size, paths in size_groups.items():
            if len(paths) < 2:
                continue
            
            for path in paths:
                sample_hash = utils.sample_hash_file(path)
                if sample_hash:
                    key = f"{size}:{sample_hash}"
                    sample_hash_groups[key].append(path)
        
        # Stage 3: For sample hash collisions, verify with full hash (optional)
        console.print("[dim]Stage 3/3: Identifying duplicates...[/dim]")
        duplicate_groups = []
        
        for key, paths in sample_hash_groups.items():
            if len(paths) < 2:
                continue
            
            # For files with same size and sample hash, they are duplicates
            # (sample hash is highly accurate for our use case)
            duplicate_groups.append(paths)
        
        if not duplicate_groups:
            console.print("[green]✓ No duplicate files found![/green]")
            return {
                'files_scanned': total_files,
                'duplicates_found': 0,
                'bytes_saved': 0
            }
        
        console.print(f"\n[bold yellow]Found {len(duplicate_groups)} group(s) of duplicate files[/bold yellow]")
        
        # Create duplicates folder
        duplicates_base = os.path.join(backup_dir, 'duplicates')
        utils.create_directory(duplicates_base)
        
        # Process each duplicate group
        total_duplicates = 0
        bytes_saved = 0
        
        for idx, group in enumerate(duplicate_groups, start=1):
            # Keep the first file, move others
            canonical_path = group[0]
            duplicates = group[1:]
            
            console.print(f"\n[cyan]Group {idx}:[/cyan] {len(group)} copies of [bold]{os.path.basename(canonical_path)}[/bold]")
            console.print(f"  Keeping: {os.path.relpath(canonical_path, backup_dir)}")
            
            for dup_path in duplicates:
                try:
                    # Calculate relative path to preserve folder structure
                    rel_path = os.path.relpath(dup_path, backup_dir)
                    new_path = os.path.join(duplicates_base, rel_path)
                    
                    # Create necessary subdirectories
                    os.makedirs(os.path.dirname(new_path), exist_ok=True)
                    
                    # Move the duplicate file
                    file_size = os.path.getsize(dup_path)
                    os.rename(dup_path, new_path)
                    
                    total_duplicates += 1
                    bytes_saved += file_size
                    
                    console.print(f"  [yellow]→ Moved:[/yellow] {rel_path}")
                    
                    # Update state if state_manager is available
                    if self.state_manager:
                        self.state_manager.update_file_path(dup_path, new_path)
                    
                except Exception as e:
                    console.print(f"  [red]✗ Error moving {os.path.basename(dup_path)}: {e}[/red]")
        
        # Print summary
        console.print(f"\n[bold green]✓ Consolidation complete![/bold green]")
        console.print(f"  Files scanned: {total_files}")
        console.print(f"  Duplicates moved: {total_duplicates}")
        console.print(f"  Space saved: {utils.format_bytes(bytes_saved)}")
        console.print(f"  Duplicates folder: {os.path.relpath(duplicates_base, backup_dir)}")
        
        return {
            'files_scanned': total_files,
            'duplicates_found': total_duplicates,
            'bytes_saved': bytes_saved
        }
