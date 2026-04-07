"""Discord bot for Mealie recipe import"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import sys
from pathlib import Path

# Add src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings
from mealie.client import MealieClient
from mealie.models import RecipeValidationResult
from utils.retry_queue import RetryQueue, RetryStatus, RetryTask

logger = logging.getLogger(__name__)


class MealieBot(commands.Bot):
    """Discord bot for importing recipes to Mealie"""

    def __init__(self, settings: Settings):
        # Set up intents for slash commands
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True

        # discord.py still requires a non-None command_prefix even if we mainly use slash commands.
        command_prefix = settings.discord_command_prefix or commands.when_mentioned

        super().__init__(
            command_prefix=command_prefix,
            intents=intents,
            help_command=None,  # We'll implement our own help
            # Increase message cache and chunk guilds timeout for better responsiveness
            max_messages=10000,  # Increase from default 1000
            chunk_guilds_at_startup=False,  # Don't block startup
            heartbeat_timeout=60.0,  # Increase from default 30s
        )

        self.settings = settings
        self.mealie_client: Optional[MealieClient] = None
        self.retry_queue = RetryQueue()

    async def setup_hook(self):
        """Setup hook called before bot starts"""
        # Initialize Mealie client
        self.mealie_client = MealieClient(self.settings)
        await self.mealie_client.connect()

        # Start retry queue processor
        self.retry_queue.set_retry_handler(self._process_retry_task)
        await self.retry_queue.start()

        # Register commands
        self._register_commands()
        
        # Register gateway event handlers
        self._register_gateway_events()

        # Sync slash commands with Discord
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

        logger.info("Bot setup completed")

    async def close(self):
        """Cleanup when bot closes"""
        # Stop retry queue
        await self.retry_queue.stop()
        
        if self.mealie_client:
            await self.mealie_client.disconnect()
        await super().close()

    def _register_commands(self):
        """Register slash commands"""

        @self.tree.command(name="save_recipe", description="Zapisz przepis z podanego URL")
        @app_commands.describe(url="URL przepisu do zapisania")
        async def save_recipe(interaction: discord.Interaction, url: str):
            """Save a recipe from URL to Mealie"""
            # Don't await - create task and return immediately to keep command handler responsive
            asyncio.create_task(self._handle_save_recipe_slash(interaction, url))

        @self.tree.command(name="import_bulk", description="Importuj wiele przepisów naraz (oddziel URLe przecinkami)")
        @app_commands.describe(urls="URLe przepisów oddzielone przecinkami lub spacjami")
        async def import_bulk(interaction: discord.Interaction, urls: str):
            """Import multiple recipes at once"""
            asyncio.create_task(self._handle_bulk_import(interaction, urls))

        @self.tree.command(name="import_status", description="Sprawdź status importów w kolejce")
        async def import_status(interaction: discord.Interaction):
            """Check status of imports in retry queue"""
            asyncio.create_task(self._handle_import_status(interaction))

        @self.tree.command(name="mealie_info", description="Pokaż informacje o bocie Mealie i dostępne komendy")
        async def mealie_info_command(interaction: discord.Interaction):
            """Show Mealie bot information and available commands"""
            logger.info(f"Slash command 'mealie_info' called by {interaction.user}")
            await self._handle_mealie_info_slash(interaction)

        # Handle messages - only process commands, no auto-detection
        @self.event
        async def on_message(message):
            if message.author == self.user or message.author.bot:
                return

            # Ignore non-command messages to keep gateway event loop and logs quieter.
            prefix = self.settings.discord_command_prefix
            if prefix and not message.content.startswith(prefix):
                return

            logger.debug(f"Processing command message: '{message.content}' from {message.author}")
            await self.process_commands(message)
    
    def _register_gateway_events(self):
        """Register Gateway connection event handlers for debugging"""
        
        @self.event
        async def on_connect():
            logger.info("Bot connected to Discord Gateway")
        
        @self.event  
        async def on_disconnect():
            logger.warning("Bot disconnected from Discord Gateway")
        
        @self.event
        async def on_resumed():
            logger.info("Bot resumed Gateway session")

    async def _process_retry_task(self, task: RetryTask) -> tuple[bool, Optional[str]]:
        """Execute a single retry task from the background retry queue."""
        try:
            logger.info(f"Processing retry task {task.task_id} for URL: {task.url}")

            recipe_data = await self.mealie_client.create_recipe_from_url(task.url)
            if recipe_data.get("status") == "created" and recipe_data.get("slug"):
                is_valid, validation_reason = await self.mealie_client.validate_recipe_complete(recipe_data["slug"])
                if is_valid:
                    await self._notify_retry_result(
                        task=task,
                        success=True,
                        recipe_slug=recipe_data["slug"],
                        method="Mealie parser",
                    )
                    return True, None
                logger.warning(
                    f"Retry task {task.task_id}: Mealie recipe incomplete ({validation_reason}), trying AI fallback"
                )

            ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(task.url)
            if ai_recipe_data:
                ai_slug = await self.mealie_client.create_recipe_from_ai_data(task.url, ai_recipe_data)
                if ai_slug:
                    await self._notify_retry_result(
                        task=task,
                        success=True,
                        recipe_slug=ai_slug,
                        method="OpenAI parser",
                    )
                    return True, None

            error_message = "Mealie and AI could not parse recipe during retry."
            await self._notify_retry_result(task=task, success=False, error_message=error_message)
            return False, error_message

        except Exception as e:
            logger.error(f"Retry task {task.task_id} failed with exception: {e}")
            await self._notify_retry_result(task=task, success=False, error_message=str(e))
            return False, str(e)

    async def _notify_retry_result(
        self,
        task: RetryTask,
        success: bool,
        recipe_slug: Optional[str] = None,
        method: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        """Send retry result to user via DM if possible."""
        user = self.get_user(task.user_id)
        if user is None:
            try:
                user = await self.fetch_user(task.user_id)
            except Exception as e:
                logger.warning(f"Could not fetch user {task.user_id} for retry task {task.task_id}: {e}")
                return

        attempt_number = task.attempt + 1

        try:
            if success and recipe_slug:
                recipe_url = self.mealie_client.get_recipe_url(recipe_slug)
                message = (
                    f"✅ **Retry importu zakończony sukcesem**\n"
                    f"URL: {task.url}\n"
                    f"Przepis: {recipe_url}\n"
                    f"Metoda: {method or 'unknown'}\n"
                    f"Próba: {attempt_number}/{task.max_attempts}"
                )
            else:
                message = (
                    f"⚠️ **Retry importu nie powiódł się**\n"
                    f"URL: {task.url}\n"
                    f"Próba: {attempt_number}/{task.max_attempts}\n"
                    f"Błąd: {error_message or 'unknown error'}\n"
                    f"Jeśli są kolejne próby, sprawdź status: `/import_status`"
                )

            await user.send(message)
        except Exception as e:
            logger.warning(f"Could not send retry DM to user {task.user_id} for task {task.task_id}: {e}")

    async def _handle_save_recipe_slash(self, interaction: discord.Interaction, url: str, is_retry: bool = False, retry_task_id: Optional[str] = None):
        """Handle recipe saving for slash commands with AI fallback"""
        # Log immediately when command is received
        logger.info(f"[{interaction.id}] Received save_recipe command from {interaction.user}, deferring...")
        
        # CRITICAL: Defer IMMEDIATELY - Discord gives only 3 seconds to respond
        # This MUST be the first operation, before ANY other code
        try:
            await interaction.response.defer()
            logger.info(f"[{interaction.id}] Successfully deferred interaction")
        except discord.NotFound:
            # Interaction expired (404) - add to retry queue if not already retrying
            if not is_retry:
                task = self.retry_queue.add_task(
                    task_id=f"recipe_{interaction.id}",
                    user_id=interaction.user.id,
                    url=url
                )
                logger.warning(f"[{interaction.id}] Interaction expired - added to retry queue (task: {task.task_id})")
                
                # Try to send DM to user
                try:
                    await interaction.user.send(
                        f"⏰ **Przepis dodany do kolejki retry**\n"
                        f"URL: {url}\n"
                        f"Discord nie dostarczył komendy na czas. Spróbuję ponownie za 5 minut.\n"
                        f"Status: `/import_status`"
                    )
                except:
                    logger.warning(f"Could not send DM to user {interaction.user.id}")
            else:
                logger.error(f"[{interaction.id}] Retry attempt also expired for task {retry_task_id}")
            return
        except discord.HTTPException as e:
            # Other Discord API errors during defer
            logger.error(f"[{interaction.id}] Failed to defer: {e} (user: {interaction.user}, url: {url})")
            if not is_retry:
                task = self.retry_queue.add_task(
                    task_id=f"recipe_{interaction.id}",
                    user_id=interaction.user.id,
                    url=url
                )
                logger.warning(f"[{interaction.id}] Added to retry queue due to error (task: {task.task_id})")
            return
        
        # Defer successful - now process the recipe
        logger.info(f"[{interaction.id}] Starting recipe processing for URL: {url}")
        
        try:
            # Validate URL
            if not self._is_valid_url(url):
                await interaction.followup.send(
                    "❌ Nieprawidłowy URL. Upewnij się, że podajesz prawidłowy link do przepisu."
                )
                return

            # Step 1: Try to create recipe with Mealie parser
            embed = discord.Embed(
                title="🔄 Przetwarzanie przepisu...",
                description="Próba sparsowania przepisu przez Mealie...",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)

            try:
                recipe_data = await self.mealie_client.create_recipe_from_url(url)

                if recipe_data.get('status') == 'created' and recipe_data.get('slug'):
                    # Step 2: Validate if recipe has required components
                    is_valid, validation_reason = await self.mealie_client.validate_recipe_complete(recipe_data['slug'])

                    if is_valid:
                        # Recipe is complete - success!
                        recipe_url = self.mealie_client.get_recipe_url(recipe_data['slug'])
                        embed = discord.Embed(
                            title="✅ Przepis dodany pomyślnie!",
                            description="Przepis został prawidłowo sparsowany przez Mealie i zawiera wszystkie wymagane składniki.",
                            color=discord.Color.green()
                        )
                        embed.add_field(
                            name="🔗 Link do przepisu",
                            value=f"[Zobacz przepis]({recipe_url})",
                            inline=False
                        )
                        embed.add_field(
                            name="🏷️ Slug przepisu",
                            value=f"`{recipe_data['slug']}`",
                            inline=True
                        )
                        await interaction.followup.send(embed=embed)
                        return
                    else:
                        # Recipe created but incomplete - try AI parsing
                        logger.warning(f"Recipe created but incomplete: {validation_reason}")
                        embed = discord.Embed(
                            title="⚠️ Przepis sparsowany częściowo",
                            description=f"Mealie sparsował przepis, ale brakuje: {validation_reason}\n\n🔄 Próbuję sparsować przez AI...",
                            color=discord.Color.orange()
                        )
                        await interaction.followup.send(embed=embed)

                        # Step 3: Try AI parsing
                        ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(url)

                        if ai_recipe_data:
                            # Create/update recipe with AI data
                            ai_slug = await self.mealie_client.create_recipe_from_ai_data(url, ai_recipe_data)

                            if ai_slug:
                                recipe_url = self.mealie_client.get_recipe_url(ai_slug)
                                embed = discord.Embed(
                                    title="🤖 Przepis sparsowany przez AI!",
                                    description="Przepis został pomyślnie sparsowany przez OpenAI i dodany do Mealie.",
                                    color=discord.Color.blue()
                                )
                                embed.add_field(
                                    name="🔗 Link do przepisu",
                                    value=f"[Zobacz przepis]({recipe_url})",
                                    inline=False
                                )
                                embed.add_field(
                                    name="🏷️ Slug przepisu",
                                    value=f"`{ai_slug}`",
                                    inline=True
                                )
                                embed.add_field(
                                    name="📝 Metoda",
                                    value="OpenAI parsing",
                                    inline=True
                                )
                                await interaction.followup.send(embed=embed)
                                return
                            else:
                                # AI parsing failed
                                embed = discord.Embed(
                                    title="❌ Parsowanie AI nie powiodło się",
                                    description="Nie udało się sparsować przepisu przez AI. Przepis może wymagać ręcznego dodania.",
                                    color=discord.Color.red()
                                )
                                await interaction.followup.send(embed=embed)
                                return
                        else:
                            # AI not available or failed
                            embed = discord.Embed(
                                title="❌ Brak wsparcia AI",
                                description="Przepis został częściowo sparsowany przez Mealie, ale brakuje wymaganych składników. AI nie jest dostępne lub nie udało się sparsować.",
                                color=discord.Color.red()
                            )
                            await interaction.followup.send(embed=embed)
                            return
                else:
                    # Mealie failed to create recipe - try AI
                    logger.warning("Mealie failed to create recipe - trying AI")
                    embed = discord.Embed(
                        title="⚠️ Mealie nie sparsował przepisu",
                        description="Mealie nie mógł sparsować tego przepisu.\n\n🔄 Próbuję sparsować przez AI...",
                        color=discord.Color.orange()
                    )
                    await interaction.followup.send(embed=embed)

                    # Try AI parsing
                    ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(url)

                    if ai_recipe_data:
                        # Create recipe with AI data
                        ai_slug = await self.mealie_client.create_recipe_from_ai_data(url, ai_recipe_data)

                        if ai_slug:
                            recipe_url = self.mealie_client.get_recipe_url(ai_slug)
                            embed = discord.Embed(
                                title="🤖 Przepis sparsowany przez AI!",
                                description="Przepis został pomyślnie sparsowany przez OpenAI i dodany do Mealie.",
                                color=discord.Color.blue()
                            )
                            embed.add_field(
                                name="🔗 Link do przepisu",
                                value=f"[Zobacz przepis]({recipe_url})",
                                inline=False
                            )
                            embed.add_field(
                                name="🏷️ Slug przepisu",
                                value=f"`{ai_slug}`",
                                inline=True
                            )
                            embed.add_field(
                                name="📝 Metoda",
                                value="OpenAI parsing",
                                inline=True
                            )
                            await interaction.followup.send(embed=embed)
                            return
                        else:
                            # AI creation failed
                            embed = discord.Embed(
                                title="❌ Nie udało się utworzyć przepisu",
                                description="Zarówno Mealie jak i AI nie mogły sparsować tego przepisu. Spróbuj innego linku lub dodaj przepis ręcznie.",
                                color=discord.Color.red()
                            )
                            await interaction.followup.send(embed=embed)
                            return
                    else:
                        # AI not available or failed
                        embed = discord.Embed(
                            title="❌ Automatyczne parsowanie niemożliwe",
                            description="Zarówno Mealie jak i AI nie mogły sparsować tego przepisu. AI nie jest dostępne lub link może być nieprawidłowy.",
                            color=discord.Color.red()
                        )
                        await interaction.followup.send(embed=embed)
                        return

            except ValueError as ve:
                # Mealie parsing failed - try AI
                logger.warning(f"Mealie parsing failed: {ve}")
                embed = discord.Embed(
                    title="⚠️ Parsowanie przez Mealie nie powiodło się",
                    description="Mealie nie mógł sparsować tego przepisu.\n\n🔄 Próbuję sparsować przez AI...",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)

                # Try AI parsing
                ai_recipe_data = await self.mealie_client.parse_recipe_with_ai(url)

                if ai_recipe_data:
                    ai_slug = await self.mealie_client.create_recipe_from_ai_data(url, ai_recipe_data)

                    if ai_slug:
                        recipe_url = self.mealie_client.get_recipe_url(ai_slug)
                        embed = discord.Embed(
                            title="🤖 Przepis sparsowany przez AI!",
                            description="Przepis został pomyślnie sparsowany przez OpenAI i dodany do Mealie.",
                            color=discord.Color.blue()
                        )
                        embed.add_field(
                            name="🔗 Link do przepisu",
                            value=f"[Zobacz przepis]({recipe_url})",
                            inline=False
                        )
                        embed.add_field(
                            name="🏷️ Slug przepisu",
                            value=f"`{ai_slug}`",
                            inline=True
                        )
                        embed.add_field(
                            name="📝 Metoda",
                            value="OpenAI parsing",
                            inline=True
                        )
                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="❌ Nie udało się utworzyć przepisu",
                            description="AI sparsował przepis, ale nie udało się go dodać do Mealie.",
                            color=discord.Color.red()
                        )
                        await interaction.followup.send(embed=embed)
                else:
                    embed = discord.Embed(
                        title="❌ Automatyczne parsowanie niemożliwe",
                        description="Zarówno Mealie jak i AI nie mogły sparsować tego przepisu.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed)

            except Exception as e:
                logger.error(f"Failed to process recipe from {url}: {e}")
                embed = discord.Embed(
                    title="❌ Błąd przetwarzania",
                    description=f"Wystąpił błąd podczas przetwarzania przepisu: {str(e)}",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Unexpected error in _handle_save_recipe_slash: {e}")
            # At this point interaction is already deferred, so always use followup
            try:
                await interaction.followup.send("❌ Wystąpił nieoczekiwany błąd.")
            except (discord.NotFound, discord.HTTPException) as send_error:
                # Interaction expired or Discord API error
                logger.error(f"Failed to send error message to Discord: {send_error}")

    async def _handle_mealie_info_slash(self, interaction: discord.Interaction):
        """Handle mealie_info command for slash commands"""
        embed = discord.Embed(
            title="🍳 Mealie Bot - Informacje",
            description="Bot do importowania przepisów z URL do aplikacji Mealie",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="📋 Dostępne komendy",
            value="""
/save_recipe [url] - Zapisz przepis z podanego URL
/mealie_info - Pokaż tę informację
            """,
            inline=False
        )

        embed.add_field(
            name="📝 Jak używać",
            value="1. Użyj `/save_recipe` i podaj URL przepisu\n2. Bot automatycznie pobierze i zapisze przepis w Mealie",
            inline=False
        )

        embed.add_field(
            name="🏷️ Tagowanie",
            value="Wszystkie przepisy są automatycznie tagowane jako:\n• **Discord Import**\n• **Verify** (do ręcznego sprawdzenia)",
            inline=False
        )

        embed.set_footer(text="Bot działa tylko na komendy slash - nie reaguje na zwykłe wiadomości z linkami")
        await interaction.response.send_message(embed=embed)

    async def _handle_save_recipe(self, ctx_or_message, url: str):
        """Handle recipe saving from either command or message"""
        try:
            # Send processing message
            processing_msg = await self._send_processing_message(ctx_or_message)

            # Validate URL
            if not self._is_valid_url(url):
                await self._send_error_message(
                    ctx_or_message,
                    "❌ Nieprawidłowy URL. Upewnij się, że podajesz prawidłowy link do przepisu."
                )
                return

            # Try to create recipe in Mealie
            try:
                recipe_data = await self.mealie_client.create_recipe_from_url(url)

                # Validate recipe data
                is_valid, reason = self.mealie_client.validate_recipe_data(recipe_data)

                if is_valid:
                    # Recipe created successfully
                    recipe_url = self.mealie_client.get_recipe_url(recipe_data.get('slug', ''))
                    await self._send_success_message(ctx_or_message, recipe_data, recipe_url)
                else:
                    # Recipe created but incomplete - try AI enhancement (future)
                    await self._send_partial_success_message(ctx_or_message, recipe_data, reason)

            except Exception as e:
                logger.error(f"Failed to create recipe from {url}: {e}")
                await self._send_error_message(
                    ctx_or_message,
                    f"❌ Nie udało się dodać przepisu. Błąd: {str(e)}"
                )

        except Exception as e:
            logger.error(f"Unexpected error in _handle_save_recipe: {e}")
            await self._send_error_message(
                ctx_or_message,
                "❌ Wystąpił nieoczekiwany błąd podczas przetwarzania przepisu."
            )

    async def _handle_help(self, ctx):
        """Handle help command"""
        help_text = """
**🤖 Mealie Discord Bot - Pomoc**

**Komendy:**
• `!mealie save_recipe <url>` - Zapisz przepis z podanego URL
• `!mealie help` - Pokaż tę pomoc

**Automatyczne wykrywanie:**
Bot automatycznie wykrywa linki do przepisów w wiadomościach i próbuje je zapisać.

**Przykład:**
```
!mealie save_recipe https://example.com/recipe
```
lub po prostu wyślij wiadomość z linkiem do przepisu.

**Tagi:**
Przepisy są automatycznie tagowane jako "Discord Import" i "Verify" do ręcznego sprawdzenia.
        """

        embed = discord.Embed(
            title="🍳 Mealie Bot - Pomoc",
            description=help_text,
            color=discord.Color.blue()
        )

        await ctx.send(embed=embed)

    def _extract_recipe_url(self, message_content: str) -> Optional[str]:
        """Extract recipe URL from message content"""
        # Simple regex for URL detection
        url_pattern = r'https?://[^\s<>"{}|\\^`[\]]+'
        urls = re.findall(url_pattern, message_content)

        # Return first URL if found
        return urls[0] if urls else None

    def _is_valid_url(self, url: str) -> bool:
        """Validate if URL is properly formatted"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    async def _send_processing_message(self, ctx_or_message) -> discord.Message:
        """Send processing message"""
        embed = discord.Embed(
            title="⚙️ Przetwarzanie przepisu...",
            description="Trwa dodawanie przepisu do Mealie. Proszę czekać...",
            color=discord.Color.orange()
        )

        if hasattr(ctx_or_message, 'send'):
            return await ctx_or_message.send(embed=embed)
        else:
            return await ctx_or_message.channel.send(embed=embed)

    async def _send_success_message(self, ctx_or_message, recipe_data: dict, recipe_url: str):
        """Send success message"""
        embed = discord.Embed(
            title="✅ Przepis dodany pomyślnie!",
            description=f"**{recipe_data.get('name', 'Przepis')}** został dodany do Mealie.",
            color=discord.Color.green()
        )

        embed.add_field(
            name="🔗 Link do przepisu",
            value=f"[Zobacz przepis]({recipe_url})",
            inline=False
        )

        embed.add_field(
            name="🏷️ Tagi",
            value=", ".join(recipe_data.get('tags', ['Brak tagów'])),
            inline=True
        )

        embed.set_footer(text="Przepis został oznaczony do weryfikacji")

        if hasattr(ctx_or_message, 'send'):
            await ctx_or_message.send(embed=embed)
        else:
            await ctx_or_message.channel.send(embed=embed)

    async def _send_partial_success_message(self, ctx_or_message, recipe_data: dict, reason: str):
        """Send partial success message for incomplete recipes"""
        embed = discord.Embed(
            title="⚠️ Przepis dodany częściowo",
            description=f"Przepis został dodany, ale brakuje niektórych elementów: {reason}",
            color=discord.Color.yellow()
        )

        recipe_url = self.mealie_client.get_recipe_url(recipe_data.get('slug', ''))
        embed.add_field(
            name="🔗 Link do przepisu",
            value=f"[Edytuj przepis]({recipe_url})",
            inline=False
        )

        if hasattr(ctx_or_message, 'send'):
            await ctx_or_message.send(embed=embed)
        else:
            await ctx_or_message.channel.send(embed=embed)

    async def _send_error_message(self, ctx_or_message, error_message: str):
        """Send error message"""
        embed = discord.Embed(
            title="❌ Błąd",
            description=error_message,
            color=discord.Color.red()
        )

        if hasattr(ctx_or_message, 'send'):
            await ctx_or_message.send(embed=embed)
        else:
            await ctx_or_message.channel.send(embed=embed)
    
    async def _handle_bulk_import(self, interaction: discord.Interaction, urls_string: str):
        """Handle bulk recipe import"""
        try:
            await interaction.response.defer()
        except:
            logger.error(f"Failed to defer bulk import interaction for user {interaction.user}")
            return
        
        # Parse URLs (split by comma, space, or newline)
        import re
        urls = [url.strip() for url in re.split(r'[,\s\n]+', urls_string) if url.strip()]
        
        if not urls:
            await interaction.followup.send("❌ Nie podano żadnych URL!")
            return
        
        if len(urls) > 10:
            await interaction.followup.send("❌ Maksymalnie 10 przepisów na raz!")
            return
        
        # Send initial status
        embed = discord.Embed(
            title="📦 Import zbiorczy rozpoczęty",
            description=f"Przetwarzam {len(urls)} przepisów...",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)
        
        # Process each URL
        success_count = 0
        failed_urls = []
        
        for i, url in enumerate(urls, 1):
            try:
                logger.info(f"Bulk import: Processing {i}/{len(urls)}: {url}")
                recipe_data = await self.mealie_client.create_recipe_from_url(url)
                
                if recipe_data.get('status') == 'created':
                    success_count += 1
                    logger.info(f"Bulk import: Successfully added recipe {i}/{len(urls)}")
                else:
                    failed_urls.append(url)
                    logger.warning(f"Bulk import: Failed to add recipe {i}/{len(urls)}: {url}")
                    
            except Exception as e:
                logger.error(f"Bulk import: Error processing {url}: {e}")
                failed_urls.append(url)
            
            # Small delay between recipes to avoid overwhelming Mealie
            if i < len(urls):
                await asyncio.sleep(2)
        
        # Send final status
        result_embed = discord.Embed(
            title="✅ Import zbiorczy zakończony",
            color=discord.Color.green() if not failed_urls else discord.Color.orange()
        )
        result_embed.add_field(
            name="Pomyślnie dodane",
            value=f"{success_count}/{len(urls)}",
            inline=True
        )
        
        if failed_urls:
            result_embed.add_field(
                name="Nieudane",
                value=f"{len(failed_urls)}/{len(urls)}",
                inline=True
            )
            failed_list = "\n".join([f"• {url[:50]}..." if len(url) > 50 else f"• {url}" for url in failed_urls[:5]])
            if len(failed_urls) > 5:
                failed_list += f"\n...i {len(failed_urls) - 5} więcej"
            result_embed.add_field(
                name="Nieudane URL",
                value=failed_list,
                inline=False
            )
        
        await interaction.followup.send(embed=result_embed)
    
    async def _handle_import_status(self, interaction: discord.Interaction):
        """Show retry queue status for user"""
        try:
            await interaction.response.defer()
        except:
            return
        
        tasks = self.retry_queue.get_user_tasks(interaction.user.id)
        
        if not tasks:
            embed = discord.Embed(
                title="📋 Status kolejki",
                description="Nie masz żadnych przepisów w kolejce retry.",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="📋 Twoje przepisy w kolejce",
            description=f"Masz {len(tasks)} przepisów w kolejce retry:",
            color=discord.Color.orange()
        )
        
        for task in tasks[:10]:  # Show max 10
            status_emoji = {
                RetryStatus.PENDING: "⏳",
                RetryStatus.RETRYING: "🔄",
                RetryStatus.SUCCESS: "✅",
                RetryStatus.FAILED: "❌"
            }.get(task.status, "❓")
            
            next_retry_str = task.next_retry.strftime("%H:%M") if task.status == RetryStatus.PENDING else "N/A"
            
            embed.add_field(
                name=f"{status_emoji} {task.url[:40]}...",
                value=f"Próba: {task.attempt}/{task.max_attempts} | Następna: {next_retry_str}",
                inline=False
            )
        
        if len(tasks) > 10:
            embed.set_footer(text=f"... i {len(tasks) - 10} więcej. Pokazano tylko pierwsze 10.")
        
        await interaction.followup.send(embed=embed)
